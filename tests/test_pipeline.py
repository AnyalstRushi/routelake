import json
import unittest

from routelake import CONTRACT_DIR
from routelake.contracts import Contract
from routelake.events import GenConfig, generate_events, split_batches
from routelake.pipeline import (BatchConflictError, build_gold, connect, init_schema,
                                reconcile, run_batch)


def rec(i, **over):
    r = {"event_id": f"e{i}", "user_id": "u1", "event_type": "purchase", "category": "home",
         "price": 10.0, "quantity": 2, "event_ts": "2026-10-01T10:00:00+00:00",
         "ingest_ts": "2026-10-01T10:00:05+00:00"}
    r.update(over)
    return r


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.c = Contract.load(CONTRACT_DIR / "events_v1.json")
        self.conn = connect()
        init_schema(self.conn)

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_matches_ground_truth_exactly(self):
        for seed in (1, 42, 2026):
            conn = connect()
            init_schema(conn)
            ev, t = generate_events(GenConfig(seed=seed, n_events=1500))
            results = [run_batch(conn, f"b{i}", b, self.c) for i, b in enumerate(split_batches(ev, 4))]
            n = lambda sql: conn.execute(sql).fetchone()[0]
            self.assertEqual(n("SELECT COUNT(*) FROM silver_events"), t.valid_unique)
            self.assertEqual(n("SELECT COUNT(*) FROM quarantine_events"), t.defects)
            self.assertEqual(sum(r.duplicates for r in results), t.duplicates)
            self.assertEqual(n("SELECT SUM(is_late) FROM silver_events"), t.late)
            self.assertEqual(sum(r.received for r in results), t.emitted)
            build_gold(conn)
            self.assertEqual(reconcile(conn), [])

    def test_replay_is_noop(self):
        batch = [rec(1), rec(2), rec(3, price=-1)]
        first = run_batch(self.conn, "b1", batch, self.c)
        before = (self.count("bronze_events"), self.count("silver_events"), self.count("quarantine_events"))
        again = run_batch(self.conn, "b1", batch, self.c)
        after = (self.count("bronze_events"), self.count("silver_events"), self.count("quarantine_events"))
        self.assertFalse(first.replayed)
        self.assertTrue(again.replayed)
        self.assertEqual(before, after)

    def test_conflicting_replay_rejected_and_state_untouched(self):
        run_batch(self.conn, "b1", [rec(1)], self.c)
        with self.assertRaises(BatchConflictError):
            run_batch(self.conn, "b1", [rec(1), rec(2)], self.c)
        with self.assertRaises(BatchConflictError):
            run_batch(self.conn, "b1", [rec(1, price=99.0)], self.c)
        self.assertEqual(self.count("silver_events"), 1)

    def test_atomic_rollback_on_failure(self):
        class Boom(Contract):
            pass
        calls = {"n": 0}
        real = self.c.validate

        class FlakyContract:
            def validate(inner, record):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("simulated crash mid-batch")
                return real(record)
        with self.assertRaises(RuntimeError):
            run_batch(self.conn, "b1", [rec(i) for i in range(5)], FlakyContract())
        for t in ("bronze_events", "silver_events", "quarantine_events", "batch_log"):
            self.assertEqual(self.count(t), 0, t)
        # the same batch can then be retried cleanly
        r = run_batch(self.conn, "b1", [rec(i) for i in range(5)], self.c)
        self.assertEqual(r.silver_inserted, 5)
        self.assertEqual(reconcile(self.conn), [])

    def test_first_write_wins_dedup_across_batches(self):
        run_batch(self.conn, "b1", [rec(1, price=10.0)], self.c)
        r = run_batch(self.conn, "b2", [rec(1, price=999.0)], self.c)
        self.assertEqual(r.duplicates, 1)
        self.assertEqual(self.conn.execute("SELECT price FROM silver_events").fetchone()[0], 10.0)

    def test_late_flag_threshold(self):
        on_time = rec(1, ingest_ts="2026-10-03T10:00:00+00:00")        # exactly 48h
        late = rec(2, ingest_ts="2026-10-03T10:00:01+00:00")           # 48h + 1s
        run_batch(self.conn, "b1", [on_time, late], self.c)
        flags = dict(self.conn.execute("SELECT event_id, is_late FROM silver_events"))
        self.assertEqual(flags, {"e1": 0, "e2": 1})

    def test_timestamps_normalised_to_utc(self):
        run_batch(self.conn, "b1", [rec(1, event_ts="2026-10-01T23:30:00-05:00",
                                         ingest_ts="2026-10-01T23:31:00-05:00")], self.c)
        ts, day = self.conn.execute("SELECT event_ts, event_date FROM silver_events").fetchone()
        self.assertEqual(day, "2026-10-02")
        self.assertTrue(ts.startswith("2026-10-02T04:30:00"))

    def test_quarantine_keeps_payload_and_reasons(self):
        bad = rec(1, price=-5, quantity=0)
        run_batch(self.conn, "b1", [bad], self.c)
        reasons, payload = self.conn.execute("SELECT reasons, payload FROM quarantine_events").fetchone()
        self.assertIn("price:below_min", reasons)
        self.assertIn("quantity:below_min", reasons)
        self.assertEqual(json.loads(payload)["event_id"], "e1")

    def test_empty_batch_and_non_dict_records(self):
        r = run_batch(self.conn, "empty", [], self.c)
        self.assertEqual((r.received, r.silver_inserted), (0, 0))
        r = run_batch(self.conn, "weird", [None, "x", 5, rec(1)], self.c)
        self.assertEqual((r.quarantined, r.silver_inserted), (3, 1))
        self.assertEqual(reconcile(self.conn), [])

    def test_gold_matches_independent_python_calculation(self):
        ev, _ = generate_events(GenConfig(n_events=2000, seed=9))
        for i, b in enumerate(split_batches(ev, 3)):
            run_batch(self.conn, f"b{i}", b, self.c)
        build_gold(self.conn)
        seen, expected = set(), {}
        for e in ev:
            if self.c.validate(e) or e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
            if e["event_type"] == "purchase":
                key = (e["event_ts"][:10], e["category"])
                expected[key] = expected.get(key, 0.0) + e["price"] * e["quantity"]
        got = {(d, c): rev for d, c, rev in self.conn.execute(
            "SELECT event_date, category, revenue FROM gold_daily_revenue WHERE revenue > 0")}
        self.assertEqual(set(got), set(expected))
        for k, v in expected.items():
            self.assertAlmostEqual(got[k], v, places=1)

    def test_gold_rebuild_is_idempotent(self):
        ev, _ = generate_events(GenConfig(n_events=500))
        run_batch(self.conn, "b", ev, self.c)
        build_gold(self.conn)
        a = self.conn.execute("SELECT * FROM gold_daily_revenue").fetchall()
        f1 = self.conn.execute("SELECT * FROM gold_funnel").fetchall()
        build_gold(self.conn)
        self.assertEqual(a, self.conn.execute("SELECT * FROM gold_daily_revenue").fetchall())
        self.assertEqual(f1, self.conn.execute("SELECT * FROM gold_funnel").fetchall())

    def test_funnel_percentage_and_zero_views(self):
        run_batch(self.conn, "b", [
            rec(1, event_type="view"), rec(2, event_type="view"), rec(3, event_type="add_to_cart"),
            rec(4, category="beauty", event_type="purchase")], self.c)
        build_gold(self.conn)
        rows = {r[0]: r for r in self.conn.execute("SELECT * FROM gold_funnel")}
        self.assertEqual(rows["home"][4], 50.0)
        self.assertIsNone(rows["beauty"][4])          # no views -> NULL, never divide by zero

    def test_reconcile_detects_tampering(self):
        ev, _ = generate_events(GenConfig(n_events=400))
        run_batch(self.conn, "b", ev, self.c)
        build_gold(self.conn)
        self.assertEqual(reconcile(self.conn), [])
        self.conn.execute("DELETE FROM silver_events WHERE rowid IN (SELECT rowid FROM silver_events LIMIT 1)")
        self.assertTrue(reconcile(self.conn))

    def test_reconcile_detects_gold_drift(self):
        run_batch(self.conn, "b", [rec(1), rec(2)], self.c)
        build_gold(self.conn)
        self.conn.execute("UPDATE gold_daily_revenue SET revenue = revenue + 100")
        self.assertTrue(any("gold revenue" in f for f in reconcile(self.conn)))

    def test_reconcile_detects_unprocessed_bronze(self):
        run_batch(self.conn, "b", [rec(1)], self.c)
        self.conn.execute("UPDATE bronze_events SET processed = 0")
        self.assertTrue(any("unprocessed" in f for f in reconcile(self.conn)))

    def test_file_database_persists_and_resumes(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lake.db")
            c1 = connect(path)
            init_schema(c1)
            run_batch(c1, "b1", [rec(1), rec(2)], self.c)
            c1.close()
            c2 = connect(path)
            init_schema(c2)                              # safe to re-run
            self.assertTrue(run_batch(c2, "b1", [rec(1), rec(2)], self.c).replayed)
            self.assertEqual(run_batch(c2, "b2", [rec(3)], self.c).silver_inserted, 1)
            self.assertEqual(reconcile(c2), [])
            c2.close()


if __name__ == "__main__":
    unittest.main()
