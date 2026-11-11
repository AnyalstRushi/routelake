"""Calibrate throughput assumptions from your own measured runs.

Input CSV columns: engine, kind, size, scan_gb, runtime_s
Each sample implies  gb_per_min_per_unit = scan_gb / ((runtime_s - startup_s)/60) / units**exp
The median per (engine, kind) replaces the assumption.
"""
from __future__ import annotations

import copy
import statistics

from .cost_model import Assumptions, ConfigError


def calibrate(a: Assumptions, samples: list[dict]) -> tuple[dict, dict]:
    """Return (new_assumptions_dict, report). Raises ConfigError on unusable samples."""
    buckets: dict = {}
    skipped = 0
    for i, s in enumerate(samples, start=1):
        try:
            engine, kind, size = s["engine"], s["kind"], s["size"]
            scan_gb, runtime_s = float(s["scan_gb"]), float(s["runtime_s"])
            spec = a.engines[engine]
            units = spec.sizes[size]
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"sample {i}: invalid or unknown field: {exc}") from exc
        if kind not in spec.gb_per_min_per_unit:
            raise ConfigError(f"sample {i}: unknown kind {kind!r} for {engine}")
        work_s = runtime_s - spec.startup_seconds
        if scan_gb <= 0 or work_s <= 0:
            skipped += 1          # run was dominated by startup; no throughput signal
            continue
        gbpm = scan_gb / (work_s / 60.0) / units ** a.scaling_exponent
        buckets.setdefault((engine, kind), []).append(gbpm)

    if not buckets:
        raise ConfigError("no usable samples (all runs shorter than startup time?)")
    new = copy.deepcopy(a.raw)
    report = {"skipped": skipped, "updated": {}}
    for (engine, kind), vals in sorted(buckets.items()):
        old = new["engines"][engine]["gb_per_min_per_unit"][kind]
        med = statistics.median(vals)
        new["engines"][engine]["gb_per_min_per_unit"][kind] = round(med, 6)
        report["updated"][f"{engine}/{kind}"] = {"old": old, "new": round(med, 6), "samples": len(vals)}
    return new, report
