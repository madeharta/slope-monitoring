from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import gzip
import pytest
from ml.pipeline.preprocessing.ppk_engine import (
    PPK_OUTPUT_SCHEMA_VERSION,
    PPKSolveError,
    RTKLibPPKEngine,
    build_convbin_command,
    parse_pos_file,
    parse_pos_line,
)

_GOOD_LINE = (
    "2026/09/15 10:30:15.000  -6.123456789  106.987654321   510.1234   1   9"
    "   0.0021   0.0018   0.0035   0.0002  -0.0004  -0.0001   1.0   32.4"
)


def test_parse_fix_quality_line_preserves_rtklib_semantics():
    r = parse_pos_line(_GOOD_LINE)
    assert r.rtklib_quality == 1
    assert r.satellites == 9
    assert r.timestamp_utc == datetime(2026, 9, 15, 10, 30, 15, tzinfo=timezone.utc)
    assert abs(r.latitude - (-6.123456789)) < 1e-9
    assert abs(r.longitude - 106.987654321) < 1e-9
    assert abs(r.ellipsoidal_height_m - 510.1234) < 1e-4
    assert r.h_acc_m > 0
    assert r.age_s == 1.0
    assert r.ratio == 32.4


def test_parse_float_quality_line_is_not_mapped_to_device_fix_type():
    line = _GOOD_LINE.replace("   1   9", "   2   9", 1)
    r = parse_pos_line(line)
    assert r.rtklib_quality == 2
    assert not hasattr(r, "gnss_fix_type")


def test_valid_non_ppk_quality_is_preserved_for_downstream_gate():
    line = _GOOD_LINE.replace("   1   9", "   6   9", 1)
    r = parse_pos_line(line)
    assert r.rtklib_quality == 6




def test_signed_negative_differential_age_is_preserved():
    line = _GOOD_LINE.replace("   1.0   32.4", " -35.99    0.0")
    r = parse_pos_line(line)
    assert r.age_s == -35.99
    assert r.ratio == 0.0

def test_invalid_quality_raises():
    line = _GOOD_LINE.replace("   1   9", "   0   9", 1)
    with pytest.raises(PPKSolveError):
        parse_pos_line(line)


def test_malformed_line_raises():
    with pytest.raises(PPKSolveError):
        parse_pos_line("not a pos line")


def test_parse_pos_file_returns_all_solution_epochs(tmp_path):
    pos = tmp_path / "solution.pos"
    second = _GOOD_LINE.replace("10:30:15.000", "10:30:30.000").replace("   1   9", "   2   10", 1)
    pos.write_text("% header\n" + _GOOD_LINE + "\n" + second + "\n")
    rows = parse_pos_file(pos)
    assert len(rows) == 2
    assert [r.rtklib_quality for r in rows] == [1, 2]
    assert rows[1].satellites == 10


def test_missing_rtklib_binary_raises_ppksolveerror_not_filenotfounderror():
    engine = RTKLibPPKEngine(
        base_reference_lat=-6.2,
        base_reference_lon=106.8,
        base_reference_alt_m=500.0,
        convbin_path="/definitely/does/not/exist/convbin",
        rnx2rtkp_path="/definitely/does/not/exist/rnx2rtkp",
        nav_file="/definitely/does/not/exist/nav.rnx",
    )
    with pytest.raises(PPKSolveError):
        engine.solve_window(
            b"\xb5\x62\x02\x15\x00\x00\x00\x00",
            b"\xb5\x62\x02\x15\x00\x00\x00\x00",
            observed_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )


def test_compressed_cached_navigation_is_materialized_plain_for_rtklib(tmp_path):
    rinex = (
        b"     3.05           N: GNSS NAV DATA    M                   RINEX VERSION / TYPE\n"
        b"                                                            END OF HEADER\n"
        b"G01 2026 09 26 00 00 00  0.0 0.0 0.0\n"
    )
    cached = tmp_path / "nav.rnx.gz"
    cached.write_bytes(gzip.compress(rinex))
    artifact = SimpleNamespace(
        path=cached,
        sha256="a" * 64,
        source_url="https://example.test/nav.rnx.gz",
    )
    acquired = SimpleNamespace(
        resolved=SimpleNamespace(artifact=artifact),
        provider="BKG_WRD",
        cache_hit=False,
    )
    acquisition = SimpleNamespace(ensure=lambda observed_at, station=None: acquired)
    engine = RTKLibPPKEngine(-6, 107, 100, navigation_acquisition=acquisition)
    nav_path, meta = engine._prepare_navigation(
        datetime(2026, 9, 26, tzinfo=timezone.utc), tmp_path / "out", station=None
    )
    assert nav_path.read_bytes() == rinex
    assert meta["provider"] == "BKG_WRD"
    assert meta["cache_hit"] is False
    assert len(meta["normalized_sha256"]) == 64


def test_convbin_command_sets_all_auxiliary_output_paths(tmp_path):
    ubx = tmp_path / "rover.ubx"
    args, obs = build_convbin_command("convbin", ubx, tmp_path, "rover")
    assert obs == tmp_path / "rover.obs"
    expected = {
        "-o": tmp_path / "rover.obs",
        "-n": tmp_path / "rover.nav",
        "-g": tmp_path / "rover.gnav",
        "-h": tmp_path / "rover.hnav",
        "-q": tmp_path / "rover.qnav",
        "-l": tmp_path / "rover.lnav",
        "-s": tmp_path / "rover.sbs",
    }
    for flag, path in expected.items():
        assert args[args.index(flag) + 1] == str(path)
    assert args[-1] == str(ubx)
    assert "/" not in [args[args.index(flag) + 1] for flag in expected]


def test_ppk_solution_contract_v1_is_explicit_and_ellipsoidal():
    r = parse_pos_line(_GOOD_LINE)
    contract = r.to_contract()
    assert contract["schema_version"] == PPK_OUTPUT_SCHEMA_VERSION == "ppk.solution.v1"
    assert set(contract) == {
        "schema_version", "timestamp_utc", "latitude", "longitude", "ellipsoidal_height_m",
        "vertical_datum",
        "rtklib_quality", "rtklib_ns", "rtklib_sdn_m", "rtklib_sde_m", "rtklib_sdu_m",
        "h_acc_m", "rtklib_age_s", "rtklib_ratio",
    }
    assert "altitude_m" not in contract
    assert "gnss_fix_type" not in contract



def test_engine_window_result_contains_reproducibility_hashes(monkeypatch, tmp_path):
    nav = tmp_path / "nav.rnx"
    nav.write_text(
        "     3.05           N: GNSS NAV DATA    M                   RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
    )
    config = tmp_path / "rtklib.conf"
    config.write_text("pos1-posmode =kinematic\nout-height =ellipsoidal\n")
    engine = RTKLibPPKEngine(
        -6.0,
        107.0,
        100.0,
        convbin_path="/bin/echo",
        rnx2rtkp_path="/bin/echo",
        nav_file=str(nav),
        rtklib_config_file=str(config),
    )

    def fake_run(args, timeout, step):
        if step.startswith("convbin"):
            Path(args[args.index("-o") + 1]).write_text("RINEX OBS\n")
        else:
            Path(args[args.index("-o") + 1]).write_text(_GOOD_LINE + "\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(engine, "_run_subprocess", fake_run)
    result = engine.solve_window(
        b"base-rawx",
        b"rover-rawx",
        observed_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    for value in (
        result.base_rawx_sha256,
        result.rover_rawx_sha256,
        result.base_obs_sha256,
        result.rover_obs_sha256,
        result.navigation_sha256,
        result.normalized_navigation_sha256,
        result.rtklib_config_sha256,
        result.convbin_sha256,
        result.rnx2rtkp_sha256,
        result.solution_pos_sha256,
    ):
        assert value is not None and len(value) == 64
