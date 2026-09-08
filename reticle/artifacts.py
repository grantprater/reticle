"""Explicit artifact dependencies shared by producers and stale-input checks.

This registry reports affected artifacts; it never schedules work or rewrites the
store. Whole-file hashes remain conservative. Definition membership is recorded
in each fingerprint's keys, so adding/removing a dependency also invalidates it.
Source and asset hashes remain per-run provenance, separate from code and metric
definition stamps. Parent artifacts express consumption, not duplicated code.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class ArtifactSpec:
    code: tuple[str, ...]
    parents: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()


ARTIFACTS = {
    "coaching": ArtifactSpec(
        ("artifacts.py", "coaching.py", "review.py", "rounds.py", "roster.py", "checks.py", "version.py"),
        inputs=("manifest", "hud", "roster")),
    "refinement": ArtifactSpec(
        ("artifacts.py", "refinement.py", "refine.py", "cli.py", "hud_reader.py", "ocr.py",
         "killfeed.py", "profiles.py", "version.py", "fingerprint.py"),
        parents=("coaching",), inputs=("media", "digit_templates", "killfeed_templates", "kf_mask")),
}


def file_digest(path):
    """Stream large stored tables instead of reading an entire file into memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def producer_fingerprint(artifact, root=None):
    """Fingerprint the artifact's direct producer; parents carry their own stamp."""
    root = Path(root) if root is not None else Path(__file__).parent
    return {name: file_digest(root / name) for name in ARTIFACTS[artifact].code}


def changed_producers(artifact, recorded, root=None):
    current = producer_fingerprint(artifact, root)
    return sorted(name for name in current.keys() | recorded.keys()
                  if current.get(name) != recorded.get(name))


def affected_artifacts(changed_paths):
    """Conservative code impact for repository-relative paths, then dependents.

    Changes to registry logic invalidate all declarations conservatively. Runtime
    data/asset invalidation still compares per-run input hashes at the consumer.
    """
    paths = {str(p).replace('\\', '/') for p in changed_paths}
    if 'reticle/artifacts.py' in paths:
        return sorted(ARTIFACTS)
    affected = {name for name, spec in ARTIFACTS.items()
                if any(f'reticle/{path}' in paths for path in spec.code)}
    while True:
        more = {name for name, spec in ARTIFACTS.items() if affected.intersection(spec.parents)}
        if more <= affected:
            return sorted(affected)
        affected.update(more)
