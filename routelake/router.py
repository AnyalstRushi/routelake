"""Workload router: choose the cheapest engine that meets the latency SLO.

Includes hysteresis: switching away from the default engine requires a minimum
saving, so decisions do not flap on tiny cost differences.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cost_model import Assumptions, Plan, Workload, best_plan


@dataclass(frozen=True)
class Decision:
    workload: str
    kind: str
    chosen: Plan
    alternatives: dict          # engine name -> Plan
    default_engine: str
    savings_vs_default_pct: float
    reason: str


def route(wl: Workload, a: Assumptions) -> Decision:
    plans = {name: best_plan(wl, spec, a.scaling_exponent) for name, spec in a.engines.items()}
    default = plans[a.default_engine]
    feasible = {n: p for n, p in plans.items() if p.feasible}

    if not feasible:
        chosen = min(plans.values(), key=lambda p: (p.runtime_s, p.engine))
        return Decision(wl.name, wl.kind, chosen, plans, a.default_engine, 0.0,
                        f"No engine meets the {wl.latency_slo_s:.0f}s SLO; showing the fastest "
                        f"({chosen.engine} {chosen.size}, {chosen.runtime_s:.0f}s). Relax the SLO or add capacity.")

    cheapest = min(feasible.values(), key=lambda p: (p.daily_usd, p.engine))
    chosen, reason = cheapest, ""
    if a.default_engine in feasible and cheapest.engine != a.default_engine:
        saving = (default.daily_usd - cheapest.daily_usd) / default.daily_usd * 100.0
        if saving < a.min_savings_pct_to_route:
            chosen = default
            reason = (f"Kept default {a.default_engine}: {cheapest.engine} would save only "
                      f"{saving:.1f}% (< {a.min_savings_pct_to_route:.0f}% threshold).")
    if not reason:
        if chosen.engine == a.default_engine:
            reason = f"{chosen.engine} {chosen.size} is the cheapest option meeting the SLO."
        else:
            reason = (f"{chosen.engine} {chosen.size} meets the SLO at "
                      f"${chosen.daily_usd:,.2f}/day vs ${default.daily_usd:,.2f}/day on "
                      f"{a.default_engine}" + ("" if default.feasible else " (default misses the SLO)") + ".")
    savings = (default.daily_usd - chosen.daily_usd) / default.daily_usd * 100.0 if default.daily_usd else 0.0
    return Decision(wl.name, wl.kind, chosen, plans, a.default_engine, savings, reason)


def route_all(workloads: list[Workload], a: Assumptions) -> list[Decision]:
    return [route(w, a) for w in workloads]


def summarize(decisions: list[Decision], a: Assumptions) -> dict:
    routed = sum(d.chosen.daily_usd for d in decisions)
    per_engine = {}
    for name in a.engines:
        per_engine[name] = {
            "daily_usd": sum(d.alternatives[name].daily_usd for d in decisions),
            "slo_misses": sum(1 for d in decisions if not d.alternatives[name].feasible),
        }
    base = per_engine[a.default_engine]["daily_usd"]
    return {
        "routed_daily_usd": routed,
        "routed_monthly_usd": routed * 30,
        "routed_slo_misses": sum(1 for d in decisions if not d.chosen.feasible),
        "default_engine": a.default_engine,
        "all_on_engine": per_engine,
        "savings_vs_default_pct": (base - routed) / base * 100.0 if base else 0.0,
        "engine_mix": {n: sum(1 for d in decisions if d.chosen.engine == n) for n in a.engines},
    }
