from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
class RINEXCacheError(RuntimeError):
    pass
@dataclass(frozen=True)
class CachedRINEXArtifact:
    sha256: str
    size_bytes: int
    path: Path
    manifest_path: Path
    original_name: str
    source_url: str | None
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
def _safe_filename(value: str | None) -> str:
    name = Path(value or "rinex.bin").name.strip() or "rinex.bin"
    cleaned = _SAFE_FILENAME.sub("_", name).strip("._")
    return cleaned or "rinex.bin"
class RINEXCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
    def store_bytes(
        self,
        content: bytes,
        *,
        original_name: str | None = None,
        source_url: str | None = None,
        expected_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CachedRINEXArtifact:
        if not content:
            raise RINEXCacheError("refusing to cache an empty RINEX artifact")
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None and digest.lower() != expected_sha256.strip().lower():
            raise RINEXCacheError(
                f"sha256 mismatch: expected {expected_sha256.strip().lower()}, got {digest}"
            )
        file_name = _safe_filename(original_name)
        artifact_dir = self.root / digest[:2] / digest
        artifact_path = artifact_dir / file_name
        manifest_path = artifact_dir / "manifest.json"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        existing = self._find_existing_artifact(artifact_dir, manifest_path)
        if existing is not None:
            if hashlib.sha256(existing.read_bytes()).hexdigest() != digest:
                raise RINEXCacheError(f"cache corruption detected for sha256 {digest}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return CachedRINEXArtifact(
                sha256=digest,
                size_bytes=int(manifest["size_bytes"]),
                path=existing,
                manifest_path=manifest_path,
                original_name=str(manifest["original_name"]),
                source_url=manifest.get("source_url"),
            )
        self._atomic_write(artifact_path, content)
        metadata_value = dict(metadata or {})
        try:
            from services.rinex_service.normalizer import RINEXNormalizationError
            from services.rinex_service.parser import RINEXParseError, parse_rinex_bytes
            metadata_value["rinex"] = parse_rinex_bytes(content, original_name=file_name).to_manifest_dict()
        except RINEXNormalizationError as exc:
            try:
                artifact_path.unlink()
            except FileNotFoundError:
                pass
            raise RINEXCacheError(f"unsafe compressed RINEX artifact: {exc}") from exc
        except RINEXParseError:
            pass
        manifest = {
            "sha256": digest,
            "size_bytes": len(content),
            "original_name": file_name,
            "source_url": source_url,
            "stored_at_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata_value,
        }
        self._atomic_write(
            manifest_path,
            (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        return CachedRINEXArtifact(
            sha256=digest,
            size_bytes=len(content),
            path=artifact_path,
            manifest_path=manifest_path,
            original_name=file_name,
            source_url=source_url,
        )
    def resolve(self, sha256: str) -> CachedRINEXArtifact:
        digest = sha256.strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise RINEXCacheError("invalid sha256")
        artifact_dir = self.root / digest[:2] / digest
        manifest_path = artifact_dir / "manifest.json"
        existing = self._find_existing_artifact(artifact_dir, manifest_path)
        if existing is None:
            raise RINEXCacheError(f"RINEX artifact not found for sha256 {digest}")
        content = existing.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise RINEXCacheError(f"cache corruption detected for sha256 {digest}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return CachedRINEXArtifact(
            sha256=digest,
            size_bytes=len(content),
            path=existing,
            manifest_path=manifest_path,
            original_name=str(manifest["original_name"]),
            source_url=manifest.get("source_url"),
        )
    @staticmethod
    def _find_existing_artifact(artifact_dir: Path, manifest_path: Path) -> Path | None:
        if not manifest_path.is_file():
            return None
        candidates = [p for p in artifact_dir.iterdir() if p.is_file() and p.name != "manifest.json"]
        if len(candidates) != 1:
            raise RINEXCacheError(f"invalid cache entry layout in {artifact_dir}")
        return candidates[0]
    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
