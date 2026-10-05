r"""Retire a capture's video: keep its audio track, prove it equal, mark the manifest.

    .\.venv\Scripts\python.exe -m reticle retire <session> [--audio-dir DIR]
    .\.venv\Scripts\python.exe -m reticle retire <session> --commit [--force-reason TEXT]

Owns [owns:video-retirement].

The player decided (2026-10-05) to retire the capture corpus in batches and
rely on the events stream. Before a match's video is deleted its audio track
is kept by stream copy, checked against the capture and the crop caches, and
the audio readers are pointed at it (`audio_source`). Screen regions outside
the cached ROIs, the screen centre among them, come from future sessions,
never from retained video. Crop caches stay.

What one run does, per session:

1. Preconditions (`preconditions`), each read from its owner and refused by
   name: `plan_needs_video` (`plan.stale` names a step that decodes the
   capture: a reader stream `scan` rereads, which opens the video even where a
   crop cache could feed it, a `decode` stream, a crop-cache re-decode);
   `kept_replay` (the replay manifest `external/replays/manifest.json` names
   the session as a replay's `capture_session`); `dev_sample` and
   `held_out_window` (`dev_sample.MATCHES`, `dev_sample.HELD_OUT_WINDOWS`);
   `pending_labels` (a label set under `labels/<set>/` whose `index.json`
   names the session and whose asked items, `ask.json` or `queue.json`, the
   set's answers `labels/<set>.jsonl` have not all answered; a set with no
   item list is pending while no answer names the session). The ability-audio
   split (`ability_audio` parameters' `split`) is reported as a role the
   retained audio keeps, not refused: the fit reads only the stored log-mel.
   `--force-reason` names why the run proceeds past refusals; the row stores
   both.
2. Extraction (`extract_audio`): `ffmpeg -vn -c:a copy` of the first audio
   stream into an `.m4a`, at Below Normal priority on one thread; no
   re-encode, no video decoded. The sidecar records codec, sample rate,
   channels, start pts, duration, bytes and sha256 (`stream_meta`).
3. Alignment (`check_alignment`): the retained start pts and duration against the
   capture's audio stream; the audio's end against the manifest's
   `duration_ms`; each stored crop cache's `t_ms` span inside the audio span
   and on the manifest's frame grid (`t_ms = frame * 1000 / fps`); and every
   packet's pts, dts, duration, size and md5 equal (`ffmpeg -f framemd5`).
4. Readers (`AUDIO_READERS`, `reader_checks`): each audio reader's output
   from the capture and from the retained file, over the whole capture, and
   where stored, against the stored stream.
5. With `--commit` and every check passing: the retained file moves into
   `<store>/audio/<RETAINED_AUDIO_VERSION>/`, a row goes to
   `retirement/retirements.jsonl`, the manifest before the change is kept
   under `retirement/manifests/`, and the manifest gains `video_retired`.
   Without `--commit` nothing in the store changes; the audio goes to
   `--audio-dir` (default: a temporary folder, removed after the run).

It never deletes or moves the capture: it prints the command that deletes it.

The audio readers, found by searching the code for the capture path, `av`
audio streams and `ffplay`/`ffmpeg` audio use (2026-10-05):

* `ult_lines` (`reticle ult-lines`, `ult_line` rows): `decode_mono`,
  `phat_tracks`, `track_peaks`; compared as samples, score tracks and peaks,
  and against the stored `ult_line` peaks.
* the audio gate's log-mel (`prototypes/audio_gate.py features`, read by
  `ability-audio` through `ability_timeline.audio_session`): `log_mel` over
  `decode_mono`; compared as L, ok and RMS, and against the stored npz.
* `ability-audio` scores (`ability_timeline.audio_cast_witness`): the
  witness rows from a log-mel npz built from each file.
* the round viewer's sound (`round_view.Audio`, `ffplay`) and the audio
  prototypes with their own decoders (`audio_bank`, `audio_channel`,
  `audio_probe`, `audio_events`, `voice_lines`, `ult_ready_lines`): they
  read the same AAC packets, which the framemd5 comparison covers.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from .audio_source import (RETAINED_AUDIO_DIR, RETAINED_SUFFIX, retained_audio_path,
                           retirement, video_present)
from .version import RETAINED_AUDIO_VERSION, RETIRE_VERSION

#: Windows priority class of every child process (Below Normal).
BELOW_NORMAL = 0x00004000
#: The retirement rows and the manifests before each retirement, under the store.
RETIREMENT_DIR = Path("retirement")
RETIREMENT_LOG = RETIREMENT_DIR / "retirements.jsonl"
#: The audio's end may lie this far from the manifest's duration (ms): two
#: video frames at 60 fps and one AAC frame at 48 kHz, rounded up.
END_TOL_MS = 100.0
#: A cache time may lie this far off the manifest's frame grid (ms).
GRID_TOL_MS = 0.5
#: The audio readers `reader_checks` compares (see the module docstring).
AUDIO_READERS = ("decode_mono", "ult_lines", "audio_gate_log_mel", "ability_audio",
                 "packet_readers")


def _flags() -> int:
    return BELOW_NORMAL if os.name == "nt" else 0


def retire_priority() -> None:
    """This process at Below Normal priority, its numeric libraries on one thread."""
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def plan_steps(store, sid: str) -> list[dict]:
    """The steps `plan.stale` names for `sid` that need the capture."""
    from .plan import ACCEPT, stale
    p = stale(store, [sid])[sid]
    out = []
    for s in p["decode"]:
        if s["channel"] in ACCEPT:
            continue     # `ult-lines` reads the retained audio (`audio_source`)
        out.append({"step": f"scan --only {s['channel']}", "stream": s["stream"],
                    "why": "scan opens the capture"
                           + (f" (a trial reads the crop cache: {s['trial']})" if s.get("trial")
                              else "")})
    out += [{"step": d["command"], "stream": d["stream"], "why": "decodes the capture"}
            for d in p["derived"] if d.get("how") == "decode"]
    w = p.get("widget") or {}
    if "cache" in w:
        out.append({"step": w["cache"]["command"], "stream": "roi_cache:minimap",
                    "why": f"minimap crop cache {w['cache']['reason']}"})
    out += [{"step": c["command"], "stream": f"roi_cache:{c['set']}",
             "why": f"{c['set']} crop cache {c['reason']}"} for c in p.get("caches") or ()]
    return out


def kept_replays(store_root, sid: str) -> list[str]:
    """The kept replays the replay manifest pairs with `sid`."""
    p = Path(store_root) / "external" / "replays" / "manifest.json"
    if not p.is_file():
        return []
    man = json.loads(p.read_text(encoding="utf-8"))
    return [f["file"] for f in man.get("files", []) if f.get("capture_session") == sid]


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def pending_labels(store_root, sid: str) -> list[dict]:
    """Label sets that still ask the player about `sid` (module docstring, step 1)."""
    root = Path(store_root) / "labels"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        idx = d / "index.json"
        if not idx.is_file():
            continue
        try:
            index = json.loads(idx.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if sid not in (index.get("sessions") or {}):
            continue
        answered = {r.get("key") for r in _jsonl(root / f"{d.name}.jsonl")
                    if r.get("session") == sid or str(r.get("key", "")).startswith(sid)}
        asked = None
        for name in ("ask.json", "queue.json"):
            if (d / name).is_file():
                items = json.loads((d / name).read_text(encoding="utf-8")).get("items") or []
                asked = [it["key"] for it in items
                         if it.get("session") == sid or str(it.get("key", "")).startswith(sid)]
                break
        if asked is None:
            if not answered:
                out.append({"set": d.name, "asked": None, "unanswered": None,
                            "why": "the index names the session and no answer does"})
            continue
        left = [k for k in asked if k not in answered]
        if left:
            out.append({"set": d.name, "asked": len(asked), "unanswered": len(left),
                        "why": f"{len(left)} of {len(asked)} asked items unanswered"})
    return out


def audio_split_roles(store_root, sid: str) -> list[str]:
    """The ability-audio split roles of `sid` (`agent:dev|held`), which the
    retained audio keeps."""
    from .adjudication.ability_audio import params_path
    from .version import ABILITY_AUDIO_PARAMS_VERSION
    p = params_path(store_root, ABILITY_AUDIO_PARAMS_VERSION) / "provenance.json"
    if not p.is_file():
        return []
    split = json.loads(p.read_text(encoding="utf-8")).get("split") or {}
    return [f"{agent}:{part}" for agent, parts in sorted(split.items())
            for part, names in sorted(parts.items())
            if any(str(n).split(":")[0] == sid for n in names)]


def preconditions(store, manifest: dict) -> dict:
    """{"refusals": [...], "kept_by_audio": [...]}: why the video may not go yet."""
    from . import dev_sample
    sid = manifest["session_id"]
    refusals = []
    if not video_present(manifest):
        refusals.append({"reason": "video_missing", "owner": "manifest",
                         "detail": manifest["source"].get("path")})
    if retirement(manifest):
        refusals.append({"reason": "already_retired", "owner": "manifest",
                         "detail": retirement(manifest).get("at")})
    steps = plan_steps(store, sid)
    if steps:
        refusals.append({"reason": "plan_needs_video", "owner": "plan.stale",
                         "detail": steps})
    reps = kept_replays(store.root, sid)
    if reps:
        refusals.append({"reason": "kept_replay", "owner": "external/replays/manifest.json",
                         "detail": reps})
    if sid in dev_sample.MATCHES:
        n = sum(w.session == sid for w in dev_sample.SAMPLE)
        refusals.append({"reason": "dev_sample", "owner": "dev_sample.MATCHES",
                         "detail": f"{dev_sample.DEV_SAMPLE_VERSION}: a Riot-paired match, "
                                   f"{n} sample windows; its held-out sets ride the match"})
    held = [w for w in dev_sample.HELD_OUT_WINDOWS if w[0] == sid]
    if held:
        refusals.append({"reason": "held_out_window", "owner": "dev_sample.HELD_OUT_WINDOWS",
                         "detail": [list(w) for w in held]})
    pend = pending_labels(store.root, sid)
    if pend:
        refusals.append({"reason": "pending_labels", "owner": "labels/<set>/index.json",
                         "detail": pend})
    kept = [{"role": r, "owner": "ability_audio parameters split",
             "why": "the fit reads the stored log-mel, which the retained audio rebuilds"}
            for r in audio_split_roles(store.root, sid)]
    return {"refusals": refusals, "kept_by_audio": kept}


# ---------------------------------------------------------------------------
# Extraction and metadata
# ---------------------------------------------------------------------------

def ffmpeg() -> str:
    from .roi_cache import ffmpeg_path
    return ffmpeg_path()


def extract_command(video, out) -> list[str]:
    """Stream copy of the first audio stream: no re-encode, no video decoded."""
    return [ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
            "-i", str(video), "-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "copy",
            "-map_metadata", "0", "-f", "mp4", "-y", str(out)]


def extract_audio(video, out) -> dict:
    """Write `out` by stream copy (through a temporary file beside it) and
    return its metadata (`stream_meta`) with bytes and sha256."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    t0 = time.time()
    proc = subprocess.run(extract_command(video, tmp), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, creationflags=_flags())
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg exit {proc.returncode}: {proc.stderr.strip()[-500:]}")
    os.replace(tmp, out)
    meta = stream_meta(out)
    meta.update(bytes=out.stat().st_size, sha256=sha256_file(out),
                extract_s=round(time.time() - t0, 1))
    return meta


def stream_meta(path) -> dict:
    """The first audio stream's codec, rate, channels, time base, start pts,
    duration and extradata digest, and the video stream's start, read by PyAV
    from the container headers."""
    import av
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        cc = st.codec_context
        tb = st.time_base
        start = st.start_time if st.start_time is not None else 0
        dur = st.duration
        v = c.streams.video[0] if c.streams.video else None
        ex = bytes(cc.extradata or b"")
        return {"codec": cc.name, "profile": cc.profile, "sample_rate": int(st.rate),
                "channels": int(cc.channels), "layout": cc.layout.name,
                "bit_rate": int(cc.bit_rate or 0),
                "time_base": f"{tb.numerator}/{tb.denominator}",
                "start_pts": int(start), "start_s": float(start * tb),
                "duration_pts": None if dur is None else int(dur),
                "duration_s": None if dur is None else float(dur * tb),
                "frames": int(st.frames or 0),
                "extradata_sha256": hashlib.sha256(ex).hexdigest() if ex else None,
                "video_start_s": None if v is None or v.start_time is None
                else float(v.start_time * v.time_base)}


def framemd5(path) -> list[str]:
    """One line per audio packet: stream, dts, pts, duration, size, md5
    (`ffmpeg -f framemd5` on a stream copy; nothing decoded)."""
    proc = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
                           "-threads", "1", "-i", str(path), "-map", "0:a:0", "-c", "copy",
                           "-f", "framemd5", "-"], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, creationflags=_flags())
    if proc.returncode != 0:
        raise RuntimeError(f"framemd5 exit {proc.returncode}: {proc.stderr.strip()[-500:]}")
    return [x for x in proc.stdout.splitlines() if x and not x.startswith("#")]


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def compare_lines(a: list[str], b: list[str]) -> dict:
    n = min(len(a), len(b))
    differ = int(np.count_nonzero(np.asarray(a[:n], dtype=object) != np.asarray(b[:n], dtype=object)))
    return {"video": len(a), "retained": len(b), "compared": n,
            "differ": differ + abs(len(a) - len(b))}


def cache_spans(store_root, manifest: dict) -> dict:
    """Per stored crop cache set: its t_ms span, rows, and the largest
    distance of a stored time from the manifest's frame grid."""
    from .roi_cache import CACHE_SETS, cache_dir
    sid = manifest["session_id"]
    fps = float(manifest["source"]["fps"])
    out = {}
    for name in CACHE_SETS:
        p = cache_dir(store_root, name) / f"{sid}.idx.npy"
        if not p.is_file():
            continue
        idx = np.load(p)
        t, f = idx[:, 0], idx[:, 1]
        out[name] = {"rows": int(len(t)), "t_min_ms": float(t.min()), "t_max_ms": float(t.max()),
                     "grid_residual_ms": float(np.abs(t - f * 1000.0 / fps).max())}
    return out


def check_alignment(manifest: dict, video_meta: dict, audio_meta: dict, caches: dict,
              packets: dict) -> dict:
    """The checks of step 3, each with its numbers and `ok`."""
    rate = audio_meta["sample_rate"]
    frame_ms = 1000.0 / float(manifest["source"]["fps"])
    start_diff = (audio_meta["start_s"] - video_meta["start_s"]) * 1000.0
    dur_diff = (None if None in (audio_meta["duration_s"], video_meta["duration_s"])
                else (audio_meta["duration_s"] - video_meta["duration_s"]) * rate)
    a0 = audio_meta["start_s"] * 1000.0
    a1 = a0 + (audio_meta["duration_s"] or 0.0) * 1000.0
    end_gap = a1 - float(manifest["source"]["duration_ms"])
    checks = {
        "start": {"video_audio_start_s": video_meta["start_s"],
                  "retained_start_s": audio_meta["start_s"],
                  "video_stream_start_s": video_meta.get("video_start_s"),
                  "diff_ms": start_diff, "ok": abs(start_diff) <= 1000.0 / rate},
        "duration": {"video_audio_s": video_meta["duration_s"],
                     "retained_s": audio_meta["duration_s"], "diff_samples": dur_diff,
                     "ok": dur_diff is not None and abs(dur_diff) <= 1024},
        "manifest_end": {"audio_end_ms": a1, "manifest_duration_ms":
                         float(manifest["source"]["duration_ms"]), "gap_ms": end_gap,
                         "tol_ms": END_TOL_MS, "ok": abs(end_gap) <= END_TOL_MS},
        "stream": {k: [video_meta[k], audio_meta[k]] for k in
                   ("codec", "profile", "sample_rate", "channels", "layout", "time_base",
                    "extradata_sha256")},
        "packets": packets,
        "caches": {name: {**c, "ok": (c["grid_residual_ms"] <= GRID_TOL_MS
                                      and c["t_min_ms"] >= a0 - frame_ms
                                      and c["t_max_ms"] <= a1 + frame_ms)}
                   for name, c in caches.items()},
    }
    checks["stream"]["ok"] = all(a == b for k, (a, b) in checks["stream"].items() if k != "ok")
    checks["packets"]["ok"] = packets["differ"] == 0 and packets["compared"] > 0
    checks["ok"] = all(v["ok"] for k, v in checks.items() if k not in ("caches",)) and all(
        c["ok"] for c in checks["caches"].values())
    return checks


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _differ(a, b) -> dict:
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return {"compared": int(min(a.size, b.size)), "differ": None,
                "shapes": [list(a.shape), list(b.shape)]}
    same = (a == b) | (np.isnan(a) & np.isnan(b)) if a.dtype.kind == "f" else (a == b)
    return {"compared": int(a.size), "differ": int(a.size - np.count_nonzero(same))}


def _outputs(path: str, templates: list[dict], xp) -> dict:
    """Every audio reader's arrays from one file."""
    from . import ult_lines as ul
    t0 = time.time()
    x, filled, rate = ul.decode_mono(path)
    out = {"x": x, "filled": filled, "rate": rate, "decode_s": round(time.time() - t0, 1)}
    tracks = ul.phat_tracks(x, [t["wave"] for t in templates], xp=xp)
    out["tracks"] = tracks
    out["peaks"] = ul.track_peaks(tracks, [t["frames"] for t in templates])
    L, ok, rms = ul.log_mel(x, filled, rate, xp=xp)
    out.update(L=ul.to_host(L), ok=ul.to_host(ok), rms=ul.to_host(rms))
    ul.release_gpu(xp)
    return out


def _features_npz(out: dict, path: Path, version: str) -> Path:
    """A log-mel npz as the audio gate stores it (L and RMS float16, the
    per-band median of live frames float32), for the ability-audio witness."""
    L = out["L"]
    ok = out["ok"].astype(bool)
    med = np.median(L[ok], axis=0) if ok.any() else np.zeros(L.shape[1], np.float32)
    np.savez(path, L=L.astype(np.float16), ok=ok, rms=out["rms"].astype(np.float16),
             med=med.astype(np.float32), version=version)
    return path


def _witness(store, sid: str, features: Path) -> dict | None:
    from .ability_audio_fit import gate_snapshot
    from .ability_timeline import audio_cast_witness
    g = gate_snapshot(store, [sid], {}).get(sid)
    if g is None:
        return None
    res = audio_cast_witness(store.root, sid, g["rows"], g["agent"], g["kit_spans"],
                             features_path=features)
    cov = {k: v for k, v in res["coverage"].items() if k != "inputs"}
    return {"rows": res["rows"], "coverage": cov}


def _stored_ult_rows(store, sid: str) -> list[dict]:
    return [r for r in store.read_events("ult_line", sid) if r.get("kind") == "peak"]


def reader_checks(store, manifest: dict, video: str, audio: str, work: Path) -> dict:
    """Step 4: each audio reader from the capture and from the retained file."""
    from . import ult_lines as ul
    from .ability_timeline import AUDIO_GATE_DIR
    from .version import ULT_LINE_VERSION
    sid = manifest["session_id"]
    xp = ul.array_module()
    declared = ul.load_manifest()
    templates = ul.build_templates(store.root / ul.manifest_dir(declared), declared["templates"],
                                   xp=xp)
    a = _outputs(video, templates, xp)
    b = _outputs(audio, templates, xp)
    res = {"window": {"t0_s": 0.0, "t1_s": len(a["x"]) / a["rate"],
                      "why": "the whole capture"}}
    res["decode_mono"] = {"samples": _differ(a["x"], b["x"]),
                          "filled": _differ(a["filled"], b["filled"]),
                          "decode_s": [a["decode_s"], b["decode_s"]]}
    peaks = {k: _differ(a["peaks"][k], b["peaks"][k]) for k in a["peaks"]}
    res["ult_lines"] = {"tracks": _differ(a["tracks"], b["tracks"]), "peaks": peaks,
                        "backend": "cupy" if xp is not np else "numpy"}
    rows_b = ul.observations(sid, manifest["source"]["content_key"], ULT_LINE_VERSION, templates,
                             declared["key"], {}, b["peaks"])[1:]
    stored = _stored_ult_rows(store, sid)
    head = (store.read_events("ult_line", sid) or [{}])[0]
    key = lambda r: (r["frame"], r["template"], r["score"])
    if head.get("ult_line_version") == ULT_LINE_VERSION and head.get("templates_key") == declared["key"]:
        got, want = {key(r) for r in rows_b}, {key(r) for r in stored}
        res["ult_lines"]["stored"] = {"retained_rows": len(rows_b), "stored_rows": len(stored),
                                      "differ": len(got ^ want)}
    else:
        res["ult_lines"]["stored"] = {"skipped": f"stored at {head.get('ult_line_version')}, "
                                                 f"templates {head.get('templates_key')}"}
    del a["tracks"], b["tracks"], a["x"], b["x"]
    lm = {k: _differ(a[k], b[k]) for k in ("L", "ok", "rms")}
    fp = Path(store.root) / AUDIO_GATE_DIR / "features" / f"{sid}.npz"
    version = "unstamped"
    if fp.is_file():
        with np.load(fp, allow_pickle=True) as z:
            version = str(z["version"]) if "version" in z.files else version
            lm["stored"] = {"L": _differ(z["L"], b["L"].astype(np.float16)),
                            "ok": _differ(z["ok"], b["ok"]),
                            "rms": _differ(z["rms"], b["rms"].astype(np.float16))}
    else:
        lm["stored"] = {"skipped": "no stored audio-gate features"}
    res["audio_gate_log_mel"] = lm
    fa = _features_npz(a, work / f"{sid}.video.features.npz", version)
    fb = _features_npz(b, work / f"{sid}.retained.features.npz", version)
    del a, b
    wa, wb = _witness(store, sid, fa), _witness(store, sid, fb)
    if wa is None or wb is None:
        res["ability_audio"] = {"skipped": "the identity arbiter names no player agent"}
    else:
        da = json.dumps(wa, sort_keys=True, default=str)
        db = json.dumps(wb, sort_keys=True, default=str)
        rows_differ = sum(json.dumps(x, sort_keys=True, default=str)
                          != json.dumps(y, sort_keys=True, default=str)
                          for x, y in zip(wa["rows"], wb["rows"]))
        res["ability_audio"] = {"rows": len(wa["rows"]), "rows_retained": len(wb["rows"]),
                                "rows_differ": rows_differ + abs(len(wa["rows"]) - len(wb["rows"])),
                                "coverage_equal": da == db or wa["coverage"] == wb["coverage"],
                                "reason": wa["coverage"].get("reason"),
                                "verdicts": wa["coverage"].get("verdicts")}
    for p in (fa, fb):
        p.unlink(missing_ok=True)
    res["packet_readers"] = {"covered_by": "alignment.packets (framemd5)",
                             "readers": ["round_view.Audio (ffplay)", "prototypes/audio_bank.py",
                                         "prototypes/audio_channel.py", "prototypes/audio_probe.py",
                                         "prototypes/audio_events.py", "prototypes/voice_lines.py",
                                         "prototypes/ult_ready_lines.py"]}
    res["ok"] = _readers_ok(res)
    return res


def _counts(d) -> list:
    """Every `differ` count in a nested result."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("differ", "rows_differ"):
                out.append(v)
            else:
                out += _counts(v)
    return out


def _readers_ok(res: dict) -> bool:
    counts = _counts({k: v for k, v in res.items() if k != "window"})
    eq = res.get("ability_audio", {}).get("coverage_equal", True)
    return bool(counts) and all(c == 0 for c in counts) and eq


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------

def deletion_command(manifest: dict) -> str:
    """The PowerShell command that deletes the capture; `retire` prints it and never runs it."""
    p = str(manifest["source"]["path"]).replace("'", "''")
    return f"Remove-Item -LiteralPath '{p}'"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def retire(store, sid: str, *, commit: bool = False, force_reason: str | None = None,
           audio_dir=None, check_readers: bool = True) -> dict:
    """Run steps 1-5 for one session and return its row (module docstring)."""
    t_start = time.time()
    man = store.read_manifest(sid)
    pre = preconditions(store, man)
    refused = pre["refusals"]
    hard = [r for r in refused if r["reason"] in ("video_missing", "already_retired")]
    row = {"session_id": sid, "retire_version": RETIRE_VERSION,
           "retained_audio_version": RETAINED_AUDIO_VERSION, "at": _now(), "commit": commit,
           "content_key": man["source"].get("content_key"), "video": man["source"].get("path"),
           "video_bytes": man["source"].get("size_bytes"), "preconditions": pre,
           "force_reason": force_reason}
    if hard or (commit and refused and not force_reason):
        row.update(status="refused", reasons=[r["reason"] for r in refused])
        return row
    final = retained_audio_path(store.root, sid)
    if commit and final.exists():
        row.update(status="refused", reasons=["retained_audio_exists"], detail=str(final))
        return row
    tmpdir = None
    if commit:
        work = final.parent / ".work"
    elif audio_dir:
        work = Path(audio_dir)
    else:
        tmpdir = tempfile.mkdtemp(prefix="reticle-retire-")
        work = Path(tmpdir)
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{sid}{RETAINED_SUFFIX}"
    try:
        video = man["source"]["path"]
        audio = extract_audio(video, out)
        vmeta = stream_meta(video)
        pk = compare_lines(framemd5(video), framemd5(out))
        align = check_alignment(man, vmeta, audio, cache_spans(store.root, man), pk)
        readers = (reader_checks(store, man, video, str(out), work) if check_readers
                   else {"skipped": "--no-readers", "ok": False})
        ok = align["ok"] and readers["ok"]
        rel = (RETAINED_AUDIO_DIR / final.name).as_posix()
        row.update(audio={**audio, "path": rel if commit else str(out)},
                   video_audio=vmeta, alignment=align, readers=readers, verified=ok,
                   wall_s=round(time.time() - t_start, 1))
        if not commit:
            row["status"] = "dry_run_verified" if ok else "dry_run_failed"
            return row
        if not ok:
            row["status"] = "verification_failed"
            out.unlink(missing_ok=True)
            return row
        os.replace(out, final)
        row["status"] = "retired"
        record_retirement(store, man, row)
        row["delete_command"] = deletion_command(man)
        return row
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def record_retirement(store, man: dict, row: dict) -> None:
    """Append the row, keep the manifest as it was, and mark it `video_retired`."""
    root = Path(store.root)
    log = root / RETIREMENT_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as f:
        f.write((json.dumps(row, default=str) + "\r\n").encode("utf-8"))
    sid = man["session_id"]
    keep = root / RETIREMENT_DIR / "manifests" / f"{sid}.{row['at'][:19].replace(':', '')}.json"
    keep.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(store.manifest_path(sid), keep)
    a = row["audio"]
    man = dict(man)
    man["video_retired"] = {
        "at": row["at"], "retire_version": RETIRE_VERSION, "force_reason": row["force_reason"],
        "refusals_overridden": [r["reason"] for r in row["preconditions"]["refusals"]],
        "manifest_before": keep.relative_to(root).as_posix(),
        "audio": {k: a.get(k) for k in ("path", "codec", "profile", "sample_rate", "channels",
                                        "layout", "time_base", "start_pts", "start_s",
                                        "duration_pts", "duration_s", "bytes", "sha256")}
                 | {"version": RETAINED_AUDIO_VERSION},
        "verification": {"retire_version": RETIRE_VERSION, "alignment_ok": row["alignment"]["ok"],
                         "readers_ok": row["readers"]["ok"],
                         "packets": row["alignment"]["packets"],
                         "row": RETIREMENT_LOG.as_posix()}}
    store.manifest_path(sid).write_text(json.dumps(man, indent=2), encoding="utf-8")


def retire_summary(row: dict) -> str:
    """The lines `reticle retire` prints for one row."""
    sid = row["session_id"]
    lines = [f"{sid}: {row['status']}"]
    for r in row["preconditions"]["refusals"]:
        d = r["detail"]
        if r["reason"] == "plan_needs_video":
            by: dict[str, list[str]] = {}
            for x in d:
                by.setdefault(x["step"], []).append(x["stream"])
            d = "; ".join(f"{step} ({', '.join(s)})" for step, s in by.items())
        elif r["reason"] == "pending_labels":
            d = "; ".join(f"{x['set']}: {x['why']}" for x in d)
        elif isinstance(d, list):
            d = "; ".join(str(x) for x in d)
        lines.append(f"  refused  {r['reason']} ({r['owner']}): {d}")
    for k in row["preconditions"]["kept_by_audio"]:
        lines.append(f"  kept     {k['role']} ({k['owner']}): {k['why']}")
    if row.get("force_reason"):
        lines.append(f"  forced   {row['force_reason']}")
    if "audio" in row:
        a, al, rd = row["audio"], row["alignment"], row["readers"]
        lines.append(f"  audio    {a['path']}: {a['codec']} {a['sample_rate']} Hz "
                     f"{a['channels']} ch, start {a['start_s']} s, {a['duration_s']} s, "
                     f"{a['bytes']} bytes ({100.0 * a['bytes'] / max(1, row['video_bytes'] or 1):.2f}% "
                     f"of the capture), sha256 {a['sha256'][:16]}")
        lines.append(f"  align    start diff {al['start']['diff_ms']:.3f} ms, duration diff "
                     f"{al['duration']['diff_samples']} samples, end gap "
                     f"{al['manifest_end']['gap_ms']:.1f} ms, packets "
                     f"{al['packets']['compared']} compared {al['packets']['differ']} differ; "
                     f"caches " + ", ".join(f"{n} {c['t_min_ms']:.0f}-{c['t_max_ms']:.0f} ms "
                                            f"{'ok' if c['ok'] else 'OUTSIDE'}"
                                            for n, c in al["caches"].items()))
        for name in AUDIO_READERS:
            if name in rd:
                lines.append(f"  reader   {name}: {json.dumps(rd[name], default=str)[:400]}")
        lines.append(f"  verified {row['verified']} in {row['wall_s']} s")
    if row.get("delete_command"):
        lines.append(f"  delete   {row['delete_command']}")
    return "\n".join(lines)
