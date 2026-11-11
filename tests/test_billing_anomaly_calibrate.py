import copy
import csv
import os
import tempfile
import unittest
from datetime import date

from routelake import CONFIG_DIR
from routelake.anomaly import detect, robust_scores
from routelake.billing import (BillingError, daily_series, parse_databricks, parse_snowflake,
                               read_csv)
from routelake.calibrate import calibrate
from routelake.cost_model import Assumptions, ConfigError, Workload, estimate
from routelake.fixtures import (DATABRICKS_COLUMNS, SNOWFLAKE_COLUMNS, databricks_rows,
                                snowflake_rows, write_csv)


class BillingTests(unittest.TestCase):
    def test_snowflake_parse_cost_and_day(self):
        rows = [{"START_TIME": "2026-10-03 13:00:00.000 -0700", "WAREHOUSE_NAME": "W", "CREDITS_USED": "2.5"}]
        (r,) = parse_snowflake(rows, 3.0)
        self.assertEqual((r.day, r.engine, r.resource, r.units, r.usd), (date(2026, 10, 3), "snowflake", "W", 2.5, 7.5))

    def test_column_names_case_insensitive(self):
        a = parse_snowflake([{"start_time": "2026-10-03", "warehouse_name": "W", "credits_used": 1}], 2.0)
        self.assertEqual(a[0].usd, 2.0)

    def test_databricks_skips_non_dbu_and_uses_sku_price(self):
        rows = [
            {"usage_date": "2026-10-01", "sku_name": "A", "usage_unit": "DBU", "usage_quantity": "10"},
            {"usage_date": "2026-10-01", "sku_name": "B", "usage_unit": "dbu", "usage_quantity": "10"},
            {"usage_date": "2026-10-01", "sku_name": "C", "usage_unit": "GB", "usage_quantity": "999"},
        ]
        recs, skipped = parse_databricks(rows, 1.0, {"B": 2.0})
        self.assertEqual(skipped, 1)
        self.assertEqual([r.usd for r in recs], [10.0, 20.0])

    def test_bad_rows_raise_with_line_numbers(self):
        bad_sets = [
            [{"START_TIME": "2026-10-01", "WAREHOUSE_NAME": "W"}],                              # missing credits
            [{"START_TIME": "xx", "WAREHOUSE_NAME": "W", "CREDITS_USED": "1"}],                # bad date
            [{"START_TIME": "2026-10-01", "WAREHOUSE_NAME": "W", "CREDITS_USED": "abc"}],      # NaN text
            [{"START_TIME": "2026-10-01", "WAREHOUSE_NAME": "W", "CREDITS_USED": "-1"}],       # negative
            [{"START_TIME": "2026-10-01", "WAREHOUSE_NAME": "W", "CREDITS_USED": "nan"}],      # non-finite
        ]
        for rows in bad_sets:
            with self.assertRaises(BillingError, msg=str(rows)) as ctx:
                parse_snowflake(rows, 3.0)
            self.assertIn("row 1", str(ctx.exception))
        with self.assertRaises(BillingError):
            parse_snowflake([], 0)
        with self.assertRaises(BillingError):
            parse_databricks([], -1)

    def test_daily_series_fills_gaps_with_zero(self):
        rows = [{"START_TIME": "2026-10-01", "WAREHOUSE_NAME": "W", "CREDITS_USED": "1"},
                {"START_TIME": "2026-10-04", "WAREHOUSE_NAME": "W", "CREDITS_USED": "2"},
                {"START_TIME": "2026-10-04", "WAREHOUSE_NAME": "W", "CREDITS_USED": "3"}]
        days, vals = daily_series(parse_snowflake(rows, 1.0))[("snowflake", "W")]
        self.assertEqual(len(days), 4)
        self.assertEqual(vals, [1.0, 0.0, 0.0, 5.0])
        self.assertEqual(daily_series([]), {})

    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.csv")
            rows = snowflake_rows(days=3)
            write_csv(p, SNOWFLAKE_COLUMNS, rows)
            back = read_csv(p)
            self.assertEqual(len(back), len(rows))
            self.assertAlmostEqual(sum(r.usd for r in parse_snowflake(back, 3.0)),
                                   sum(r.usd for r in parse_snowflake(rows, 3.0)), places=6)


class AnomalyTests(unittest.TestCase):
    def test_finds_exactly_the_planted_spikes(self):
        sf = parse_snowflake(snowflake_rows(spike_day=21, spike_wh="ADHOC_WH"), 3.0)
        db, _ = parse_databricks(databricks_rows(spike_day=14, spike_sku="ALL_PURPOSE_COMPUTE"), 0.7)
        found = {(a.engine, a.resource, a.day.isoformat()) for a in detect(daily_series(sf + db))}
        self.assertEqual(found, {("snowflake", "ADHOC_WH", "2026-10-22"),
                                 ("databricks", "ALL_PURPOSE_COMPUTE", "2026-10-15")})

    def test_no_false_positives_without_spike(self):
        for seed in range(25):
            sf = parse_snowflake(snowflake_rows(seed=seed, spike_mult=1.0), 3.0)
            db, _ = parse_databricks(databricks_rows(seed=seed, spike_mult=1.0), 0.7)
            self.assertEqual(detect(daily_series(sf + db)), [], f"seed {seed}")

    def test_flat_series_and_mad_zero_fallback(self):
        days = [date(2026, 10, d) for d in range(1, 11)]
        self.assertEqual(detect({("e", "r"): (days, [10.0] * 10)}), [])
        spiky = [10.0] * 9 + [200.0]                      # MAD == 0 but a clear spike
        (a,) = detect({("e", "r"): (days, spiky)})
        self.assertEqual(a.day, days[-1])

    def test_short_series_skipped_and_drops_ignored(self):
        days = [date(2026, 10, d) for d in range(1, 6)]
        self.assertEqual(detect({("e", "r"): (days, [1, 1, 1, 1, 500])}), [])
        days10 = [date(2026, 10, d) for d in range(1, 11)]
        self.assertEqual(detect({("e", "r"): (days10, [100.0] * 9 + [1.0])}), [])   # a drop is not flagged

    def test_tiny_absolute_changes_ignored(self):
        days = [date(2026, 10, d) for d in range(1, 11)]
        self.assertEqual(detect({("e", "r"): (days, [0.01] * 9 + [0.5])}, min_abs_usd=1.0), [])

    def test_spike_from_zero_baseline_explained(self):
        days = [date(2026, 10, d) for d in range(1, 11)]
        (a,) = detect({("e", "r"): (days, [0.0] * 9 + [50.0])})
        self.assertIn("from ~zero", a.explanation)

    def test_robust_scores_median_resists_outlier(self):
        med, scores = robust_scores([10, 11, 9, 10, 12, 10, 9, 1000])
        self.assertAlmostEqual(med, 10.0)
        self.assertGreater(scores[-1], 100)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        import json
        self.a = Assumptions.load(CONFIG_DIR / "assumptions.json")
        self.raw = json.loads((CONFIG_DIR / "assumptions.json").read_text())

    def synth(self, truth, engine="snowflake", kind="batch_etl"):
        spec = self.a.engines[engine]
        rows = []
        for size in list(spec.sizes)[:3]:
            for gb in (50, 200, 800):
                w = Workload("w", kind, gb, 1, 1e9)
                # runtime from the model using the *true* throughput
                units = spec.sizes[size]
                rt = spec.startup_seconds + gb / (truth * units ** self.a.scaling_exponent) * 60
                rows.append({"engine": engine, "kind": kind, "size": size, "scan_gb": gb, "runtime_s": rt})
        return rows

    def test_recovers_known_throughput(self):
        new, rep = calibrate(self.a, self.synth(7.77))
        self.assertAlmostEqual(new["engines"]["snowflake"]["gb_per_min_per_unit"]["batch_etl"], 7.77, places=4)
        self.assertEqual(rep["updated"]["snowflake/batch_etl"]["samples"], 9)
        Assumptions.from_dict(new)                         # result is itself valid
        self.assertEqual(self.a.raw["engines"]["snowflake"]["gb_per_min_per_unit"]["batch_etl"], 3.0)  # input untouched

    def test_model_roundtrip_after_calibration(self):
        new, _ = calibrate(self.a, self.synth(5.0, "databricks", "ml_training"))
        a2 = Assumptions.from_dict(new)
        spec = a2.engines["databricks"]
        w = Workload("w", "ml_training", 100, 1, 1e9)
        measured = spec.startup_seconds + 100 / (5.0 * spec.sizes["S"] ** a2.scaling_exponent) * 60
        self.assertAlmostEqual(estimate(w, spec, "S", a2.scaling_exponent).runtime_s, measured, places=3)

    def test_unusable_inputs(self):
        with self.assertRaises(ConfigError):
            calibrate(self.a, [])
        with self.assertRaises(ConfigError):
            calibrate(self.a, [{"engine": "snowflake", "kind": "sql_bi", "size": "XS", "scan_gb": 1, "runtime_s": 1}])  # < startup
        for bad in ({"engine": "oracle", "kind": "sql_bi", "size": "XS", "scan_gb": 1, "runtime_s": 9},
                    {"engine": "snowflake", "kind": "nope", "size": "XS", "scan_gb": 1, "runtime_s": 9},
                    {"engine": "snowflake", "kind": "sql_bi", "size": "XXL", "scan_gb": 1, "runtime_s": 9},
                    {"engine": "snowflake", "kind": "sql_bi", "size": "XS", "scan_gb": "x", "runtime_s": 9}):
            with self.assertRaises(ConfigError, msg=str(bad)):
                calibrate(self.a, [bad])


if __name__ == "__main__":
    unittest.main()
