"""A new capture's replay, kept, linked, parsed, wrapped and built.

[owns:replay-keeping]

    reticle replay-keep SESSION [--demos DIR]

docs/REPLAY_KEEPING.md is the protocol: the player downloads the match's
replay in the client; an agent keeps it. This module is the agent's half, as
six steps, each idempotent and each refused by name:

1. `find_replay`: the replay whose recording overlaps the capture. The
   capture's span is its file name's local start (`capture_start_ms`, the
   recorder's `YYYY-MM-DD HH-MM-SS`) plus the manifest's duration; a
   replay's span is its header's recording timestamp plus its length
   (`read_info`). Candidates are the client's Demos folder and the replays
   already kept. Zero or several overlapping replays refuse.
   The header's timestamp, not the file's mtime, dates the recording: the
   client stamps the mtime at download, which can be hours after the match
   (b03fecd3's mtime is 8 h after its recording ended). The mtime serves
   only a header without a timestamp, as `mtime - length`.
2. `keep`: a byte copy into `<store>/external/replays/`, sha256 of source
   and copy compared; a kept file whose sha256 differs from the source
   refuses.
3. `link_manifest`: the manifest entry (`external/replays/manifest.json`)
   names the capture session and path. A `.bak` of the manifest is written before each
   change. An entry naming another session, or another entry naming this
   session, refuses. This is the one store manifest this module writes.
4. `parse_replay`: vrfkit validate, export and spike carrier, once.
5. `wrap_riot`: the Riot record the player's fetch kit saved
   (`external/riot-pd-v1/raw/`) wrapped into `external/riot/`; without one,
   the refusal says the player's fetch is needed (docs/MATCH_FETCH_KIT.md).
6. The replay layer and its episodes (`replay_layer.build`,
   `episodes.build`) where absent or stale; the layer waits for the stored
   deaths its clock is fitted on.

`missing_steps` names what a session lacks of these, for `plan`.
`reticle ingest-passes` runs the steps at its end, so an ingest keeps its
replay without being asked; the layer then waits in `plan` behind the deaths.

Nothing here reads pixels or is shown during play: the replay is external
truth under docs/EXTERNAL_GROUND_TRUTH.md's use policy, and the held-out
match (`replay_layer.HELD_OUT`) is built and never summarised.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

from .replay_source import (VRFKIT_VERSION, file_sha256, parsed_dir, replay_manifest,
                            replays_dir, riot_records)
from .store import DEFAULT_STORE

REPLAY_KEEP_VERSION = "replay-keep-0.1.0"
#: Where the client writes downloaded replays; it rotates the folder.
DEMOS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) \
    / "VALORANT" / "Saved" / "Demos"
#: The replay container's magic (Riot's, in place of UE's 0x1CA2E27F).
VRF_MAGIC = 0x43F4EFDD
#: UE `FDateTime` ticks (100 ns) from 0001-01-01 to the Unix epoch.
_EPOCH_TICKS = 621355968000000000
BELOW_NORMAL = 0x00004000
SINGLE_THREAD_ENV = {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                     "OPENBLAS_NUM_THREADS": "1", "RAYON_NUM_THREADS": "1"}
#: How far before Riot's game start a capture may begin, and the slack after
#: the game ends, when the capture file's name gives its local start time.
WRAP_EARLY_MS = 15 * 60 * 1000.0
WRAP_LATE_MS = 5 * 60 * 1000.0
FETCH_NEEDED = ("no_fetched_record: the player's fetch kit must save the match "
                "(docs/MATCH_FETCH_KIT.md)")


# ----------------------------------------------------------------- times

def capture_start_ms(capture_path: str) -> float | None:
    """The capture's start from its file name (`YYYY-MM-DD HH-MM-SS.mp4`, the
    recorder's local time) as epoch ms, or None when the name has no stamp."""
    stem = Path(str(capture_path).replace("\\", "/")).stem
    try:
        return _dt.datetime.strptime(stem[:19], "%Y-%m-%d %H-%M-%S").timestamp() * 1000.0
    except ValueError:
        return None


def read_info(vrf: Path) -> dict:
    """The replay's info header (UE `LocalFileNetworkReplayStreamer` layout
    under Riot's magic): `length_ms` and `recorded_ms` (epoch ms, UTC; None
    where the header holds no timestamp), or `{"refused": reason}`."""
    try:
        with open(vrf, "rb") as f:
            b = f.read(4096)
        magic, version = struct.unpack_from("<II", b, 0)
        if magic != VRF_MAGIC:
            return {"refused": f"not_a_replay:magic_{magic:#x}"}
        off = 8
        if version >= 7:                      # custom version container
            n, = struct.unpack_from("<i", b, off)
            off += 4 + 20 * n
        length, _net, _cl, slen = struct.unpack_from("<iIIi", b, off)
        off += 16 + (-2 * slen if slen < 0 else slen)
        off += 4                              # bIsLive
        recorded = None
        if version >= 1:
            ticks, = struct.unpack_from("<q", b, off)
            recorded = (ticks - _EPOCH_TICKS) / 10_000.0
        return {"file_version": version, "length_ms": int(length), "recorded_ms": recorded}
    except (OSError, struct.error) as e:
        return {"refused": f"unreadable_header:{type(e).__name__}"}


def replay_span(vrf: Path) -> dict:
    """`{start_ms, end_ms, basis, length_ms, recorded_ms}` of one replay, or
    `{"refused"}`: the header's timestamp plus its length (`header`), else
    the mtime minus the length (`mtime`)."""
    info = read_info(vrf)
    if "refused" in info:
        return info
    if info["recorded_ms"] is not None:
        start, basis = info["recorded_ms"], "header"
    else:
        start, basis = Path(vrf).stat().st_mtime * 1000.0 - info["length_ms"], "mtime"
    return {**info, "start_ms": start, "end_ms": start + info["length_ms"], "basis": basis}


def overlapping(cap_start: float, cap_end: float, spans: dict[str, dict]) -> list[str]:
    """The replays (name -> span) whose recording overlaps the capture's
    span by more than zero ms, in name order."""
    return sorted(n for n, s in spans.items() if "refused" not in s
                  and min(cap_end, s["end_ms"]) - max(cap_start, s["start_ms"]) > 0)


# ----------------------------------------------------------------- step 1

def _replay_files(root, demos: Path | None) -> dict[str, Path]:
    """Every replay the client's Demos folder or the store holds, by file
    name; the Demos copy wins where both hold one (it is the source)."""
    out: dict[str, Path] = {}
    for d in (replays_dir(root), demos):
        if d is not None and Path(d).is_dir():
            out.update({p.name: p for p in sorted(Path(d).glob("*.vrf"))})
    return out


_SPANS: dict[tuple[str, float, int], dict] = {}


def _span_memo(p: Path) -> dict:
    st = p.stat()
    key = (str(p), st.st_mtime, st.st_size)
    if key not in _SPANS:
        _SPANS[key] = replay_span(p)
    return _SPANS[key]


def find_replay(manifest: dict, root=DEFAULT_STORE, demos: Path | None = DEMOS_DIR) -> dict:
    """`{"file", "path", "span", "overlap_ms"}` for the one replay whose
    recording overlaps the capture, or `{"refused"}`: a capture name with no
    stamp, a manifest with no duration, no replay, or several."""
    src = manifest.get("source") or {}
    if not src.get("path"):
        return {"refused": "capture_path_unknown"}
    start = capture_start_ms(src["path"])
    if start is None:
        return {"refused": f"capture_name_has_no_stamp:{Path(src['path']).name}"}
    if not src.get("duration_ms"):
        return {"refused": "capture_duration_unknown"}
    end = start + float(src["duration_ms"])
    paths = _replay_files(root, demos)
    spans = {n: _span_memo(p) for n, p in paths.items()}
    hits = overlapping(start, end, spans)
    if not hits:
        return {"refused": f"no_replay_overlaps_capture:{len(spans)}_replays_searched"}
    if len(hits) > 1:
        return {"refused": "several_replays_overlap_capture:" + ",".join(hits)}
    s = spans[hits[0]]
    return {"file": hits[0], "path": str(paths[hits[0]]), "span": s,
            "overlap_ms": round(min(end, s["end_ms"]) - max(start, s["start_ms"]))}


# ----------------------------------------------------------------- step 2

def keep(source: Path, root=DEFAULT_STORE) -> dict:
    """Copy one replay into the store byte for byte. `{"kept": "copied" |
    "already_kept", "sha256"}` or `{"refused"}`. A copy is written beside its
    destination and renamed into place only once both sha256s agree."""
    source = Path(source)
    dest = replays_dir(root) / source.name
    if source.resolve() == dest.resolve():
        return {"kept": "already_kept", "sha256": file_sha256(dest)}
    want = file_sha256(source)
    if dest.is_file():
        have = file_sha256(dest)
        if have != want:
            return {"refused": f"kept_copy_differs_from_source:{dest.name}"}
        return {"kept": "already_kept", "sha256": have}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".copying")
    shutil.copy2(source, tmp)
    if file_sha256(tmp) != want:
        return {"refused": f"copy_sha256_differs:{tmp.name}"}
    tmp.replace(dest)
    return {"kept": "copied", "sha256": want}


# ----------------------------------------------------------------- step 3

def _utc_iso(ms: float | None) -> str | None:
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc).isoformat()


def link_entry(man: dict, file: str, sid: str, capture_path: str, *, size: int | None = None,
               sha256: str | None = None, span: dict | None = None,
               source_mtime_ms: float | None = None) -> dict:
    """The manifest `man` with `file`'s entry naming session `sid`, as
    `{"manifest", "changed"}` or `{"refused"}`; `man` is not modified. A
    missing entry is created; null header fields fill from `span`."""
    man = json.loads(json.dumps(man))
    files = man.setdefault("files", [])
    other = next((f for f in files if f.get("capture_session") == sid and f["file"] != file), None)
    if other is not None:
        return {"refused": f"session_names_another_replay:{other['file']}"}
    entry = next((f for f in files if f["file"] == file), None)
    if entry is None:
        entry = {"file": file, "size": size, "sha256": sha256, "sha256_verified": True,
                 "source_mtime_utc": _utc_iso(source_mtime_ms), "recorded_utc": None,
                 "length_ms": None, "map": None, "riot_record": None,
                 "capture_session": None, "capture_path": None,
                 "kept_by": REPLAY_KEEP_VERSION}
        files.append(entry)
    if entry.get("capture_session") not in (None, sid):
        return {"refused": f"replay_names_session:{entry['capture_session']}"}
    before = json.dumps(entry, sort_keys=True)
    entry["capture_session"] = sid
    entry["capture_path"] = str(capture_path).replace("\\", "/")
    if span and "refused" not in span:
        if entry.get("length_ms") is None:
            entry["length_ms"] = span["length_ms"]
        if entry.get("recorded_utc") is None and span.get("recorded_ms") is not None:
            entry["recorded_utc"] = _utc_iso(span["recorded_ms"])
    if json.dumps(entry, sort_keys=True) != before:
        entry["linked_by"] = REPLAY_KEEP_VERSION
    return {"manifest": man, "changed": json.dumps(entry, sort_keys=True) != before}


def link_manifest(file: str, sid: str, capture_path: str, root=DEFAULT_STORE, *,
                  size: int | None = None, sha256: str | None = None, span: dict | None = None,
                  source_mtime_ms: float | None = None) -> dict:
    """Write `link_entry`'s change to `external/replays/manifest.json`,
    copying the manifest to `manifest.json.bak` first."""
    p = replays_dir(root) / "manifest.json"
    res = link_entry(replay_manifest(root), file, sid, capture_path, size=size, sha256=sha256,
                     span=span, source_mtime_ms=source_mtime_ms)
    if "refused" in res or not res["changed"]:
        return {k: v for k, v in res.items() if k != "manifest"} | (
            {} if "refused" in res else {"linked": "already_linked"})
    if p.is_file():
        shutil.copy2(p, p.with_name("manifest.json.bak"))
    tmp = p.with_name("manifest.json.writing")
    tmp.write_text(json.dumps(res["manifest"], indent=2), encoding="utf-8", newline="\n")
    tmp.replace(p)
    return {"linked": "written", "backup": "manifest.json.bak"}


# ----------------------------------------------------------------- step 4

def vrfkit_dir(root=DEFAULT_STORE) -> Path:
    return Path(root) / "tools" / "vrfkit"


def _run_tool(cmd: list[str], cwd: Path | None = None, out: Path | None = None) -> dict:
    """Run one command at Below Normal priority, single-threaded, and time it."""
    t0 = time.time()
    flags = BELOW_NORMAL if sys.platform == "win32" else 0
    p = subprocess.run(cmd, cwd=cwd, env={**os.environ, **SINGLE_THREAD_ENV},
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=flags)
    if out is not None:
        out.write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""),
                       encoding="utf-8")
    return {"cmd": cmd, "exit": p.returncode, "seconds": round(time.time() - t0, 2),
            "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-800:]}


def _git_head(d: Path) -> str:
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def _toolchain() -> dict:
    out = {}
    for tool in ("rustc", "cargo"):
        exe = Path.home() / ".cargo" / "bin" / f"{tool}.exe"
        out[tool] = subprocess.run([str(exe), "-V"], capture_output=True,
                                   text=True).stdout.strip() if exe.is_file() else None
    return out


def is_parsed(match: str, root=DEFAULT_STORE) -> bool:
    return (parsed_dir(match, root) / "export" / "actors.parquet").is_file()


def parse_replay(vrf: Path, force: bool = False, root=DEFAULT_STORE) -> dict:
    """vrfkit validate + export + spike carrier for one kept replay, once:
    an existing `provenance.json` is returned unless `force`."""
    vrf = Path(vrf)
    match = vrf.stem
    d = parsed_dir(match, root)
    prov_p = d / "provenance.json"
    if prov_p.is_file() and not force:
        return json.loads(prov_p.read_text(encoding="utf-8"))
    tools = vrfkit_dir(root)
    exe = tools / "target" / "release" / "vrfkit.exe"
    d.mkdir(parents=True, exist_ok=True)
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    digest = file_sha256(vrf)
    want = next((f["sha256"] for f in replay_manifest(root).get("files") or []
                 if f["file"] == vrf.name), None)
    steps = {"validate": _run_tool([str(exe), "validate", str(vrf)], out=d / "validate.txt"),
             "export": _run_tool([str(exe), "export", str(vrf), "--out", str(d / "export")],
                            out=d / "export.txt")}
    if steps["export"]["exit"] == 0:
        steps["spike_carrier"] = _run_tool(
            [sys.executable, str(tools / "tools" / "extract_spike_carrier.py"),
             "--export", str(d / "export"), "--out", str(d / "spike_carrier.parquet")],
            cwd=tools / "tools", out=d / "spike_carrier.txt")
    prov = {"kind": "vrfkit-parse", "replay_keep_version": REPLAY_KEEP_VERSION,
            "input": str(vrf).replace("\\", "/"), "input_sha256": digest,
            "input_sha256_matches_manifest": digest == want,
            "vrfkit": {"version": VRFKIT_VERSION, "commit": _git_head(tools),
                       "exe": str(exe).replace("\\", "/"), "exe_sha256": file_sha256(exe)},
            "toolchain": _toolchain(), "python": sys.version.split()[0],
            "priority": "Below Normal (creationflags 0x4000)",
            "started_utc": started,
            "finished_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "steps": steps}
    prov_p.write_text(json.dumps(prov, indent=1), encoding="utf-8")
    return prov


# ----------------------------------------------------------------- step 5

def riot_raw_path(match: str, root=DEFAULT_STORE) -> Path:
    return Path(root) / "external" / "riot-pd-v1" / "raw" / f"{match}.json"


def riot_wrapped_path(match: str, root=DEFAULT_STORE) -> Path:
    return Path(root) / "external" / "riot" / f"{match}.json"


def wrap_record(raw: bytes, prov: dict, match: str, session: str, capture_path: str,
                replay_session: str | None, wrapped_sessions: dict[str, str]) -> dict:
    """One fetched match-details body as `riot_records`' wrapped record.

    `raw` is `riot-pd-v1/raw/<match>.json` byte for byte and `prov` its
    sidecar; `replay_session` is the capture session the replay manifest names
    for this match (None when it names none); `wrapped_sessions` maps each
    session already wrapped in `external/riot/` to its match. Returns
    `{"record": ...}` or `{"refused": reason}`: a body whose sha256 differs
    from the sidecar's, a record of another match, a session another record
    already holds, a replay that names another session, or a capture whose
    name puts its start outside the game's span."""
    digest = hashlib.sha256(raw).hexdigest()
    if prov.get("body_sha256") != digest:
        return {"refused": "raw_sha256_differs_from_provenance"}
    rec = json.loads(raw.decode("utf-8"))
    info = rec.get("matchInfo") or {}
    if info.get("matchId") != match:
        return {"refused": f"record_is_match:{info.get('matchId')}"}
    if wrapped_sessions.get(session) not in (None, match):
        return {"refused": f"session_already_wrapped:{wrapped_sessions[session]}"}
    if replay_session not in (None, session):
        return {"refused": f"replay_names_session:{replay_session}"}
    start, length = info.get("gameStartMillis"), info.get("gameLengthMillis")
    cap = capture_start_ms(capture_path)
    delta = None
    if cap is not None and start is not None:
        delta = cap - float(start)
        if not (-WRAP_EARLY_MS <= delta <= float(length or 0) + WRAP_LATE_MS):
            return {"refused": f"capture_outside_game:{delta / 1000.0:.0f}s"}
    probe = {"session_id": session, "capture": capture_path,
             "fetched_at": prov.get("fetched_at"),
             "wrapped_by": REPLAY_KEEP_VERSION,
             "raw": f"external/riot-pd-v1/raw/{match}.json", "raw_sha256": digest,
             "capture_minus_game_start_s": None if delta is None else round(delta / 1000.0, 1)}
    return {"record": {"probe": probe, "match": rec}}


def wrap_riot(match: str, session: str, write: bool = False, store=DEFAULT_STORE) -> dict:
    """Wrap a fetched record into `external/riot/`.

    Reads `external/riot-pd-v1/raw/<match>.json` and its provenance sidecar,
    checks them (`wrap_record`), and with `write` creates
    `external/riot/<match>.json`; it never overwrites a wrapped file."""
    from .store import Store

    pd = Path(store) / "external" / "riot-pd-v1"
    raw_p, prov_p = pd / "raw" / f"{match}.json", pd / "provenance" / f"{match}.json"
    out_p = riot_wrapped_path(match, store)
    if not raw_p.is_file() or not prov_p.is_file():
        return {"match": match, "refused": "no_fetched_record"}
    if out_p.is_file():
        return {"match": match, "refused": "already_wrapped", "path": str(out_p)}
    man = Store(store).read_manifest(session)
    entry = next((f for f in replay_manifest(store).get("files") or []
                  if Path(f["file"]).stem == match), None)
    wrapped = {sid: d["match"]["matchInfo"]["matchId"]
               for sid, d in riot_records(Path(store)).items()}
    res = wrap_record(raw_p.read_bytes(), json.loads(prov_p.read_text(encoding="utf-8")),
                      match, session, man["source"]["path"],
                      (entry or {}).get("capture_session"), wrapped)
    if "refused" in res:
        return {"match": match, **res}
    out = {"match": match, "session": session, "path": str(out_p), "written": False,
           "probe": res["record"]["probe"]}
    if write:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("x", encoding="utf-8") as f:
            json.dump(res["record"], f)
        out["written"] = True
    return out


# ----------------------------------------------------------------- step 6

def deaths_path(sid: str, root=DEFAULT_STORE) -> Path:
    return Path(root) / "events" / "death" / f"{sid}.jsonl"


# ----------------------------------------------------------------- the hook

def run(sid: str, root=DEFAULT_STORE, demos: Path | None = DEMOS_DIR) -> list[dict]:
    """The six steps for one capture session, in order; each row is
    `{"step", ...}` with `done`, `already` or `refused`. A refusal stops the
    steps that need it; a missing Riot record does not stop the layer."""
    from .store import Store

    man = Store(root).read_manifest(sid)
    out: list[dict] = []
    entry = next((f for f in replay_manifest(root).get("files") or []
                  if f.get("capture_session") == sid), None)
    if entry is not None:
        out.append({"step": "find", "already": entry["file"]})
        file = entry["file"]
        src = (Path(demos) / file) if demos and (Path(demos) / file).is_file() \
            else replays_dir(root) / file
        found = {"file": file, "path": str(src)}
    else:
        found = find_replay(man, root, demos)
        if "refused" in found:
            return out + [{"step": "find", "refused": found["refused"]}]
        out.append({"step": "find", "done": found["file"], "overlap_ms": found["overlap_ms"],
                    "basis": found["span"]["basis"]})
        file = found["file"]
    src = Path(found["path"])
    if not src.is_file():
        return out + [{"step": "keep", "refused": f"replay_file_missing:{file}"}]
    k = keep(src, root)
    if "refused" in k:
        return out + [{"step": "keep", **k}]
    out.append({"step": "keep", ("done" if k["kept"] == "copied" else "already"): file})
    span = _span_memo(replays_dir(root) / file)
    st = (replays_dir(root) / file).stat()
    ln = link_manifest(file, sid, man["source"]["path"], root, size=st.st_size,
                       sha256=k["sha256"], span=span,
                       source_mtime_ms=src.stat().st_mtime * 1000.0)
    if "refused" in ln:
        return out + [{"step": "link", **ln}]
    out.append({"step": "link", ("done" if ln["linked"] == "written" else "already"): sid})
    match = Path(file).stem
    if is_parsed(match, root):
        out.append({"step": "parse", "already": match})
    else:
        prov = parse_replay(replays_dir(root) / file, root=root)
        bad = {n: s["exit"] for n, s in prov["steps"].items() if s["exit"]}
        if bad or not is_parsed(match, root):
            return out + [{"step": "parse", "refused": f"vrfkit_failed:{bad}"}]
        out.append({"step": "parse", "done": match})
    if riot_wrapped_path(match, root).is_file():
        out.append({"step": "wrap", "already": match})
    else:
        w = wrap_riot(match, sid, write=True, store=root)
        if w.get("refused") == "no_fetched_record":
            out.append({"step": "wrap", "refused": FETCH_NEEDED})
        elif "refused" in w:
            out.append({"step": "wrap", "refused": w["refused"]})
        else:
            out.append({"step": "wrap", "done": match})
    if not deaths_path(sid, root).is_file():
        return out + [{"step": "replay_layer", "refused":
                       "no_stored_deaths: the layer's clock is fitted on them; run "
                       f"`reticle plan {sid}`'s deaths first"}]
    from . import episodes as ep
    from . import replay_layer as rl
    if rl.status(match, root)["state"] == "current":
        out.append({"step": "replay_layer", "already": match})
    else:
        h = rl.build(match, root)
        if "refused" in h:
            return out + [{"step": "replay_layer", "refused": h["refused"]}]
        out.append({"step": "replay_layer", "done": match})
    if ep.status(match, root)["state"] == "current":
        out.append({"step": "episodes", "already": match})
    else:
        ep.build(match, root)
        out.append({"step": "episodes", "done": match})
    return out


def missing_steps(sid: str, manifest: dict, root=DEFAULT_STORE,
                  demos: Path | None = DEMOS_DIR) -> list[dict]:
    """What of steps 1-5 a session lacks, for `plan`: `[{"step", "why",
    "how", "command"}]`. Steps 6 are `replay_layer` and `episodes`'s own
    plan entries. A session no kept or downloaded replay overlaps lacks
    nothing here."""
    cmd = f"reticle replay-keep {sid}"
    entry = next((f for f in replay_manifest(root).get("files") or []
                  if f.get("capture_session") == sid), None)
    if entry is None:
        found = find_replay(manifest, root, demos)
        if "refused" in found:
            if found["refused"].startswith("several_replays"):
                return [{"step": "find", "why": found["refused"], "how": "storage",
                         "command": cmd}]
            return []
        kept = (replays_dir(root) / found["file"]).is_file()
        return [{"step": "link" if kept else "keep",
                 "why": f"{found['file']} overlaps the capture by {found['overlap_ms']} ms "
                        f"and is {'kept but unlinked' if kept else 'not kept'}",
                 "how": "storage", "command": cmd}]
    match = Path(entry["file"]).stem
    out = []
    if not is_parsed(match, root):
        out.append({"step": "parse", "why": "unparsed", "how": "storage", "command": cmd})
    if not riot_wrapped_path(match, root).is_file():
        if riot_raw_path(match, root).is_file():
            out.append({"step": "wrap", "why": "fetched, unwrapped", "how": "storage",
                        "command": cmd})
        else:
            out.append({"step": "wrap", "why": "no fetched Riot record", "how": "player",
                        "command": f"the player's fetch kit (docs/MATCH_FETCH_KIT.md), then {cmd}"})
    return out


def command(sid: str, root=DEFAULT_STORE, demos: Path | None = DEMOS_DIR) -> int:
    """`reticle replay-keep SESSION`: print each step; exit 1 on a refusal
    other than a missing Riot record."""
    rows = run(sid, root, demos)
    rc = 0
    for r in rows:
        state = next(k for k in ("done", "already", "refused") if k in r)
        extra = "  ".join(f"{k} {v}" for k, v in r.items() if k not in ("step", state))
        print(f"{r['step']:<13} {state:<8} {r[state]}" + (f"  {extra}" if extra else ""))
        if state == "refused" and not (r["step"] == "wrap" and r[state] == FETCH_NEEDED):
            rc = 1
    return rc
