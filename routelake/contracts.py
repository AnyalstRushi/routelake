"""Data contracts: declarative record validation with explicit reason codes."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TYPES = ("string", "number", "integer", "timestamp")


class ContractError(ValueError):
    """The contract definition itself is invalid."""


def parse_ts(value) -> datetime:
    """Parse an ISO-8601 timestamp into aware UTC. Naive input is taken as UTC."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = True
    enum: tuple | None = None
    min: float | None = None
    max: float | None = None
    min_length: int | None = None


@dataclass(frozen=True)
class Contract:
    name: str
    version: int
    fields: tuple
    additional_fields: str = "reject"   # "reject" | "allow"

    @classmethod
    def from_dict(cls, d: dict) -> "Contract":
        try:
            name, version, raw_fields = d["name"], int(d["version"]), d["fields"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"contract needs name, version, fields: {exc}") from exc
        if not isinstance(raw_fields, dict) or not raw_fields:
            raise ContractError("fields must be a non-empty object")
        additional = d.get("additional_fields", "reject")
        if additional not in ("reject", "allow"):
            raise ContractError("additional_fields must be 'reject' or 'allow'")
        fields = []
        for fname, spec in raw_fields.items():
            ftype = spec.get("type")
            if ftype not in TYPES:
                raise ContractError(f"{fname}: unknown type {ftype!r}")
            enum = spec.get("enum")
            if enum is not None and (not isinstance(enum, list) or not enum):
                raise ContractError(f"{fname}: enum must be a non-empty list")
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None and hi is not None and lo > hi:
                raise ContractError(f"{fname}: min > max")
            fields.append(Field(
                name=fname, type=ftype, required=bool(spec.get("required", True)),
                enum=tuple(enum) if enum else None, min=lo, max=hi,
                min_length=spec.get("min_length"),
            ))
        return cls(name=name, version=version, fields=tuple(fields),
                   additional_fields=additional)

    @classmethod
    def load(cls, path) -> "Contract":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self, record) -> list[str]:
        """Return reason codes; an empty list means the record is valid."""
        if not isinstance(record, dict):
            return ["record:not_an_object"]
        reasons: list[str] = []
        for f in self.fields:
            value = record.get(f.name)
            if value is None:
                if f.required:
                    reasons.append(f"{f.name}:missing")
                continue
            reasons.extend(self._check(f, value))
        if self.additional_fields == "reject":
            known = {f.name for f in self.fields}
            reasons.extend(f"{k}:unexpected_field" for k in sorted(set(record) - known))
        return reasons

    @staticmethod
    def _check(f: Field, v) -> list[str]:
        n = f.name
        if f.type == "string":
            if not isinstance(v, str):
                return [f"{n}:wrong_type"]
            out = []
            if f.min_length is not None and len(v.strip()) < f.min_length:
                out.append(f"{n}:too_short")
            if f.enum is not None and v not in f.enum:
                out.append(f"{n}:not_in_enum")
            return out
        if f.type in ("number", "integer"):
            is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
            if f.type == "integer":
                is_num = isinstance(v, int) and not isinstance(v, bool)
            if not is_num or (isinstance(v, float) and not math.isfinite(v)):
                return [f"{n}:wrong_type"]
            out = []
            if f.min is not None and v < f.min:
                out.append(f"{n}:below_min")
            if f.max is not None and v > f.max:
                out.append(f"{n}:above_max")
            return out
        # timestamp
        try:
            parse_ts(v)
        except (ValueError, TypeError):
            return [f"{n}:bad_timestamp"]
        return []
