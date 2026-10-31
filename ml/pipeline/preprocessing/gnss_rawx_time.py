"""4G GNSS RXM-RAWX epoch validation. No implicit offset correction.

Accepts known source timestamp semantics (UTC or WIB wall-clock) ONLY when
consistent to <=10 seconds with the validated GNSS frame. Returns GNSS UTC.
No firmware-time claim is made; use UTC-aware telemetry metadata in future.
"""
from datetime import datetime, timedelta, timezone
import math
import struct

GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
MAX_TIMESTAMP_DIFFERENCE_SECONDS = 10.0


def canonical_rawx_utc(raw: bytes, source_timestamp_as_utc: datetime) -> datetime:
    if source_timestamp_as_utc.tzinfo is None:
        raise ValueError("source timestamp must be timezone-aware")
    if len(raw) < 24 or raw[:4] != b"\xb5\x62\x02\x15":
        raise ValueError("GNSS time unverified: expected UBX-RXM-RAWX")
    length = int.from_bytes(raw[4:6], "little")
    if length + 8 != len(raw) or length < 16:
        raise ValueError("GNSS time unverified: RAWX length mismatch")
    ck_a = ck_b = 0
    for octet in raw[2:-2]:
        ck_a = (ck_a + octet) & 255
        ck_b = (ck_b + ck_a) & 255
    if raw[-2:] != bytes((ck_a, ck_b)):
        raise ValueError("GNSS time unverified: UBX checksum mismatch")
    rcv_tow, week, leap_seconds, num_meas, rec_stat, version = struct.unpack_from("<dHbBBB", raw, 6)
    if (not math.isfinite(rcv_tow) or not (0 <= rcv_tow < 604800)
            or not (0 <= leap_seconds < 64) or not (rec_stat & 0x01)
            or week <= 0 or num_meas < 1):
        raise ValueError("GNSS time unverified: invalid GNSS timing flags or fields")
    utc = GPS_EPOCH + timedelta(weeks=week, seconds=rcv_tow - leap_seconds)
    source_utc = source_timestamp_as_utc.astimezone(timezone.utc)
    delta = (source_utc - utc).total_seconds()
    # No correction is inferred for arbitrary mismatches. Validate against
    # the two known contract interpretations; never mass shift timestamps.
    if min(abs(delta), abs(delta - 7 * 3600)) > MAX_TIMESTAMP_DIFFERENCE_SECONDS:
        raise ValueError(f"source timestamp differs from RAWX GNSS time by {delta:.3f}s")
    return utc
