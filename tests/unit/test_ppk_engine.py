import pytest
from ml.pipeline.preprocessing.ppk_engine import PPKSolveError, parse_pos_line
_GOOD_LINE = (
    "2026/09/15 10:30:15.000  -6.123456789  106.987654321   510.1234   1   9"
    "   0.0021   0.0018   0.0035   0.0002  -0.0004  -0.0001   1.0   32.4"
)
def test_parse_fix_quality_line():
    r = parse_pos_line(_GOOD_LINE)
    assert r.gnss_fix_type == 4
    assert abs(r.latitude - (-6.123456789)) < 1e-9
    assert abs(r.longitude - 106.987654321) < 1e-9
    assert abs(r.altitude_m - 510.1234) < 1e-4
    assert r.h_acc_m > 0
def test_parse_float_quality_line():
    line = _GOOD_LINE.replace("   1   9", "   2   9", 1)
    r = parse_pos_line(line)
    assert r.gnss_fix_type == 5
def test_unusable_quality_raises():
    line = _GOOD_LINE.replace("   1   9", "   6   9", 1)
    with pytest.raises(PPKSolveError):
        parse_pos_line(line)
def test_malformed_line_raises():
    with pytest.raises(PPKSolveError):
        parse_pos_line("not a pos line")
def test_missing_rtklib_binary_raises_ppksolveerror_not_filenotfounderror():
    from ml.pipeline.preprocessing.ppk_engine import RTKLibPPKEngine
    engine = RTKLibPPKEngine(
        base_reference_lat=-6.2, base_reference_lon=106.8, base_reference_alt_m=500.0,
        convbin_path="/definitely/does/not/exist/convbin",
        rnx2rtkp_path="/definitely/does/not/exist/rnx2rtkp",
    )
    with pytest.raises(PPKSolveError):
        engine.solve(b"\xb5\x62\x02\x15\x00\x00\x00\x00", b"\xb5\x62\x02\x15\x00\x00\x00\x00")
