"""Config-driven runtime and cost model for Snowflake-like and Databricks-like engines.

All numbers come from `config/assumptions.json`. The model is deliberately small
and explicit so every output can be explained in an interview or a design review:

    runtime_s   = startup_s + scan_gb / (gb_per_min_per_unit * units**exp) * 60
    billed_s    = max(min_billed_s, runtime_s) + idle_tail_s
    idle_tail_s = min(auto_suspend_s, max(0, avg_gap_s - runtime_s))
    cost_run    = billed_s / 3600 * units * clusters * usd_per_unit_hour
    clusters    = ceil(concurrency / max_concurrency_per_cluster)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Assumptions or workload definition is invalid."""


@dataclass(frozen=True)
class EngineSpec:
    name: str
    usd_per_unit_hour: float
    min_billed_seconds: float
    auto_suspend_seconds: float
    startup_seconds: float
    max_concurrency_per_cluster: int
    sizes: dict
    gb_per_min_per_unit: dict


@dataclass(frozen=True)
class Assumptions:
    engines: dict
    scaling_exponent: float
    default_engine: str
    min_savings_pct_to_route: float
    raw: dict

    @classmethod
    def from_dict(cls, d: dict) -> "Assumptions":
        try:
            exp = float(d["scaling_exponent"])
            engines_raw = d["engines"]
            default_engine = d["default_engine"]
            hyst = float(d.get("min_savings_pct_to_route", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"assumptions missing/invalid field: {exc}") from exc
        if not 0 < exp <= 1:
            raise ConfigError("scaling_exponent must be in (0, 1]")
        if hyst < 0:
            raise ConfigError("min_savings_pct_to_route must be >= 0")
        if len(engines_raw) < 1:
            raise ConfigError("at least one engine required")
        if default_engine not in engines_raw:
            raise ConfigError(f"default_engine {default_engine!r} not in engines")
        engines = {}
        for name, e in engines_raw.items():
            try:
                spec = EngineSpec(
                    name=name,
                    usd_per_unit_hour=float(e["usd_per_unit_hour"]),
                    min_billed_seconds=float(e["min_billed_seconds"]),
                    auto_suspend_seconds=float(e["auto_suspend_seconds"]),
                    startup_seconds=float(e["startup_seconds"]),
                    max_concurrency_per_cluster=int(e["max_concurrency_per_cluster"]),
                    sizes={k: float(v) for k, v in e["sizes"].items()},
                    gb_per_min_per_unit={k: float(v) for k, v in e["gb_per_min_per_unit"].items()},
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ConfigError(f"engine {name}: invalid definition: {exc}") from exc
            if spec.usd_per_unit_hour <= 0:
                raise ConfigError(f"engine {name}: usd_per_unit_hour must be > 0")
            if min(spec.min_billed_seconds, spec.auto_suspend_seconds, spec.startup_seconds) < 0:
                raise ConfigError(f"engine {name}: seconds must be >= 0")
            if spec.max_concurrency_per_cluster < 1:
                raise ConfigError(f"engine {name}: max_concurrency_per_cluster must be >= 1")
            if not spec.sizes or min(spec.sizes.values()) <= 0:
                raise ConfigError(f"engine {name}: sizes must be positive")
            if not spec.gb_per_min_per_unit or min(spec.gb_per_min_per_unit.values()) <= 0:
                raise ConfigError(f"engine {name}: throughput must be positive")
            engines[name] = spec
        return cls(engines, exp, default_engine, hyst, d)

    @classmethod
    def load(cls, path) -> "Assumptions":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def kinds(self) -> set:
        sets = [set(e.gb_per_min_per_unit) for e in self.engines.values()]
        return set.intersection(*sets)


@dataclass(frozen=True)
class Workload:
    name: str
    kind: str
    scan_gb: float
    runs_per_day: float
    latency_slo_s: float
    concurrency: int = 1

    @classmethod
    def from_dict(cls, d: dict, kinds: set | None = None) -> "Workload":
        try:
            w = cls(name=str(d["name"]), kind=str(d["kind"]), scan_gb=float(d["scan_gb"]),
                    runs_per_day=float(d["runs_per_day"]),
                    latency_slo_s=float(d["latency_slo_s"]),
                    concurrency=int(d.get("concurrency", 1)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"workload invalid: {exc}") from exc
        if w.scan_gb <= 0 or w.runs_per_day <= 0 or w.latency_slo_s <= 0 or w.concurrency < 1:
            raise ConfigError(f"workload {w.name}: scan_gb, runs_per_day, latency_slo_s must be > 0 "
                              "and concurrency >= 1")
        if kinds is not None and w.kind not in kinds:
            raise ConfigError(f"workload {w.name}: unknown kind {w.kind!r}; known: {sorted(kinds)}")
        return w


def load_workloads(path, assumptions: Assumptions | None = None) -> list[Workload]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    kinds = assumptions.kinds if assumptions else None
    items = [Workload.from_dict(w, kinds) for w in raw["workloads"]]
    names = [w.name for w in items]
    if len(set(names)) != len(names):
        raise ConfigError("duplicate workload names")
    return items


@dataclass(frozen=True)
class Plan:
    engine: str
    size: str
    units: float
    clusters: int
    runtime_s: float
    cost_per_run: float
    daily_usd: float
    monthly_usd: float
    feasible: bool


def estimate(wl: Workload, engine: EngineSpec, size: str, exponent: float) -> Plan:
    units = engine.sizes[size]
    throughput = engine.gb_per_min_per_unit[wl.kind] * units ** exponent
    runtime = engine.startup_seconds + wl.scan_gb / throughput * 60.0
    avg_gap = 86400.0 / wl.runs_per_day
    idle_tail = min(engine.auto_suspend_seconds, max(0.0, avg_gap - runtime))
    billed = max(engine.min_billed_seconds, runtime) + idle_tail
    clusters = math.ceil(wl.concurrency / engine.max_concurrency_per_cluster)
    per_run = billed / 3600.0 * units * clusters * engine.usd_per_unit_hour
    daily = per_run * wl.runs_per_day
    return Plan(engine.name, size, units, clusters, runtime, per_run, daily,
                daily * 30.0, runtime <= wl.latency_slo_s)


def best_plan(wl: Workload, engine: EngineSpec, exponent: float) -> Plan:
    """Cheapest size meeting the SLO; if none, the fastest size (feasible=False)."""
    plans = [estimate(wl, engine, s, exponent) for s in engine.sizes]
    ok = [p for p in plans if p.feasible]
    if ok:
        return min(ok, key=lambda p: (p.daily_usd, p.units))
    return min(plans, key=lambda p: (p.runtime_s, p.daily_usd))
