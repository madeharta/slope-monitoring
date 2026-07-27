"""Payload schema — envelope separated from measurements (context.md §6).

Supports heterogeneous sensors (soil moisture, pore pressure, tilt, rain,
piezometer) and microcontroller families without per-type schema changes.

Constraints enforced here:
- `timestamp` is timezone-aware with sub-second precision (maps to Postgres
  `timestamptz`). It is the *produce/ingress* time, used for latency.
- `site_id` and `depth_cm` are always present in every reading (required
  keys). `depth_cm` may be null only for genuinely surface / non-depth
  sensors; `value` may be null only for a bad reading, which `quality_flag`
  then explains.
- `quality_flag` is populated from the start (defaults to "ok").
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: str
    value: float | None  # null == bad/missing reading; quality_flag explains
    unit: str
    depth_cm: float | None  # required key; null only for surface/non-depth sensors
    quality_flag: str = "ok"

    @field_validator("quantity", "unit", "quality_flag")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    device_type: str
    site_id: str
    timestamp: datetime
    location: Location
    readings: list[Reading] = Field(min_length=1)

    @field_validator("device_id", "device_type", "site_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware (timestamptz)")
        return v

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> Envelope:
        return cls.model_validate_json(raw)
