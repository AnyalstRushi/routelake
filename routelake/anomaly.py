"""Robust spend-anomaly detection (median/MAD modified z-score)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Anomaly:
    day: date
    engine: str
    resource: str
    usd: float
    baseline_usd: float
    score: float
    explanation: str


def robust_scores(values: list[float]) -> tuple[float, list[float]]:
    """Return (median, modified z-scores). Falls back to mean abs deviation when MAD is 0."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    if mad > 0:
        return med, [0.6745 * (v - med) / mad for v in values]
    mean_ad = sum(abs(v - med) for v in values) / len(values)
    if mean_ad > 0:
        return med, [(v - med) / (1.253314 * mean_ad) for v in values]
    return med, [0.0] * len(values)


def detect(series_map: dict, threshold: float = 3.5, min_points: int = 7,
           min_abs_usd: float = 1.0, min_ratio: float = 1.5) -> list[Anomaly]:
    """Flag cost *increases* that are statistically unusual AND materially large.

    Three gates must all pass: robust z >= threshold, absolute increase >= min_abs_usd,
    and value >= min_ratio x the series median. The ratio gate stops very smooth series
    (tiny MAD) from alerting on a 10% wobble.
    """
    out: list[Anomaly] = []
    for (engine, resource), (days, values) in series_map.items():
        if len(values) < min_points:
            continue
        med, scores = robust_scores(values)
        for day, v, s in zip(days, values, scores):
            if s >= threshold and (v - med) >= min_abs_usd and v >= med * min_ratio:
                ratio = v / med if med > 0 else float("inf")
                ratio_txt = f"{ratio:.1f}x" if ratio != float("inf") else "from ~zero"
                out.append(Anomaly(
                    day, engine, resource, v, med, s,
                    f"{engine}/{resource} spent ${v:,.2f} on {day.isoformat()} vs a typical "
                    f"${med:,.2f} ({ratio_txt}); robust z={s:.1f}"))
    return sorted(out, key=lambda a: (-a.score, a.day))
