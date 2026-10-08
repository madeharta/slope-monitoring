from __future__ import annotations
import gzip
import io
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


class RINEXNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedRINEXContent:
    content: bytes
    transport_compression: str


_GZIP_MAGIC = b"\x1f\x8b"
_UNIX_COMPRESS_MAGIC = b"\x1f\x9d"


def normalize_rinex_transport(
    content: bytes,
    *,
    max_decompressed_bytes: int | None = None,
    max_expansion_ratio: float | None = None,
    timeout_s: float | None = None,
    max_layers: int = 2,
) -> NormalizedRINEXContent:
    if not content:
        raise RINEXNormalizationError("empty RINEX content")
    max_bytes = max_decompressed_bytes or _positive_int_env(
        "RINEX_DECOMPRESS_MAX_BYTES", 512 * 1024 * 1024
    )
    ratio = max_expansion_ratio or _positive_float_env("RINEX_DECOMPRESS_MAX_RATIO", 100.0)
    timeout = timeout_s or _positive_float_env("RINEX_DECOMPRESS_TIMEOUT_S", 30.0)
    if max_layers < 1:
        raise RINEXNormalizationError("max_layers must be positive")
    current = content
    encodings: list[str] = []
    for _ in range(max_layers):
        if current.startswith(_GZIP_MAGIC):
            current = _decompress_gzip(current, max_bytes=max_bytes, ratio=ratio)
            encodings.append("gzip")
            continue
        if current.startswith(_UNIX_COMPRESS_MAGIC):
            current = _decompress_unix_compress(
                current,
                max_bytes=max_bytes,
                ratio=ratio,
                timeout_s=timeout,
            )
            encodings.append("compress-z")
            continue
        break
    if current.startswith((_GZIP_MAGIC, _UNIX_COMPRESS_MAGIC)):
        raise RINEXNormalizationError("compressed RINEX nesting exceeds configured layer limit")
    return NormalizedRINEXContent(
        content=current,
        transport_compression="+".join(encodings) if encodings else "none",
    )


def _decompress_gzip(content: bytes, *, max_bytes: int, ratio: float) -> bytes:
    limit = _effective_output_limit(len(content), max_bytes=max_bytes, ratio=ratio)
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as stream:
            while True:
                chunk = stream.read(min(1024 * 1024, limit - len(output) + 1))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    raise RINEXNormalizationError(
                        f"gzip output exceeds safe decompression limit of {limit} bytes"
                    )
    except RINEXNormalizationError:
        raise
    except (OSError, EOFError) as exc:
        raise RINEXNormalizationError(f"invalid gzip-compressed RINEX artifact: {exc}") from exc
    if not output:
        raise RINEXNormalizationError("compressed RINEX artifact decompressed to empty content")
    return bytes(output)


def _decompress_unix_compress(
    content: bytes,
    *,
    max_bytes: int,
    ratio: float,
    timeout_s: float,
) -> bytes:
    executable = shutil.which("gzip") or shutil.which("uncompress")
    if executable is None:
        raise RINEXNormalizationError(
            "Unix compress (.Z) input requires gzip or uncompress on PATH"
        )
    limit = _effective_output_limit(len(content), max_bytes=max_bytes, ratio=ratio)
    with tempfile.NamedTemporaryFile(prefix="rinex-", suffix=".Z", delete=False) as handle:
        handle.write(content)
        handle.flush()
        temp_path = Path(handle.name)
    command = [executable, "-cd", str(temp_path)] if Path(executable).name == "gzip" else [executable, "-c", str(temp_path)]
    try:
        return _run_bounded_decompress(command, limit=limit, timeout_s=timeout_s)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _run_bounded_decompress(command: list[str], *, limit: int, timeout_s: float) -> bytes:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RINEXNormalizationError("failed to initialize decompressor pipes")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = bytearray()
    errors = bytearray()
    deadline = time.monotonic() + timeout_s
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                raise RINEXNormalizationError("Unix compress (.Z) decompression timed out")
            events = selector.select(timeout=min(0.25, remaining))
            if not events and process.poll() is not None:
                break
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    output.extend(chunk)
                    if len(output) > limit:
                        process.kill()
                        raise RINEXNormalizationError(
                            f"Unix compress (.Z) output exceeds safe decompression limit of {limit} bytes"
                        )
                elif len(errors) < 8192:
                    errors.extend(chunk[: 8192 - len(errors)])
        try:
            return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise RINEXNormalizationError("Unix compress (.Z) decompression timed out") from exc
        if return_code != 0:
            detail = errors.decode("utf-8", errors="replace").strip()
            raise RINEXNormalizationError(
                f"invalid Unix compress (.Z) RINEX artifact{': ' + detail if detail else ''}"
            )
        if not output:
            raise RINEXNormalizationError("compressed RINEX artifact decompressed to empty content")
        return bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        process.stderr.close()


def _effective_output_limit(compressed_size: int, *, max_bytes: int, ratio: float) -> int:
    if max_bytes <= 0 or ratio <= 0:
        raise RINEXNormalizationError("decompression limits must be positive")
    ratio_limit = max(1024 * 1024, int(max(1, compressed_size) * ratio))
    return min(max_bytes, ratio_limit)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RINEXNormalizationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RINEXNormalizationError(f"{name} must be positive")
    return value


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RINEXNormalizationError(f"{name} must be numeric") from exc
    if value <= 0:
        raise RINEXNormalizationError(f"{name} must be positive")
    return value
