import copy
import json
import random
import unittest

from routelake import CONFIG_DIR
from routelake.cost_model import (Assumptions, ConfigError, Workload, best_plan, estimate,
                                  load_workloads)
from routelake.router import route, route_all, summarize

RAW = json.loads((CONFIG_DIR / "assumptions.json").read_text())


def A(**patch):
    raw = copy.deepcopy(RAW)
    raw.update(patch)
    return Assumptions.from_dict(raw)


def W(**kw):
    base = dict(name="w", kind="batch_etl", scan_gb=100, runs_per_day=4, latency_slo_s=7200, concurrency=1)
    base.update(kw)
    return Workload.from_dict(base)


class CostModelTests(unittest.TestCase):
    def setUp(self):
        self.a = A()
        self.sf = self.a.engines["snowflake"]

    def test_hand_computed_example(self):
        # XS: 1 unit. 60 GB at 3 GB/min = 1200s + 2s startup = 1202s. 1 run/day -> idle tail 60s.
        p = estimate(W(scan_gb=60, runs_per_day=1), self.sf, "XS", 0.85)
        self.assertAlmostEqual(p.runtime_s, 1202.0, places=6)
        billed = 1202.0 + 60.0
        self.assertAlmostEqual(p.cost_per_run, billed / 3600 * 1 * 1 * 3.0, places=9)
        self.assertAlmostEqual(p.daily_usd, p.cost_per_run * 1, places=9)
        self.assertAlmostEqual(p.monthly_usd, p.daily_usd * 30, places=9)

    def test_min_billed_seconds_applies(self):
        p = estimate(W(scan_gb=0.01, kind="sql_bi", runs_per_day=1), self.sf, "XS", 0.85)
        self.assertLess(p.runtime_s, 60)
        self.assertAlmostEqual(p.cost_per_run, (60 + 60) / 3600 * 3.0, places=9)

    def test_idle_tail_shrinks_when_runs_are_frequent(self):
        sparse = estimate(W(scan_gb=1, kind="sql_bi", runs_per_day=1), self.sf, "XS", 0.85)
        dense = estimate(W(scan_gb=1, kind="sql_bi", runs_per_day=1440), self.sf, "XS", 0.85)
        self.assertLess(dense.cost_per_run, sparse.cost_per_run)

    def test_bigger_size_is_faster(self):
        w = W(scan_gb=500)
        times = [estimate(w, self.sf, s, 0.85).runtime_s for s in ("XS", "S", "M", "L", "XL")]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_concurrency_multiplies_clusters_and_cost(self):
        one = estimate(W(kind="sql_bi", concurrency=8), self.sf, "S", 0.85)
        three = estimate(W(kind="sql_bi", concurrency=17), self.sf, "S", 0.85)
        self.assertEqual((one.clusters, three.clusters), (1, 3))
        self.assertAlmostEqual(three.cost_per_run, one.cost_per_run * 3, places=9)

    def test_best_plan_is_cheapest_feasible_not_just_smallest(self):
        w = W(scan_gb=300, latency_slo_s=3600, runs_per_day=1)
        p = best_plan(w, self.sf, 0.85)
        self.assertTrue(p.feasible)
        feas = [estimate(w, self.sf, s, 0.85) for s in self.sf.sizes]
        self.assertEqual(p.daily_usd, min(x.daily_usd for x in feas if x.feasible))

    def test_infeasible_returns_fastest(self):
        w = W(scan_gb=100000, latency_slo_s=10)
        p = best_plan(w, self.sf, 0.85)
        self.assertFalse(p.feasible)
        self.assertEqual(p.size, "XL")

    def test_validation(self):
        bad_patches = [
            dict(scaling_exponent=0), dict(scaling_exponent=1.5), dict(default_engine="oracle"),
            dict(min_savings_pct_to_route=-1), dict(engines={}),
        ]
        for patch in bad_patches:
            with self.assertRaises(ConfigError, msg=str(patch)):
                A(**patch)
        for mutate in (lambda r: r["engines"]["snowflake"].update(usd_per_unit_hour=0),
                       lambda r: r["engines"]["snowflake"].update(sizes={}),
                       lambda r: r["engines"]["snowflake"].update(max_concurrency_per_cluster=0),
                       lambda r: r["engines"]["databricks"]["gb_per_min_per_unit"].update(sql_bi=-1),
                       lambda r: r["engines"]["databricks"].pop("sizes")):
            raw = copy.deepcopy(RAW)
            mutate(raw)
            with self.assertRaises(ConfigError):
                Assumptions.from_dict(raw)
        for bad in (dict(scan_gb=0), dict(runs_per_day=-1), dict(latency_slo_s=0),
                    dict(concurrency=0), dict(kind="quantum")):
            with self.assertRaises(ConfigError, msg=str(bad)):
                Workload.from_dict({**dict(name="w", kind="sql_bi", scan_gb=1, runs_per_day=1,
                                           latency_slo_s=1, concurrency=1), **bad}, self.a.kinds)

    def test_shipped_configs_load(self):
        ws = load_workloads(CONFIG_DIR / "workloads.json", self.a)
        self.assertGreaterEqual(len(ws), 5)

    def test_duplicate_workload_names_rejected(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "w.json")
            w = dict(name="x", kind="sql_bi", scan_gb=1, runs_per_day=1, latency_slo_s=10)
            with open(p, "w") as fh:
                fh.write(json.dumps({"workloads": [w, w]}))
            with self.assertRaises(ConfigError):
                load_workloads(p, self.a)


class RouterTests(unittest.TestCase):
    def test_chosen_is_cheapest_feasible(self):
        a = A(min_savings_pct_to_route=0.0)
        for w in load_workloads(CONFIG_DIR / "workloads.json", a):
            d = route(w, a)
            feasible = [p for p in d.alternatives.values() if p.feasible]
            self.assertTrue(feasible)
            self.assertAlmostEqual(d.chosen.daily_usd, min(p.daily_usd for p in feasible), places=9)

    def test_hysteresis_keeps_default_on_small_savings(self):
        # Databricks is ~10% cheaper for this job: switches when threshold is 0, stays when it is 25
        w = W(name="close", scan_gb=20, runs_per_day=1, latency_slo_s=86400)
        strict = route(w, A(min_savings_pct_to_route=0.0))
        sticky = route(w, A(min_savings_pct_to_route=25.0))
        self.assertEqual(strict.chosen.engine, "databricks")
        self.assertEqual(sticky.chosen.engine, "snowflake")
        self.assertIn("Kept default", sticky.reason)
        self.assertEqual(sticky.savings_vs_default_pct, 0.0)

    def test_hysteresis_never_hurts_default_cost(self):
        rng = random.Random(1)
        a = A()
        for _ in range(300):
            w = W(name="r", kind=rng.choice(["sql_bi", "batch_etl", "ml_training"]),
                  scan_gb=rng.uniform(0.5, 3000), runs_per_day=rng.choice([1, 4, 24, 96, 288]),
                  latency_slo_s=rng.uniform(15, 20000), concurrency=rng.randint(1, 30))
            d = route(w, a)
            default = d.alternatives[a.default_engine]
            if default.feasible:
                self.assertLessEqual(d.chosen.daily_usd, default.daily_usd + 1e-9)
                self.assertTrue(d.chosen.feasible)

    def test_infeasible_everywhere_is_reported_not_hidden(self):
        d = route(W(scan_gb=1e6, latency_slo_s=5), A())
        self.assertFalse(d.chosen.feasible)
        self.assertIn("No engine meets", d.reason)

    def test_default_infeasible_forces_switch(self):
        a = A()
        w = W(kind="ml_training", scan_gb=2000, latency_slo_s=15000, runs_per_day=1)
        d = route(w, a)
        self.assertFalse(d.alternatives["snowflake"].feasible)
        self.assertTrue(d.alternatives["databricks"].feasible)
        self.assertEqual(d.chosen.engine, "databricks")
        self.assertIn("misses the SLO", d.reason)

    def test_routing_is_deterministic(self):
        a = A()
        ws = load_workloads(CONFIG_DIR / "workloads.json", a)
        self.assertEqual([d.chosen for d in route_all(ws, a)], [d.chosen for d in route_all(ws, a)])

    def test_summary_consistency(self):
        a = A()
        ws = load_workloads(CONFIG_DIR / "workloads.json", a)
        ds = route_all(ws, a)
        s = summarize(ds, a)
        self.assertAlmostEqual(s["routed_daily_usd"], sum(d.chosen.daily_usd for d in ds), places=9)
        self.assertAlmostEqual(s["routed_monthly_usd"], s["routed_daily_usd"] * 30, places=9)
        self.assertEqual(sum(s["engine_mix"].values()), len(ws))
        self.assertLessEqual(s["routed_daily_usd"], s["all_on_engine"][a.default_engine]["daily_usd"] + 1e-9)
        base = s["all_on_engine"][a.default_engine]["daily_usd"]
        self.assertAlmostEqual(s["savings_vs_default_pct"], (base - s["routed_daily_usd"]) / base * 100, places=9)


if __name__ == "__main__":
    unittest.main()
