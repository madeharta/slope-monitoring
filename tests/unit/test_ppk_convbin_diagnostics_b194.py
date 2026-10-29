from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.pipeline.preprocessing.ppk_engine import RTKLibPPKEngine, PPKSolveError


@pytest.mark.parametrize(
    ("returncode", "output_mode", "expected_reason"),
    [
        (1, "missing", "CONVBIN_EXIT_NONZERO"),
        (0, "missing", "RINEX_OBS_MISSING"),
        (0, "empty", "RINEX_OBS_EMPTY"),
    ],
)
def test_convbin_failure_reason_codes(
    monkeypatch, tmp_path, returncode, output_mode, expected_reason
):
    engine = object.__new__(RTKLibPPKEngine)
    engine._convbin = "convbin"

    obs = tmp_path / "base.obs"

    def fake_build(*args):
        return ["convbin", "base.ubx"], obs

    def fake_run(*args, **kwargs):
        if output_mode == "empty":
            obs.write_bytes(b"")
        return SimpleNamespace(returncode=returncode, stderr="")

    monkeypatch.setattr(
        "ml.pipeline.preprocessing.ppk_engine.build_convbin_command",
        fake_build,
    )
    monkeypatch.setattr(engine, "_run_subprocess", fake_run)

    with pytest.raises(PPKSolveError, match=expected_reason):
        engine._convert_to_rinex(
            Path("base.ubx"), tmp_path, "base"
        )
