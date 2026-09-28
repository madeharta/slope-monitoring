from __future__ import annotations
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from services.rinex_service.normalizer import normalize_rinex_transport


class RINEXParseError(ValueError):
    pass


@dataclass(frozen=True)
class RINEXMetadata:
    version: str | None
    data_type: str
    constellation: str | None
    station: str | None
    nominal_date: date | None
    record_first_epoch_utc: datetime | None
    record_last_epoch_utc: datetime | None
    navigation_valid_from_utc: datetime | None = None
    navigation_valid_until_utc: datetime | None = None
    container_format: str = "rinex"
    transport_compression: str = "none"

    @property
    def first_epoch_utc(self) -> datetime | None:
        return self.record_first_epoch_utc

    @property
    def last_epoch_utc(self) -> datetime | None:
        return self.record_last_epoch_utc

    def to_manifest_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["nominal_date"] = self.nominal_date.isoformat() if self.nominal_date else None
        for key in (
            "record_first_epoch_utc",
            "record_last_epoch_utc",
            "navigation_valid_from_utc",
            "navigation_valid_until_utc",
        ):
            timestamp = value[key]
            value[key] = timestamp.isoformat() if timestamp else None
        return value


_LEGACY_NAME = re.compile(
    r"^(?P<station>[A-Za-z0-9]{4})(?P<doy>\d{3})(?P<session>[A-Za-z0-9])\.(?P<yy>\d{2})(?P<kind>[A-Za-z])(?:\..*)?$"
)
_LONG_NAME_DATE = re.compile(r"^[A-Za-z0-9]{4,9}_[A-Z]_(?P<year>\d{4})(?P<doy>\d{3})\d{4}", re.IGNORECASE)
_RINEX3_NAV_EPOCH = re.compile(
    r"^[A-Z][0-9]{2}\s+(?P<year>\d{4})\s+(?P<month>\d{1,2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{1,2})\s+(?P<minute>\d{1,2})\s+(?P<second>\d{1,2}(?:\.\d+)?)"
)
_RINEX2_NAV_EPOCH = re.compile(
    r"^\s*\d{1,2}\s+(?P<year>\d{2})\s+(?P<month>\d{1,2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{1,2})\s+(?P<minute>\d{1,2})\s+(?P<second>\d{1,2}(?:\.\d+)?)"
)


def parse_rinex_file(path: str | Path) -> RINEXMetadata:
    source = Path(path)
    return parse_rinex_bytes(source.read_bytes(), original_name=source.name)


def parse_rinex_bytes(
    content: bytes,
    *,
    original_name: str | None = None,
    max_decompressed_bytes: int | None = None,
    max_expansion_ratio: float | None = None,
    decompression_timeout_s: float | None = None,
) -> RINEXMetadata:
    normalized = normalize_rinex_transport(
        content,
        max_decompressed_bytes=max_decompressed_bytes,
        max_expansion_ratio=max_expansion_ratio,
        timeout_s=decompression_timeout_s,
    )
    text = normalized.content.decode("ascii", errors="replace")
    lines = text.splitlines()
    if not lines:
        raise RINEXParseError("empty RINEX content")
    version = None
    data_type = "unknown"
    constellation = None
    station = None
    record_first_epoch = None
    record_last_epoch = None
    header_end = None
    saw_rinex_header = False
    compact_rinex = False
    for index, line in enumerate(lines[:500]):
        label = line[60:].strip() if len(line) >= 60 else ""
        upper = line.upper()
        if "CRINEX VERS / TYPE" in upper or "COMPACT RINEX FORMAT" in upper:
            compact_rinex = True
        if "RINEX VERSION / TYPE" in upper:
            saw_rinex_header = True
            version = line[:9].strip() or None
            type_char = line[20:21].upper() if len(line) > 20 else ""
            if "OBSERVATION DATA" in upper or type_char == "O":
                data_type = "observation"
            elif "NAVIGATION DATA" in upper or type_char in {"N", "G", "H", "J", "L", "C", "P"}:
                data_type = "navigation"
            constellation = _constellation_from_header(line)
        elif label == "MARKER NAME":
            station = line[:60].strip() or station
        elif label == "TIME OF FIRST OBS":
            record_first_epoch = _parse_header_epoch(line[:60])
        elif label == "TIME OF LAST OBS":
            record_last_epoch = _parse_header_epoch(line[:60])
        if "END OF HEADER" in upper:
            header_end = index
            break
    if not saw_rinex_header:
        raise RINEXParseError("missing RINEX VERSION / TYPE header")
    if compact_rinex and data_type not in {"observation", "unknown"}:
        raise RINEXParseError("Compact RINEX content must contain observation data")
    if compact_rinex and data_type == "unknown":
        data_type = "observation"
    file_station, nominal_date, filename_type = _infer_from_filename(original_name)
    if station is None:
        station = file_station
    if data_type == "unknown" and filename_type is not None:
        data_type = filename_type
    if data_type == "navigation" and header_end is not None:
        epochs = _parse_navigation_epochs(lines[header_end + 1 :])
        if epochs:
            if record_first_epoch is None:
                record_first_epoch = min(epochs)
            if record_last_epoch is None:
                record_last_epoch = max(epochs)
            if nominal_date is None:
                nominal_date = record_first_epoch.date()
    if nominal_date is None and record_first_epoch is not None:
        nominal_date = record_first_epoch.date()
    return RINEXMetadata(
        version=version,
        data_type=data_type,
        constellation=constellation,
        station=station.upper() if station else None,
        nominal_date=nominal_date,
        record_first_epoch_utc=record_first_epoch,
        record_last_epoch_utc=record_last_epoch,
        navigation_valid_from_utc=None,
        navigation_valid_until_utc=None,
        container_format="compact_rinex" if compact_rinex else "rinex",
        transport_compression=normalized.transport_compression,
    )


def _constellation_from_header(line: str) -> str | None:
    upper = line.upper()
    if "MIXED" in upper or (len(line) > 40 and line[40:41].upper() == "M"):
        return "MIXED"
    mapping = {
        "GPS": "GPS",
        "GLONASS": "GLONASS",
        "GALILEO": "GALILEO",
        "BEIDOU": "BEIDOU",
        "QZSS": "QZSS",
    }
    for needle, value in mapping.items():
        if needle in upper:
            return value
    system_char = line[40:41].upper() if len(line) > 40 else ""
    return {
        "G": "GPS",
        "R": "GLONASS",
        "E": "GALILEO",
        "C": "BEIDOU",
        "J": "QZSS",
    }.get(system_char)


def _parse_header_epoch(value: str) -> datetime | None:
    parts = value.split()
    if len(parts) < 6:
        return None
    try:
        return _utc_datetime(
            int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), float(parts[5])
        )
    except (TypeError, ValueError):
        return None


def _parse_navigation_epochs(lines: list[str]) -> list[datetime]:
    epochs: list[datetime] = []
    for line in lines:
        match = _RINEX3_NAV_EPOCH.match(line)
        if match:
            try:
                epochs.append(_match_datetime(match, rinex2=False))
            except ValueError:
                pass
            continue
        match = _RINEX2_NAV_EPOCH.match(line)
        if match:
            try:
                epochs.append(_match_datetime(match, rinex2=True))
            except ValueError:
                pass
    return epochs


def _match_datetime(match: re.Match[str], *, rinex2: bool) -> datetime:
    year = int(match.group("year"))
    if rinex2:
        year = 2000 + year if year < 80 else 1900 + year
    return _utc_datetime(
        year,
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        float(match.group("second")),
    )


def _utc_datetime(year: int, month: int, day: int, hour: int, minute: int, second: float) -> datetime:
    whole_second = int(second)
    microsecond = int(round((second - whole_second) * 1_000_000))
    if microsecond == 1_000_000:
        whole_second += 1
        microsecond = 0
    return datetime(year, month, day, hour, minute, whole_second, microsecond, tzinfo=timezone.utc)


def _infer_from_filename(name: str | None) -> tuple[str | None, date | None, str | None]:
    if not name:
        return None, None, None
    basename = Path(name).name
    legacy = _LEGACY_NAME.match(basename)
    if legacy:
        yy = int(legacy.group("yy"))
        year = 2000 + yy if yy < 80 else 1900 + yy
        nominal = datetime.strptime(f"{year}-{legacy.group('doy')}", "%Y-%j").date()
        kind_char = legacy.group("kind").lower()
        data_type = "observation" if kind_char in {"o", "d"} else "navigation" if kind_char in {"n", "g", "h", "j", "l", "c", "p"} else None
        return legacy.group("station").upper(), nominal, data_type
    long_match = _LONG_NAME_DATE.match(basename)
    if long_match:
        nominal = datetime.strptime(
            f"{long_match.group('year')}-{long_match.group('doy')}", "%Y-%j"
        ).date()
        station = basename.split("_", 1)[0][:4].upper() or None
        upper = basename.upper()
        data_type = "navigation" if "_MN." in upper or "_GN." in upper else "observation" if "_MO." in upper or "_GO." in upper else None
        return station, nominal, data_type
    return None, None, None
