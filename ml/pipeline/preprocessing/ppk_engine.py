from __future__ import annotations
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from services.rinex_service.normalizer import RINEXNormalizationError, normalize_rinex_transport


PPK_OUTPUT_SCHEMA_VERSION = "ppk.solution.v1"
PPK_ACCEPTANCE_SCHEMA_VERSION = "ppk.engine.acceptance.v1"
PPK_ENGINE_NAME = "RTKLIB"


class PPKSolveError(RuntimeError):
    pass


# Explicitly bind every RTKLIB auxiliary output so convbin never resolves a default path to filesystem root.
def build_convbin_command(
    convbin_path: str,
    ubx_path: Path,
    out_dir: Path,
    label: str,
) -> tuple[list[str], Path]:
    obs_path = out_dir / f"{label}.obs"
    outputs = {
        "-n": out_dir / f"{label}.nav",
        "-g": out_dir / f"{label}.gnav",
        "-h": out_dir / f"{label}.hnav",
        "-q": out_dir / f"{label}.qnav",
        "-l": out_dir / f"{label}.lnav",
        "-s": out_dir / f"{label}.sbs",
    }
    args = [convbin_path, "-r", "ubx", "-o", str(obs_path)]
    for flag, path in outputs.items():
        args.extend([flag, str(path)])
    args.append(str(ubx_path))
    return args, obs_path


@dataclass(frozen=True)
class PPKSolutionEpoch:
    timestamp_utc: datetime
    latitude: float
    longitude: float
    ellipsoidal_height_m: float
    rtklib_quality: int
    satellites: int
    sdn_m: float
    sde_m: float
    sdu_m: float
    age_s: float | None
    ratio: float | None

    def to_contract(self) -> dict:
        return {
            "schema_version": PPK_OUTPUT_SCHEMA_VERSION,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "ellipsoidal_height_m": self.ellipsoidal_height_m,
            "vertical_datum": "ELLIPSOIDAL_WGS84",
            "rtklib_quality": self.rtklib_quality,
            "rtklib_ns": self.satellites,
            "rtklib_sdn_m": self.sdn_m,
            "rtklib_sde_m": self.sde_m,
            "rtklib_sdu_m": self.sdu_m,
            "h_acc_m": self.h_acc_m,
            "rtklib_age_s": self.age_s,
            "rtklib_ratio": self.ratio,
        }

    @property
    def h_acc_m(self) -> float:
        return (self.sdn_m**2 + self.sde_m**2) ** 0.5


@dataclass(frozen=True)
class PPKWindowResult:
    solutions: tuple[PPKSolutionEpoch, ...]
    navigation_sha256: str
    navigation_source_url: str | None
    navigation_provider: str | None
    navigation_cache_hit: bool
    rtklib_config_sha256: str | None
    base_rawx_sha256: str | None = None
    rover_rawx_sha256: str | None = None
    base_obs_sha256: str | None = None
    rover_obs_sha256: str | None = None
    normalized_navigation_sha256: str | None = None
    convbin_sha256: str | None = None
    rnx2rtkp_sha256: str | None = None
    solution_pos_sha256: str | None = None
    engine_name: str = PPK_ENGINE_NAME


class PPKEngine(ABC):
    @abstractmethod
    def solve_window(
        self,
        base_rawx: bytes,
        rover_rawx: bytes,
        *,
        observed_at: datetime,
        station: str | None = None,
    ) -> PPKWindowResult: ...


class RTKLibPPKEngine(PPKEngine):
    def __init__(
        self,
        base_reference_lat: float,
        base_reference_lon: float,
        base_reference_alt_m: float,
        convbin_path: str = "convbin",
        rnx2rtkp_path: str = "rnx2rtkp",
        nav_file: str | None = None,
        navigation_acquisition=None,
        rtklib_config_file: str | None = None,
    ) -> None:
        self._ref_lat = base_reference_lat
        self._ref_lon = base_reference_lon
        self._ref_alt = base_reference_alt_m
        self._convbin = convbin_path
        self._rnx2rtkp = rnx2rtkp_path
        self._nav_file = nav_file
        self._navigation_acquisition = navigation_acquisition
        self._rtklib_config_file = rtklib_config_file

    def solve_window(
        self,
        base_rawx: bytes,
        rover_rawx: bytes,
        *,
        observed_at: datetime,
        station: str | None = None,
    ) -> PPKWindowResult:
        if observed_at.tzinfo is None:
            raise PPKSolveError("observed_at must be timezone-aware UTC-compatible datetime")
        if not base_rawx or not rover_rawx:
            raise PPKSolveError("base and rover RAWX streams must both be nonempty")
        if base_rawx == rover_rawx:
            raise PPKSolveError("base and rover RAWX streams must be distinct physical observations")
        base_rawx_sha256 = hashlib.sha256(base_rawx).hexdigest()
        rover_rawx_sha256 = hashlib.sha256(rover_rawx).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_ubx = tmp_path / "base.ubx"
            rover_ubx = tmp_path / "rover.ubx"
            base_ubx.write_bytes(base_rawx)
            rover_ubx.write_bytes(rover_rawx)
            base_obs = self._convert_to_rinex(base_ubx, tmp_path, "base")
            rover_obs = self._convert_to_rinex(rover_ubx, tmp_path, "rover")
            base_obs_sha256 = hashlib.sha256(base_obs.read_bytes()).hexdigest()
            rover_obs_sha256 = hashlib.sha256(rover_obs.read_bytes()).hexdigest()
            nav_path, nav_meta = self._prepare_navigation(observed_at, tmp_path, station=station)
            pos_file = tmp_path / "solution.pos"
            self._run_rnx2rtkp(rover_obs, base_obs, nav_path, pos_file)
            solutions = parse_pos_file(pos_file)
            solution_pos_sha256 = hashlib.sha256(pos_file.read_bytes()).hexdigest()
            config_sha = None
            if self._rtklib_config_file:
                config_path = Path(self._rtklib_config_file)
                if config_path.is_file():
                    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
            return PPKWindowResult(
                solutions=tuple(solutions),
                navigation_sha256=nav_meta["sha256"],
                navigation_source_url=nav_meta.get("source_url"),
                navigation_provider=nav_meta.get("provider"),
                navigation_cache_hit=bool(nav_meta.get("cache_hit")),
                rtklib_config_sha256=config_sha,
                base_rawx_sha256=base_rawx_sha256,
                rover_rawx_sha256=rover_rawx_sha256,
                base_obs_sha256=base_obs_sha256,
                rover_obs_sha256=rover_obs_sha256,
                normalized_navigation_sha256=nav_meta.get("normalized_sha256"),
                convbin_sha256=_executable_sha256(self._convbin),
                rnx2rtkp_sha256=_executable_sha256(self._rnx2rtkp),
                solution_pos_sha256=solution_pos_sha256,
            )

    def solve(self, base_rawx: bytes, rover_rawx: bytes) -> PPKSolutionEpoch:
        raise PPKSolveError("single-epoch solve() is deprecated; use solve_window() with an observation timestamp")

    def _convert_to_rinex(self, ubx_path: Path, out_dir: Path, label: str) -> Path:
        args, obs_path = build_convbin_command(self._convbin, ubx_path, out_dir, label)
        result = self._run_subprocess(
            args,
            timeout=30,
            step=f"convbin ({label})",
        )
        if result.returncode != 0 or not obs_path.exists() or obs_path.stat().st_size == 0:
            raise PPKSolveError(f"convbin failed for {label}: {result.stderr.strip()}")
        return obs_path

    def _prepare_navigation(
        self,
        observed_at: datetime,
        out_dir: Path,
        *,
        station: str | None,
    ) -> tuple[Path, dict]:
        provider = None
        cache_hit = False
        source_url = None
        source_path: Path | None = None
        sha256_value: str | None = None
        if self._navigation_acquisition is not None:
            try:
                acquired = self._navigation_acquisition.ensure(observed_at, station=station)
            except Exception as exc:
                raise PPKSolveError(f"navigation acquisition failed: {exc}") from exc
            artifact = acquired.resolved.artifact
            source_path = artifact.path
            sha256_value = artifact.sha256
            source_url = artifact.source_url
            provider = acquired.provider
            cache_hit = acquired.cache_hit
        elif self._nav_file and Path(self._nav_file).is_file():
            source_path = Path(self._nav_file)
            raw = source_path.read_bytes()
            sha256_value = hashlib.sha256(raw).hexdigest()
        else:
            raise PPKSolveError(
                "PPK requires RINEX navigation: configure automatic acquisition or an existing nav_file"
            )
        try:
            raw = source_path.read_bytes()
            normalized = normalize_rinex_transport(raw)
        except (OSError, RINEXNormalizationError) as exc:
            raise PPKSolveError(f"unable to materialize navigation RINEX: {exc}") from exc
        out_dir.mkdir(parents=True, exist_ok=True)
        nav_path = out_dir / "navigation.rnx"
        nav_path.write_bytes(normalized.content)
        if not nav_path.stat().st_size:
            raise PPKSolveError("navigation RINEX materialized to an empty file")
        return nav_path, {
            "sha256": sha256_value or hashlib.sha256(raw).hexdigest(),
            "source_url": source_url,
            "provider": provider,
            "cache_hit": cache_hit,
            "normalized_sha256": hashlib.sha256(normalized.content).hexdigest(),
        }

    def _run_rnx2rtkp(self, rover_obs: Path, base_obs: Path, nav_file: Path, pos_out: Path) -> None:
        args = [self._rnx2rtkp]
        if self._rtklib_config_file:
            config_path = Path(self._rtklib_config_file)
            if not config_path.is_file():
                raise PPKSolveError(f"RTKLIB config file not found: {config_path}")
            args.extend(["-k", str(config_path)])
        else:
            args.extend(["-p", "2"])
        args.extend([
            "-l", str(self._ref_lat), str(self._ref_lon), str(self._ref_alt),
            "-o", str(pos_out), str(rover_obs), str(base_obs), str(nav_file),
        ])
        result = self._run_subprocess(args, timeout=120, step="rnx2rtkp")
        if result.returncode != 0 or not pos_out.exists() or pos_out.stat().st_size == 0:
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


def _executable_sha256(command: str) -> str | None:
    """Return a reproducible hash for a resolved executable when available."""
    resolved = Path(command)
    if not resolved.is_file():
        found = shutil.which(command)
        if not found:
            return None
        resolved = Path(found)
    try:
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return None


def parse_pos_file(path: Path) -> list[PPKSolutionEpoch]:
    solutions: list[PPKSolutionEpoch] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        try:
            solutions.append(parse_pos_line(stripped))
        except PPKSolveError as exc:
            raise PPKSolveError(f"invalid RTKLIB solution line {line_number}: {exc}") from exc
    if not solutions:
        raise PPKSolveError("rnx2rtkp produced no solution epochs")
    timestamps = [solution.timestamp_utc for solution in solutions]
    if len(set(timestamps)) != len(timestamps):
        raise PPKSolveError("rnx2rtkp produced duplicate solution timestamps")
    if timestamps != sorted(timestamps):
        raise PPKSolveError("rnx2rtkp solution timestamps are not monotonic")
    return solutions


def parse_pos_line(line: str) -> PPKSolutionEpoch:
    fields = line.split()
    if len(fields) < 10:
        raise PPKSolveError(f"unrecognized .pos line (expected >=10 fields): {line!r}")
    try:
        timestamp = datetime.strptime(
            f"{fields[0]} {fields[1]}", "%Y/%m/%d %H:%M:%S.%f"
        ).replace(tzinfo=timezone.utc)
        lat = float(fields[2])
        lon = float(fields[3])
        height = float(fields[4])
        q = int(fields[5])
        ns = int(fields[6])
        sdn = float(fields[7])
        sde = float(fields[8])
        sdu = float(fields[9])
        age = float(fields[13]) if len(fields) > 13 else None
        ratio = float(fields[14]) if len(fields) > 14 else None
    except (ValueError, IndexError) as exc:
        raise PPKSolveError(f"could not parse .pos line {line!r}: {exc}") from exc
    numeric_values = [lat, lon, height, sdn, sde, sdu]
    if age is not None:
        numeric_values.append(age)
    if ratio is not None:
        numeric_values.append(ratio)
    if not all(math.isfinite(value) for value in numeric_values):
        raise PPKSolveError(f"non-finite numeric value in RTKLIB solution (line: {line!r})")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise PPKSolveError(f"invalid RTKLIB latitude/longitude (line: {line!r})")
    if q < 1 or q > 6:
        raise PPKSolveError(f"invalid RTKLIB solution quality Q={q} (line: {line!r})")
    if ns <= 0:
        raise PPKSolveError(f"invalid RTKLIB satellite count ns={ns} (line: {line!r})")
    if min(sdn, sde, sdu) < 0:
        raise PPKSolveError(f"negative RTKLIB standard deviation (line: {line!r})")
    # RTKLIB's solution age is the signed rover/base observation-time
    # difference ("age of differential"), not an elapsed-duration field.
    # A negative value is valid when the selected base observation is later
    # than the rover epoch. Preserve the sign for provenance/diagnostics;
    # RTKLIB's processing max-age gate is responsible for admissibility.
    if ratio is not None and ratio < 0:
        raise PPKSolveError(f"negative RTKLIB ambiguity ratio (line: {line!r})")
    return PPKSolutionEpoch(
        timestamp_utc=timestamp,
        latitude=lat,
        longitude=lon,
        ellipsoidal_height_m=height,
        rtklib_quality=q,
        satellites=ns,
        sdn_m=sdn,
        sde_m=sde,
        sdu_m=sdu,
        age_s=age,
        ratio=ratio,
    )
