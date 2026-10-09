from __future__ import annotations

import base64
import csv
import struct
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.pipeline.preprocessing.ppk_engine import (
    PPK_ACCEPTANCE_SCHEMA_VERSION,
    PPK_OUTPUT_SCHEMA_VERSION,
    PPKSolveError,
    RTKLibPPKEngine,
    parse_pos_file,
    parse_pos_line,
)
from scripts.convert_rawx_ppk import execute

GOOD_LINE = (
    "2026/09/15 10:30:15.000 -6.123456789 106.987654321 510.1234 1 9 "
    "0.0021 0.0018 0.0035 0.0002 -0.0004 -0.0001 1.0 32.4"
)


def _rawx_b64(*, week: int, tow: float, num_meas: int = 1) -> str:
    payload = struct.pack("<dHbBBBH", tow, week, 18, num_meas, 1, 1, 0)
    payload += b"\x00" * (32 * num_meas)
    body = bytes((0x02, 0x15)) + len(payload).to_bytes(2, "little") + payload
    ck_a = 0
    ck_b = 0
    for value in body:
        ck_a = (ck_a + value) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return base64.b64encode(b"\xb5\x62" + body + bytes((ck_a, ck_b))).decode()


def _write_rawx_csv(path: Path, device_id: str, tow: float) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["device_id", "timestamp_utc", "gnss_raw_payload_base64"])
        writer.writerow([device_id, "2026-09-18 12:00:00", _rawx_b64(week=2436, tow=tow)])


def test_engine_rejects_empty_and_self_paired_rawx_before_rtklib_execution():
    engine = RTKLibPPKEngine(-6.0, 107.0, 100.0)
    observed = datetime(2026, 9, 18, tzinfo=timezone.utc)
    with pytest.raises(PPKSolveError, match="nonempty"):
        engine.solve_window(b"", b"rover", observed_at=observed)
    with pytest.raises(PPKSolveError, match="distinct physical observations"):
        engine.solve_window(b"same", b"same", observed_at=observed)


@pytest.mark.parametrize(
    "line,match",
    [
        (GOOD_LINE.replace("-6.123456789", "nan"), "non-finite"),
        (GOOD_LINE.replace("-6.123456789", "95.0"), "latitude/longitude"),
        (GOOD_LINE.replace(" 1 9 ", " 1 0 "), "satellite count"),
        (GOOD_LINE.replace("0.0021 0.0018 0.0035", "-0.0021 0.0018 0.0035"), "standard deviation"),
    ],
)
def test_pos_parser_fails_closed_on_invalid_numeric_semantics(line, match):
    with pytest.raises(PPKSolveError, match=match):
        parse_pos_line(line)


def test_pos_file_rejects_duplicate_and_nonmonotonic_epochs(tmp_path):
    duplicate = tmp_path / "duplicate.pos"
    duplicate.write_text(GOOD_LINE + "\n" + GOOD_LINE + "\n")
    with pytest.raises(PPKSolveError, match="duplicate solution timestamps"):
        parse_pos_file(duplicate)

    older = GOOD_LINE.replace("10:30:15.000", "10:30:14.000")
    nonmonotonic = tmp_path / "nonmonotonic.pos"
    nonmonotonic.write_text(GOOD_LINE + "\n" + older + "\n")
    with pytest.raises(PPKSolveError, match="not monotonic"):
        parse_pos_file(nonmonotonic)


def test_full_acceptance_manifest_locks_chain_provenance_and_config(monkeypatch, tmp_path):
    rover = tmp_path / "rover.csv"
    base = tmp_path / "base.csv"
    nav = tmp_path / "nav.rnx"
    config = tmp_path / "rtklib.conf"
    output = tmp_path / "out"
    _write_rawx_csv(rover, "ROVER-B1-01", 1000.0)
    _write_rawx_csv(base, "BASE-01", 1000.0)
    nav.write_text(
        "     3.05           N: GNSS NAV DATA    M                   RINEX VERSION / TYPE\n"
        "                                                            END OF HEADER\n"
    )
    config.write_text("pos1-posmode =kinematic\nout-height =ellipsoidal\n")

    commands = []

    def fake_binary(value):
        return "/bin/echo"

    def fake_run(args, text, capture_output, timeout, check):
        commands.append(args)
        if "-o" in args:
            out = Path(args[args.index("-o") + 1])
            if out.suffix == ".pos":
                out.write_text(GOOD_LINE + "\n")
            else:
                out.write_text("RINEX OBS\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("scripts.convert_rawx_ppk._binary", fake_binary)
    monkeypatch.setattr("scripts.convert_rawx_ppk.subprocess.run", fake_run)

    manifest = execute(
        rover,
        output,
        base_input=base,
        base_coords=(-6.0, 107.0, 100.0),
        nav=nav,
        convbin="convbin",
        rnx2rtkp="rnx2rtkp",
        rtklib_config=config,
    )

    assert manifest["acceptance_schema_version"] == PPK_ACCEPTANCE_SCHEMA_VERSION
    assert manifest["output_schema_version"] == PPK_OUTPUT_SCHEMA_VERSION
    assert manifest["engine_acceptance"]["status"] == "PASS"
    assert manifest["engine_acceptance"]["production_geodetic_validation"] is False
    assert all(manifest["engine_acceptance"]["gates"].values())
    assert manifest["time_integrity"]["pairing"]["status"] == "OVERLAP"
    assert manifest["time_integrity"]["pairing_time_basis"] == "rxm_rawx_gps_seconds"
    assert manifest["rtklib_config_mode"] == "explicit_file"
    assert len(manifest["rtklib_config_sha256"]) == 64
    assert len(manifest["rover_ubx_sha256"]) == 64
    assert len(manifest["base_ubx_sha256"]) == 64
    assert len(manifest["rover_obs_sha256"]) == 64
    assert len(manifest["base_obs_sha256"]) == 64
    assert len(manifest["navigation_normalized_sha256"]) == 64
    assert manifest["ppk"]["solution_epochs"] == 1
    solver = next(command for command in commands if any(str(part).endswith("solution.pos") for part in command))
    assert "-k" in solver
    assert solver[solver.index("-k") + 1] == str(config)
    assert "-p" not in solver


def test_single_stream_fixture_is_explicitly_partial_not_ppk_pass(monkeypatch, tmp_path):
    rover = tmp_path / "rover.csv"
    _write_rawx_csv(rover, "ROVER-B1-01", 1000.0)

    def fake_binary(value):
        return "/bin/echo"

    def fake_run(args, text, capture_output, timeout, check):
        out = Path(args[args.index("-o") + 1])
        out.write_text("RINEX OBS\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("scripts.convert_rawx_ppk._binary", fake_binary)
    monkeypatch.setattr("scripts.convert_rawx_ppk.subprocess.run", fake_run)
    manifest = execute(rover, tmp_path / "out", convbin="convbin")
    assert manifest["mode"] == "RAWX_ONLY"
    assert manifest["engine_acceptance"]["status"] == "PARTIAL_CONVBIN_ONLY"
    assert manifest["ppk_validated"] is False


def test_pos_parser_preserves_signed_differential_age():
    line = GOOD_LINE.replace(" 1.0 32.4", " -35.99 0.0")
    parsed = parse_pos_line(line)
    assert parsed.age_s == -35.99
    assert parsed.ratio == 0.0
