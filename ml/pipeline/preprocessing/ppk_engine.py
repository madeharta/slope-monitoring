from __future__ import annotations
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
class PPKSolveError(RuntimeError):
    pass
@dataclass(frozen=True)
class PPKResult:
    latitude: float
    longitude: float
    altitude_m: float
    gnss_fix_type: int
    h_acc_m: float
class PPKEngine(ABC):
    @abstractmethod
    def solve(self, base_rawx: bytes, rover_rawx: bytes) -> PPKResult: ...
_RTKLIB_Q_TO_FIX_TYPE = {1: 4, 2: 5, 5: 3}
class RTKLibPPKEngine(PPKEngine):
    def __init__(self, base_reference_lat: float, base_reference_lon: float, base_reference_alt_m: float,
                 convbin_path: str = "convbin", rnx2rtkp_path: str = "rnx2rtkp",
                 nav_file: str | None = None) -> None:
        self._ref_lat = base_reference_lat
        self._ref_lon = base_reference_lon
        self._ref_alt = base_reference_alt_m
        self._convbin = convbin_path
        self._rnx2rtkp = rnx2rtkp_path
        self._nav_file = nav_file
    def solve(self, base_rawx: bytes, rover_rawx: bytes) -> PPKResult:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_ubx = tmp_path / "base.ubx"
            rover_ubx = tmp_path / "rover.ubx"
            base_ubx.write_bytes(base_rawx)
            rover_ubx.write_bytes(rover_rawx)
            base_obs = self._convert_to_rinex(base_ubx, tmp_path, "base")
            rover_obs = self._convert_to_rinex(rover_ubx, tmp_path, "rover")
            pos_file = tmp_path / "solution.pos"
            self._run_rnx2rtkp(rover_obs, base_obs, pos_file)
            last_line = self._last_solution_line(pos_file)
            return parse_pos_line(last_line)
    def _convert_to_rinex(self, ubx_path: Path, out_dir: Path, label: str) -> Path:
        obs_path = out_dir / f"{label}.obs"
        result = self._run_subprocess(
            [self._convbin, "-r", "ubx", "-o", str(obs_path), str(ubx_path)], timeout=30, step=f"convbin ({label})",
        )
        if result.returncode != 0 or not obs_path.exists():
            raise PPKSolveError(f"convbin failed for {label}: {result.stderr.strip()}")
        return obs_path
    def _run_rnx2rtkp(self, rover_obs: Path, base_obs: Path, pos_out: Path) -> None:
        if not self._nav_file or not Path(self._nav_file).is_file():
            raise PPKSolveError("PPK requires an existing RINEX navigation/ephemeris file; RAWX alone is insufficient")
        result = self._run_subprocess(
            [
                self._rnx2rtkp, "-p", "2",
                "-l", str(self._ref_lat), str(self._ref_lon), str(self._ref_alt),
                "-o", str(pos_out), str(rover_obs), str(base_obs), self._nav_file,
            ],
            timeout=60, step="rnx2rtkp",
        )
        if result.returncode != 0 or not pos_out.exists():
            raise PPKSolveError(f"rnx2rtkp failed: {result.stderr.strip()}")
    @staticmethod
    def _run_subprocess(args: list[str], timeout: int, step: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise PPKSolveError(
                f"{step}: binary not found ({args[0]}) — is RTKLIB installed and on $PATH "
                f"or RTKLIB_CONVBIN_PATH/RTKLIB_RNX2RTKP_PATH set correctly?"
            ) from exc
        except PermissionError as exc:
            raise PPKSolveError(f"{step}: binary not executable ({args[0]}): {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PPKSolveError(f"{step}: timed out after {timeout}s") from exc
    def _last_solution_line(self, pos_file: Path) -> str:
        lines = [ln for ln in pos_file.read_text().splitlines() if ln and not ln.startswith("%")]
        if not lines:
            raise PPKSolveError("rnx2rtkp produced no solution epochs")
        return lines[-1]
def parse_pos_line(line: str) -> PPKResult:
    fields = line.split()
    if len(fields) < 6:
        raise PPKSolveError(f"unrecognized .pos line (expected >=6 fields): {line!r}")
    try:
        lat = float(fields[2])
        lon = float(fields[3])
        height = float(fields[4])
        q = int(fields[5])
        sdn = float(fields[7]) if len(fields) > 7 else 0.0
        sde = float(fields[8]) if len(fields) > 8 else 0.0
    except (ValueError, IndexError) as exc:
        raise PPKSolveError(f"could not parse .pos line {line!r}: {exc}") from exc
    if q not in _RTKLIB_Q_TO_FIX_TYPE:
        raise PPKSolveError(f"unusable RTKLIB solution quality Q={q} (line: {line!r})")
    h_acc_m = (sdn**2 + sde**2) ** 0.5
    return PPKResult(
        latitude=lat, longitude=lon, altitude_m=height,
        gnss_fix_type=_RTKLIB_Q_TO_FIX_TYPE[q], h_acc_m=h_acc_m,
    )
