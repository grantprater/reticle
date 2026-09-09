"""Immutable analysis revisions with an atomically published current pointer.

An output directory contains canonical ``runs/<revision_id>/`` bundles and a
small ``current.json`` pointer.  Files at the output root are compatibility
views for consumers that have not migrated yet; provenance-aware readers should
resolve the pointer.  A failed write can leave an unreferenced complete run, but
can never make a partial run current or destroy the prior revision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


REVISION_SCHEMA_VERSION = 1


def _bytes(value: str | bytes) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else value


def _replace(source: Path, target: Path) -> None:
    os.replace(source, target)


def _revision_id(artifact: str, producer_version: str,
                 files: dict[str, str | bytes], manifest: dict) -> str:
    digest = hashlib.sha256()
    digest.update(artifact.encode())
    digest.update(b"\0")
    digest.update(producer_version.encode())
    digest.update(b"\0")
    digest.update(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode())
    for name, value in sorted(files.items()):
        if Path(name).name != name or name in {"manifest.json", "current.json"}:
            raise ValueError("revision file names must be plain non-manifest names")
        digest.update(b"\0" + name.encode() + b"\0" + _bytes(value))
    return digest.hexdigest()[:20]


def current_revision(out: str | Path) -> Path | None:
    """Resolve the published immutable run, or None when nothing is current."""
    out = Path(out)
    pointer = out / "current.json"
    if not pointer.is_file():
        return None
    doc = json.loads(pointer.read_text(encoding="utf-8"))
    revision = doc.get("revision_id")
    if not isinstance(revision, str) or not revision:
        raise ValueError(f"invalid revision pointer: {pointer}")
    path = out / "runs" / revision
    if not path.is_dir():
        raise ValueError(f"revision pointer names a missing run: {path}")
    return path


def publish_revision(out: str | Path, *, artifact: str, producer_version: str,
                     files: dict[str, str | bytes], manifest: dict,
                     compatibility: bool = True) -> Path:
    """Write a content-addressed run, then atomically make it current.

    Existing run directories are verified byte-for-byte and never rewritten.
    Compatibility files are individually replaced before the current pointer;
    a failed publication therefore leaves the prior canonical revision current.
    """
    if not artifact or not producer_version or not files:
        raise ValueError("artifact, producer_version and files are required")
    out = Path(out)
    runs = out / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    revision_id = _revision_id(artifact, producer_version, files, manifest)
    final = runs / revision_id
    revision_manifest = {
        **manifest,
        "revision": {
            "schema_version": REVISION_SCHEMA_VERSION,
            "artifact": artifact,
            "producer_version": producer_version,
            "revision_id": revision_id,
            "immutable": True,
        },
    }
    encoded = {name: _bytes(value) for name, value in files.items()}
    encoded["manifest.json"] = json.dumps(
        revision_manifest, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")

    if final.exists():
        for name, value in encoded.items():
            path = final / name
            if not path.is_file() or path.read_bytes() != value:
                raise ValueError(f"immutable revision collision at {final}")
    else:
        temporary = runs / f".tmp-{revision_id}-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            for name, value in encoded.items():
                (temporary / name).write_bytes(value)
            _replace(temporary, final)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    out.mkdir(parents=True, exist_ok=True)
    if compatibility:
        for name, value in encoded.items():
            temp = out / f".{name}.{uuid.uuid4().hex}.tmp"
            temp.write_bytes(value)
            _replace(temp, out / name)
    pointer = {
        "schema_version": REVISION_SCHEMA_VERSION,
        "artifact": artifact,
        "producer_version": producer_version,
        "revision_id": revision_id,
        "path": f"runs/{revision_id}",
    }
    pointer_temp = out / f".current.{uuid.uuid4().hex}.tmp"
    pointer_temp.write_text(json.dumps(pointer, indent=2, sort_keys=True), encoding="utf-8")
    _replace(pointer_temp, out / "current.json")
    return final
