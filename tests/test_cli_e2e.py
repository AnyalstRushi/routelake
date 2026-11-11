import contextlib
import io
import json
import os
import tempfile
import unittest

from routelake import CONFIG_DIR, ROOT, __version__
from routelake.cli import main


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_demo_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run(["demo", "--out", os.path.join(d, "r"), "--data", os.path.join(d, "data")])
            self.assertEqual(code, 0, out)
            report = json.loads(read(d, "r", "latest.json"))
            self.assertTrue(report["pipeline"]["matches_ground_truth"])
            self.assertEqual(report["pipeline"]["reconciliation_failures"], [])
            self.assertTrue(report["pipeline"]["replay_was_noop"])
            self.assertEqual(report["routing"]["summary"]["routed_slo_misses"], 0)
            self.assertEqual(len(report["billing"]["anomalies"]), 2)
            self.assertIn("RouteLake demo report", read(d, "r", "latest.md"))

    def test_demo_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a", "b"):
                run(["demo", "--out", os.path.join(d, name), "--data", os.path.join(d, "data")])
            self.assertEqual(read(d, "a", "latest.json"), read(d, "b", "latest.json"))

    def test_committed_sample_report_is_current(self):
        with tempfile.TemporaryDirectory() as d:
            run(["demo", "--out", d, "--data", str(ROOT / "data" / "sample")])
            self.assertEqual(read(d, "latest.json"),
                             (ROOT / "reports" / "latest.json").read_text(),
                             "reports/latest.json is stale: run `python -m routelake demo`")

    def test_route_command_and_bad_paths(self):
        code, out, _ = run(["route"])
        self.assertEqual(code, 0)
        self.assertIn("routed_daily_usd", json.loads(out)["summary"])
        code, _, err = run(["route", "--workloads", "/nope/missing.json"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_calibrate_command(self):
        with tempfile.TemporaryDirectory() as d:
            samples = os.path.join(d, "s.csv")
            with open(samples, "w") as fh:
                fh.write("engine,kind,size,scan_gb,runtime_s\n")
                fh.write("snowflake,batch_etl,XS,60,1002\n")
            out_path = os.path.join(d, "out.json")
            code, out, _ = run(["calibrate", "--samples", samples, "--out", out_path])
            self.assertEqual(code, 0, out)
            new = json.loads(read(out_path))
            self.assertAlmostEqual(new["engines"]["snowflake"]["gb_per_min_per_unit"]["batch_etl"], 3.6, places=3)
            code, _, err = run(["calibrate", "--samples", "/nope.csv", "--out", out_path])
            self.assertEqual(code, 2)

    def test_version_and_usage_errors(self):
        code, out, _ = run(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)
        code, _, _ = run([])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
