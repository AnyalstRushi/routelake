"""Deterministic synthetic clickstream generator with exact, known defects.

Every defect, duplicate and late event is injected in a *counted* way so tests
can assert that the pipeline finds exactly what was planted (ground truth).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CATEGORIES = ("electronics", "fashion", "grocery", "home", "beauty")
EVENT_TYPES = ("view", "add_to_cart", "purchase")
DEFECT_KINDS = (
    "missing_user_id",
    "negative_price",
    "unknown_event_type",
    "bad_timestamp",
    "zero_quantity",
)


@dataclass(frozen=True)
class GenConfig:
    seed: int = 42
    n_events: int = 5000          # unique events before duplicates are appended
    days: int = 14
    start: str = "2026-10-01"     # ISO date, UTC
    defect_rate: float = 0.04
    duplicate_rate: float = 0.03
    late_rate: float = 0.02

    def validate(self) -> None:
        if self.n_events < 1:
            raise ValueError("n_events must be >= 1")
        if self.days < 1:
            raise ValueError("days must be >= 1")
        for name in ("defect_rate", "duplicate_rate", "late_rate"):
            v = getattr(self, name)
            if not 0.0 <= v <= 0.5:
                raise ValueError(f"{name} must be within [0, 0.5]")


@dataclass(frozen=True)
class GroundTruth:
    emitted: int            # records returned, duplicates included
    unique_events: int      # n_events
    defects: int            # records that violate the contract
    duplicates: int         # exact repeats of valid events
    late: int               # valid unique events that arrive > 48h late
    valid_unique: int       # what silver must contain
    defect_by_kind: dict


def generate_events(cfg: GenConfig = GenConfig()) -> tuple[list[dict], GroundTruth]:
    cfg.validate()
    rng = random.Random(cfg.seed)
    start = datetime.fromisoformat(cfg.start).replace(tzinfo=timezone.utc)
    n = cfg.n_events

    k_def = round(n * cfg.defect_rate)
    k_dup = round(n * cfg.duplicate_rate)
    k_late = round(n * cfg.late_rate)
    if k_def + k_late > n:
        raise ValueError("defect_rate + late_rate exceeds 100% of events")

    indices = list(range(n))
    defect_idx = set(rng.sample(indices, k_def))
    clean = [i for i in indices if i not in defect_idx]
    late_idx = set(rng.sample(clean, k_late))
    dup_idx = sorted(rng.sample(clean, min(k_dup, len(clean))))

    kinds_for_defects = {i: DEFECT_KINDS[j % len(DEFECT_KINDS)]
                         for j, i in enumerate(sorted(defect_idx))}

    events: list[dict] = []
    for i in indices:
        offset = rng.randrange(0, cfg.days * 86400)
        event_dt = start + timedelta(seconds=offset)
        delay = timedelta(hours=72 + rng.randrange(0, 48)) if i in late_idx \
            else timedelta(seconds=rng.randrange(1, 300))
        etype = rng.choices(EVENT_TYPES, weights=(70, 20, 10))[0]
        rec = {
            "event_id": f"evt-{cfg.seed}-{i:07d}",
            "user_id": f"u{rng.randrange(1, 1500):05d}",
            "event_type": etype,
            "category": rng.choice(CATEGORIES),
            "price": round(rng.uniform(1.0, 500.0), 2),
            "quantity": rng.randint(1, 3) if etype == "purchase" else 1,
            "event_ts": event_dt.isoformat(),
            "ingest_ts": (event_dt + delay).isoformat(),
        }
        kind = kinds_for_defects.get(i)
        if kind == "missing_user_id":
            rec["user_id"] = None
        elif kind == "negative_price":
            rec["price"] = -abs(rec["price"])
        elif kind == "unknown_event_type":
            rec["event_type"] = "teleport"
        elif kind == "bad_timestamp":
            rec["event_ts"] = "not-a-timestamp"
        elif kind == "zero_quantity":
            rec["quantity"] = 0
        events.append(rec)

    out = list(events)
    for i in dup_idx:
        original = events[i]
        pos = out.index(original)
        out.insert(rng.randint(pos + 1, len(out)), dict(original))

    by_kind = {k: 0 for k in DEFECT_KINDS}
    for k in kinds_for_defects.values():
        by_kind[k] += 1
    truth = GroundTruth(
        emitted=len(out),
        unique_events=n,
        defects=k_def,
        duplicates=len(dup_idx),
        late=k_late,
        valid_unique=n - k_def,
        defect_by_kind=by_kind,
    )
    return out, truth


def split_batches(events: list[dict], n_batches: int) -> list[list[dict]]:
    """Split into contiguous, near-equal batches (stable order)."""
    if n_batches < 1:
        raise ValueError("n_batches must be >= 1")
    size, rem = divmod(len(events), n_batches)
    batches, pos = [], 0
    for b in range(n_batches):
        step = size + (1 if b < rem else 0)
        batches.append(events[pos:pos + step])
        pos += step
    return batches
