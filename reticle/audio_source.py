"""Which file holds a session's audio track.

Owns [owns:session-audio-source].

The capture holds the audio while its video is on disk. The player decided
(2026-10-05) to retire the capture corpus in batches: before a capture is
deleted, `reticle retire` keeps its audio track by stream copy under
`<store>/audio/<RETAINED_AUDIO_VERSION>/<sid>.m4a`, checks it against the
capture and the crop caches, and marks the manifest `video_retired`. From
then on this module names the retained file once the capture is gone.

Every audio reader asks `audio_source` for the file it reads: `reticle
ult-lines`, the audio gate's log-mel features (`prototypes/audio_gate.py
features`, which `ability-audio` reads), the round viewer's sound and the
audio prototypes. None reads `manifest["source"]["path"]` for sound.

The rule. The capture while it is on disk; after it is gone, the retained
audio the manifest's `video_retired` names, if it is on disk at the size the
manifest recorded. Both files carry the same AAC packets (`retire` compared
them packet by packet before marking the manifest), so a reader gives the
same output from either. A session with neither returns no path and the
reason: `source_media_moved` (no retirement recorded),
`retained_audio_missing` or `retained_audio_size_mismatch`.

`video_state` says what `plan`, `status` and `doctor` need: `present`,
`retired` (the video is gone, the audio kept), `retired_present` (marked,
video not yet deleted) or `missing` (gone with no retirement recorded).
"""
from __future__ import annotations

from pathlib import Path

from .version import RETAINED_AUDIO_VERSION

#: The retained audio's folder under the store root.
RETAINED_AUDIO_DIR = Path("audio") / RETAINED_AUDIO_VERSION
#: The container a stream-copied AAC track is kept in.
RETAINED_SUFFIX = ".m4a"


def retained_audio_path(store_root, session_id: str) -> Path:
    """Where `retire` keeps a session's audio track in the store."""
    return Path(store_root) / RETAINED_AUDIO_DIR / f"{session_id}{RETAINED_SUFFIX}"


def retirement(manifest: dict) -> dict | None:
    """The manifest's `video_retired` record, or None where the video is not retired."""
    return manifest.get("video_retired") or None


def video_present(manifest: dict) -> bool:
    """Whether the capture the manifest names is on disk."""
    p = manifest.get("source", {}).get("path")
    return bool(p) and Path(p).is_file()


def video_state(manifest: dict) -> str:
    """`present`, `retired`, `retired_present` or `missing` (see the module docstring)."""
    here = video_present(manifest)
    if retirement(manifest):
        return "retired_present" if here else "retired"
    return "present" if here else "missing"


def _retained(manifest: dict, store_root) -> tuple[Path | None, str | None]:
    rec = retirement(manifest)
    if rec is None:
        return None, "source_media_moved"
    audio = rec.get("audio") or {}
    p = Path(audio.get("path") or "")
    if not p.is_absolute():
        p = Path(store_root) / p
    if not p.is_file():
        return None, "retained_audio_missing"
    if audio.get("bytes") is not None and p.stat().st_size != int(audio["bytes"]):
        return None, "retained_audio_size_mismatch"
    return p, None


def audio_source(manifest: dict, store_root) -> dict:
    """{"path", "kind", "reason"}: the file a reader decodes the session's
    audio from. `kind` is `video` or `retained_audio`; where neither file is
    usable `path` and `kind` are None and `reason` says why."""
    if video_present(manifest):
        return {"path": str(manifest["source"]["path"]), "kind": "video", "reason": None}
    p, why = _retained(manifest, store_root)
    if p is None:
        return {"path": None, "kind": None, "reason": why}
    return {"path": str(p), "kind": "retained_audio", "reason": None}


def audio_path(manifest: dict, store_root) -> str:
    """`audio_source`'s path, or SystemExit with the reason; for prototypes
    and commands that stop on a missing source."""
    got = audio_source(manifest, store_root)
    if got["path"] is None:
        raise SystemExit(f"{manifest['session_id']}: no audio source ({got['reason']})")
    return got["path"]
