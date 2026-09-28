from datetime import date, timezone
from services.rinex_service.parser import parse_rinex_bytes
def _header(version_line: str, *lines: str) -> bytes:
    body = [version_line, *lines, f"{'':60}END OF HEADER"]
    return ("\n".join(body) + "\n").encode()
def test_rinex2_legacy_nav_filename_and_epochs():
    payload = _header(
        "     2.11           NAVIGATION DATA     GPS                 RINEX VERSION / TYPE",
        f"{'CLBG':60}MARKER NAME",
    ) + (
        " 1 26  9 25  0  0  0.0 0.0 0.0 0.0\n"
        " 1 26  9 25 23 59 30.0 0.0 0.0 0.0\n"
    ).encode()
    meta = parse_rinex_bytes(payload, original_name="clbg2680.26n")
    assert meta.data_type == "navigation"
    assert meta.station == "CLBG"
    assert meta.nominal_date == date(2026, 9, 25)
    assert meta.first_epoch_utc.tzinfo == timezone.utc
    assert meta.last_epoch_utc.hour == 23
def test_rinex2_observation_filename_and_header_time():
    first = "  2026     9    25     0     0    0.0000000     GPS         TIME OF FIRST OBS"
    payload = _header(
        "     2.11           OBSERVATION DATA    G                   RINEX VERSION / TYPE",
        f"{'CLBG':60}MARKER NAME",
        first,
    )
    meta = parse_rinex_bytes(payload, original_name="clbg2680.26o")
    assert meta.data_type == "observation"
    assert meta.nominal_date == date(2026, 9, 25)
def test_rinex3_long_mixed_nav_filename():
    payload = _header(
        "     3.05           NAVIGATION DATA     M                   RINEX VERSION / TYPE",
    ) + b"G01 2026 09 27 00 00 00 0 0 0\n"
    meta = parse_rinex_bytes(payload, original_name="BRDC00IGS_R_20262700000_01D_MN.rnx")
    assert meta.data_type == "navigation"
    assert meta.constellation == "MIXED"
    assert meta.nominal_date == date(2026, 9, 27)
def test_invalid_non_rinex_rejected():
    import pytest
    with pytest.raises(ValueError, match="RINEX VERSION"):
        parse_rinex_bytes(b"not rinex", original_name="x.26n")
