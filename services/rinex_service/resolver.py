from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from services.rinex_service.cache import CachedRINEXArtifact, RINEXCache, RINEXCacheError
from services.rinex_service.parser import RINEXMetadata, RINEXParseError, parse_rinex_file


class RINEXResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedNavigation:
    artifact: CachedRINEXArtifact
    metadata: RINEXMetadata


class RINEXNavigationResolver:
    def __init__(self, cache: RINEXCache) -> None:
        self.cache = cache

    def resolve(self, observed_at: datetime, *, station: str | None = None) -> ResolvedNavigation:
        timestamp = _as_utc(observed_at)
        station_key = station.strip().upper() if station else None
        candidates: list[tuple[tuple[int, int, str], ResolvedNavigation]] = []
        for manifest_path in sorted(self.cache.root.glob("*/*/manifest.json")):
            digest = manifest_path.parent.name
            try:
                artifact = self.cache.resolve(digest)
                metadata = _metadata_for_artifact(artifact)
            except (RINEXCacheError, RINEXParseError, OSError, ValueError, json.JSONDecodeError):
                continue
            if metadata.data_type != "navigation":
                continue
            if metadata.nominal_date != timestamp.date():
                continue
            if station_key is not None and metadata.station != station_key:
                continue
            mixed_bonus = int(metadata.constellation == "MIXED")
            station_bonus = int(station_key is not None and metadata.station == station_key)
            score = (station_bonus, mixed_bonus, artifact.sha256)
            candidates.append((score, ResolvedNavigation(artifact=artifact, metadata=metadata)))
        if not candidates:
            label = f" for station {station_key}" if station_key else ""
            raise RINEXResolutionError(
                f"no cached RINEX navigation candidate for UTC date {timestamp.date().isoformat()}{label}"
            )
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]


def _metadata_for_artifact(artifact: CachedRINEXArtifact) -> RINEXMetadata:
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    rinex = manifest.get("metadata", {}).get("rinex")
    if isinstance(rinex, dict):
        record_first = _parse_datetime(
            rinex.get("record_first_epoch_utc", rinex.get("first_epoch_utc"))
        )
        record_last = _parse_datetime(
            rinex.get("record_last_epoch_utc", rinex.get("last_epoch_utc"))
        )
        nominal_date = _parse_date(rinex.get("nominal_date"))
        if nominal_date is None and record_first is not None:
            nominal_date = record_first.date()
        return RINEXMetadata(
            version=rinex.get("version"),
            data_type=str(rinex.get("data_type", "unknown")),
            constellation=rinex.get("constellation"),
            station=str(rinex.get("station")).upper() if rinex.get("station") else None,
            nominal_date=nominal_date,
            record_first_epoch_utc=record_first,
            record_last_epoch_utc=record_last,
            navigation_valid_from_utc=_parse_datetime(rinex.get("navigation_valid_from_utc")),
            navigation_valid_until_utc=_parse_datetime(rinex.get("navigation_valid_until_utc")),
            container_format=str(rinex.get("container_format", "rinex")),
            transport_compression=str(rinex.get("transport_compression", "none")),
        )
    return parse_rinex_file(artifact.path)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise RINEXResolutionError("observed_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value))


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
