import math
import unittest

from routelake import CONTRACT_DIR
from routelake.contracts import Contract, ContractError, parse_ts
from routelake.events import GenConfig, generate_events, split_batches


def good():
    return {"event_id": "e1", "user_id": "u1", "event_type": "purchase", "category": "home",
            "price": 10.5, "quantity": 2, "event_ts": "2026-10-01T10:00:00+00:00",
            "ingest_ts": "2026-10-01T10:00:05+00:00"}


class GeneratorTests(unittest.TestCase):
    def test_deterministic(self):
        a, ta = generate_events(GenConfig(seed=5, n_events=500))
        b, tb = generate_events(GenConfig(seed=5, n_events=500))
        self.assertEqual(a, b)
        self.assertEqual(ta, tb)

    def test_seed_changes_output(self):
        a, _ = generate_events(GenConfig(seed=1, n_events=300))
        b, _ = generate_events(GenConfig(seed=2, n_events=300))
        self.assertNotEqual(a, b)

    def test_ground_truth_arithmetic(self):
        ev, t = generate_events(GenConfig(n_events=1000))
        self.assertEqual(len(ev), t.emitted)
        self.assertEqual(t.emitted, t.unique_events + t.duplicates)
        self.assertEqual(t.valid_unique, t.unique_events - t.defects)
        self.assertEqual(sum(t.defect_by_kind.values()), t.defects)

    def test_unique_ids_apart_from_duplicates(self):
        ev, t = generate_events(GenConfig(n_events=800))
        self.assertEqual(len({e["event_id"] for e in ev}), t.unique_events)

    def test_duplicates_come_after_their_original(self):
        ev, _ = generate_events(GenConfig(n_events=800))
        seen = set()
        for e in ev:
            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
        first_pos = {}
        for i, e in enumerate(ev):
            first_pos.setdefault(e["event_id"], i)
        for i, e in enumerate(ev):
            self.assertGreaterEqual(i, first_pos[e["event_id"]])

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            generate_events(GenConfig(n_events=0))
        with self.assertRaises(ValueError):
            generate_events(GenConfig(defect_rate=0.9))
        with self.assertRaises(ValueError):       # rounding makes defects + late exceed events
            generate_events(GenConfig(defect_rate=0.5, late_rate=0.5, n_events=3))

    def test_zero_rates_produce_clean_data(self):
        ev, t = generate_events(GenConfig(n_events=200, defect_rate=0, duplicate_rate=0, late_rate=0))
        c = Contract.load(CONTRACT_DIR / "events_v1.json")
        self.assertEqual(t.emitted, 200)
        self.assertTrue(all(c.validate(e) == [] for e in ev))

    def test_split_batches_preserves_everything(self):
        ev, _ = generate_events(GenConfig(n_events=333))
        for n in (1, 2, 7, 50):
            parts = split_batches(ev, n)
            self.assertEqual(len(parts), n)
            self.assertEqual([x for p in parts for x in p], ev)
            self.assertLessEqual(max(map(len, parts)) - min(map(len, parts)), 1)
        with self.assertRaises(ValueError):
            split_batches(ev, 0)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.c = Contract.load(CONTRACT_DIR / "events_v1.json")

    def test_good_record_passes(self):
        self.assertEqual(self.c.validate(good()), [])

    def test_every_planted_defect_kind_is_caught(self):
        ev, t = generate_events(GenConfig(n_events=1000, duplicate_rate=0, late_rate=0))
        bad = [e for e in ev if self.c.validate(e)]
        self.assertEqual(len(bad), t.defects)

    def test_reason_codes(self):
        cases = {
            "user_id": (None, "user_id:missing"),
            "event_type": ("teleport", "event_type:not_in_enum"),
            "price": (-1, "price:below_min"),
            "quantity": (0, "quantity:below_min"),
            "event_ts": ("garbage", "event_ts:bad_timestamp"),
        }
        for field, (value, code) in cases.items():
            r = good()
            r[field] = value
            self.assertIn(code, self.c.validate(r), field)

    def test_type_strictness(self):
        for field, value in (("price", True), ("price", "5"), ("price", math.nan),
                             ("price", math.inf), ("quantity", 2.0), ("quantity", True),
                             ("user_id", 5), ("event_ts", 12345)):
            r = good()
            r[field] = value
            self.assertTrue(self.c.validate(r), f"{field}={value!r} should fail")

    def test_whitespace_only_string_is_too_short(self):
        r = good()
        r["user_id"] = "   "
        self.assertIn("user_id:too_short", self.c.validate(r))

    def test_unexpected_field_rejected_or_allowed(self):
        r = good()
        r["surprise"] = 1
        self.assertIn("surprise:unexpected_field", self.c.validate(r))
        d = {"name": "x", "version": 1, "additional_fields": "allow",
             "fields": {"a": {"type": "string"}}}
        self.assertEqual(Contract.from_dict(d).validate({"a": "x", "b": 2}), [])

    def test_non_dict_records(self):
        for bad in (None, [], "str", 5):
            self.assertEqual(self.c.validate(bad), ["record:not_an_object"])

    def test_timestamp_formats(self):
        for ok in ("2026-10-01T10:00:00Z", "2026-10-01T10:00:00+05:30", "2026-10-01T10:00:00",
                   "2026-10-01"):
            self.assertEqual(parse_ts(ok).tzinfo is not None, True)
        self.assertEqual(parse_ts("2026-10-01T10:00:00+05:30").hour, 4)
        self.assertEqual(parse_ts("2026-10-01T10:00:00+05:30").minute, 30)
        with self.assertRaises(ValueError):
            parse_ts("nope")
        with self.assertRaises(ValueError):
            parse_ts(None)

    def test_invalid_contract_definitions(self):
        bad = [
            {},
            {"name": "x", "version": 1, "fields": {}},
            {"name": "x", "version": 1, "fields": {"a": {"type": "blob"}}},
            {"name": "x", "version": 1, "fields": {"a": {"type": "number", "min": 5, "max": 1}}},
            {"name": "x", "version": 1, "fields": {"a": {"type": "string", "enum": []}}},
            {"name": "x", "version": 1, "additional_fields": "maybe", "fields": {"a": {"type": "string"}}},
        ]
        for d in bad:
            with self.assertRaises(ContractError, msg=str(d)):
                Contract.from_dict(d)

    def test_optional_field_may_be_absent(self):
        c = Contract.from_dict({"name": "x", "version": 1,
                                "fields": {"a": {"type": "string", "required": False}}})
        self.assertEqual(c.validate({}), [])


if __name__ == "__main__":
    unittest.main()
