r"""Thin each stored ability-tray crop file to the 2 Hz grid its readers read,
checked before it replaces anything.

    .\.venv\Scripts\python.exe prototypes\tray_thin.py migrate --out DIR [--replace] [--keep] [--record] [SID ...]
    .\.venv\Scripts\python.exe prototypes\tray_thin.py project [--record]

The player said go (2026-10-05) to thinning the tray crops: the profile ROI
`hud_abilities`, the second rectangle of the `minimap` crop set, its own
FFV1 file (`*.r1.mkv`), written at the minimap rate. Every tray reader in
`reticle/` reads a 0.5 s grid of the cached times on each round span
(`roi_cache.grid_keep`; `reticle tray`, `tray-kit`, `menu` and
`ability-state`), so new captures write the tray on that grid alone
(`roi_cache.GRID_ROIS`, `RoiCacheWriter`), and this script brings the stored
files to it. The minimap rectangle is untouched.

**migrate**, per session, one at a time: a cache written over the whole
capture (a demo) is kept (`whole_capture`); a session whose cache files
another process holds open, or that another job is rewriting (a `.part` or
`.pre-thin` file beside it, or a file that changes during the check), is
refused as `busy`, never failed. Otherwise `roi_cache.grid_thin_rect`
re-encodes the tray file to the grid into `DIR/<sid>/` (no capture decoded),
and the copy must pass every check: each kept frame reads back bit for bit
(`compare_thinned`), the minimap rows are unchanged, `RoiCache` serves the
copy beside the stored files (`with_index`) holding the same times, a
dropped time asked for the tray refuses as `thinned_out` and a grid time
yields the stored pixels; and every tray reader run on the full and on the
thinned cache writes identical rows in every tray stream (`STREAMS`), timing
fields aside (`TIMING`). The readers run in memory: their writes are caught
(`CaptureStore`), never stored. With `--replace` a checked copy replaces the
stored tray file, index and record (the stored ones moved aside first, and
put back if the swapped cache does not load as thinned). Without it the
copy is removed unless `--keep`. `--record` writes a ledger row per session
and one for the run (`tray_thin/migrate-check` or `tray_thin/migrate`).
Run it from the main worktree, with `DIR` on the store's drive, so a swap is
a rename.

**project** reads only file sizes and indexes: the stored tray bytes and
frames over every session with a tray file, the grid share of each, and the
bytes a grid file would take at the same bytes a frame.

Owns nothing: a one-time migration. Wire: no (a migration of stored caches;
new captures thin in `roi_cache.RoiCacheWriter`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOOL_VERSION = "tray-thin-0.1.0"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
ROI = "hud_abilities"
SET = "minimap"
#: The tray streams the readers write, compared row for row.
STREAMS = ("tray_drop", "tray_countdown", "tray_kit", "tray_kit_identity", "menu_open",
           "ability_state")
#: Wall-clock fields a reader stores under `checks`; they never compare.
TIMING = ("cache_read_s", "wall_s")
#: Every this many grid times one is asked of both caches through `samples`.
SEEK_EVERY = 25
#: Free bytes the out directory's drive keeps through a thinning.
MIN_FREE = 10e9


def cache_root(store: Path = STORE) -> Path:
    from reticle.roi_cache import cache_dir
    return cache_dir(store, SET)


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


def open_elsewhere(path: Path) -> bool:
    """Whether another handle holds `path` open: on Windows an open asking
    no sharing fails with a sharing violation then. Never on other systems."""
    if os.name != "nt" or not Path(path).is_file():
        return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    h = k32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)   # GENERIC_READ, OPEN_EXISTING
    if h == wintypes.HANDLE(-1).value or h is None:
        return ctypes.get_last_error() in (32, 33)                     # sharing, lock violation
    k32.CloseHandle(h)
    return False


def cache_files(sid: str, cache: Path) -> list[Path]:
    return [cache / f"{sid}.json", cache / f"{sid}.idx.npy", cache / f"{sid}.r0.mkv",
            cache / f"{sid}.r1.mkv"]


def busy(sid: str, cache: Path) -> str | None:
    """Why the session's cache may not be thinned now, or None: a file being
    written beside it (`.part`, `.pre-thin`) or a file another process holds."""
    for p in sorted(cache.glob(f"{sid}.*")):
        if ".part" in p.name or p.name.endswith(".pre-thin"):
            return f"{p.name} lies beside the cache: another job is rewriting it"
    for p in cache_files(sid, cache):
        if open_elsewhere(p):
            return f"{p.name} is open in another process"
    return None


def snapshot(sid: str, cache: Path) -> dict:
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) if p.is_file() else None
            for p in cache_files(sid, cache)}


class CaptureStore:
    """The store as a reader sees it, its event writes caught in `rows`: a
    stream caught in this run reads back as caught, so a later reader takes
    the earlier one's new rows, as a rerun in order would; every other read
    goes to the store, and any other write raises."""

    def __init__(self, root: Path):
        from reticle.store import Store
        self._store = Store(root)
        self.root = self._store.root
        self.rows: dict[str, list[dict]] = {}

    def write_events(self, kind: str, session_id: str, rows: list[dict]) -> Path:
        self.rows[kind] = json.loads(json.dumps(rows, default=str))
        return Path(f"<caught {kind}>")

    def read_events(self, kind: str, session_id: str) -> list[dict]:
        if kind in self.rows:
            return json.loads(json.dumps(self.rows[kind]))
        return self._store.read_events(kind, session_id)

    def read_events_kind(self, kind: str, session_id: str, row_kind: str) -> list[dict]:
        if kind in self.rows:
            rows = self.read_events(kind, session_id)
            return rows[:1] + [r for r in rows[1:] if r.get("kind") == row_kind]
        return self._store.read_events_kind(kind, session_id, row_kind)

    def __getattr__(self, name):
        if name.startswith("write") or name in ("commit_staged", "staging"):
            raise RuntimeError(f"a tray reader called Store.{name}; the check writes nothing")
        return getattr(self._store, name)


def run_readers(sid: str, cache, store_root: Path = STORE) -> dict:
    """Each tray reader run on `cache` as the session's minimap cache, at
    its defaults, in the order each reads the one before: `reticle menu`,
    `tray-kit`, `tray` (whose gate reads both) and `ability-state` (which
    reads the new `tray_drop`). The rows each would write, per stream, and
    what it printed. Writes nothing."""
    from reticle import cli
    from reticle.roi_cache import RoiCache
    real_load = RoiCache.load
    cap = CaptureStore(store_root)

    def load(root, manifest, profile, name="killfeed", raw=False):
        if name == SET and manifest.get("session_id") == sid and not raw:
            return cache, None
        return real_load(root, manifest, profile, name, raw)

    out = io.StringIO()
    base = dict(store=str(store_root), session=sid, all=False, record=False)
    with mock.patch.object(cli, "Store", lambda root: cap), \
            mock.patch.object(RoiCache, "load", load), contextlib.redirect_stdout(out):
        cli.cmd_menu(SimpleNamespace(**base, step=0.5))
        cli.cmd_tray_kit(SimpleNamespace(**base, step=0.5, at=[]))
        cli.cmd_tray(SimpleNamespace(**base, step=0.5))
        cli.cmd_ability_state(SimpleNamespace(**base))
    return {"rows": {s: cap.rows.get(s) for s in STREAMS}, "printed": out.getvalue()}


def _drop_timing(row):
    if isinstance(row, dict):
        return {k: (_drop_timing(v) if k != "checks" else
                    {a: b for a, b in v.items() if a not in TIMING} if isinstance(v, dict) else v)
                for k, v in row.items()}
    return row


def compare_stream_rows(base: list[dict] | None, got: list[dict] | None) -> dict:
    """Rows of one stream from two runs: how many each wrote and how many
    differ, position by position, timing fields aside."""
    base, got = base or [], got or []
    key = lambda r: json.dumps(_drop_timing(r), sort_keys=True, default=str)
    differ = sum(key(a) != key(b) for a, b in zip(base, got)) + abs(len(base) - len(got))
    ex = next(([key(a)[:300], key(b)[:300]] for a, b in zip(base, got) if key(a) != key(b)), None)
    return {"rows_full": len(base), "rows_thinned": len(got), "differ": int(differ),
            "example": ex}


def stored_compare(sid: str, rows: dict, store_root: Path = STORE) -> dict:
    """Whether the full-cache rerun reproduces the stored rows, per stream:
    context for the check (a stale stream differs here on both caches)."""
    from reticle.store import Store
    st = Store(store_root)
    return {s: (compare_stream_rows(st.read_events(s, sid), r)["differ"] if r is not None else None)
            for s, r in rows.items()}


def load_checks(full, thin, roi: str = ROI) -> dict:
    """The thinned copy read through `RoiCache` beside the full cache: the
    same times held, every dropped time refused `thinned_out` for the tray
    (and by `samples`), every kept time held, and every `SEEK_EVERY`th grid
    time read as the full cache's pixels."""
    from reticle.roi_cache import CACHE_SETS, ThinnedOut
    k = CACHE_SETS[full.record["roi"]].index(roi)
    held = full.holds()
    grid = sorted(float(t) for t in thin.t_ms[thin.rect == k])
    dropped = sorted(set(held) - set(grid))
    ref_drop = {}
    for t in dropped:
        why = thin.refusal(t, [roi])
        ref_drop[why] = ref_drop.get(why, 0) + 1
    ref_kept = {}
    for t in grid:
        why = thin.refusal(t, [roi])
        ref_kept[str(why)] = ref_kept.get(str(why), 0) + 1
    raised = 0
    for t in dropped[:: max(1, len(dropped) // 20)]:
        try:
            list(thin.samples([t], rois=[roi]))
        except ThinnedOut:
            raised += 1
    asked = grid[::SEEK_EVERY]
    same = sum(np.array_equal(a.frame, b.frame) and a.frame_idx == b.frame_idx
               for a, b in zip(thin.samples(asked, rois=[roi]), full.samples(asked, rois=[roi])))
    out = {"held_same": thin.holds() == held, "grid": len(grid), "dropped": len(dropped),
           "refusal_dropped": ref_drop, "refusal_kept": ref_kept,
           "raised": raised, "raise_asked": len(dropped[:: max(1, len(dropped) // 20)]),
           "seek_asked": len(asked), "seek_same": int(same)}
    out["ok"] = (out["held_same"] and ref_drop == ({"thinned_out": len(dropped)} if dropped else {})
                 and ref_kept == {"None": len(grid)} and raised == out["raise_asked"]
                 and same == len(asked))
    return out


def _swap_in(sid: str, cache: Path, work: Path) -> list[tuple[Path, Path]]:
    """Move the stored tray file, index and record aside (`.pre-thin`) and
    the thinned ones in; returns (stored, aside) pairs for `_restore`."""
    names = [f"{sid}.json", f"{sid}.idx.npy", f"{sid}.r1.mkv"]
    aside, moved = [], []
    try:
        for n in names:
            if (cache / n).is_file():
                os.replace(cache / n, cache / f"{n}.pre-thin")
                aside.append((cache / n, cache / f"{n}.pre-thin"))
        for n in names:
            os.replace(work / n, cache / n)
            moved.append(n)
    except OSError:
        # A file another process holds will not move: put back what did.
        for n in moved:
            os.replace(cache / n, work / n)
        _restore(aside)
        raise
    return aside


def _restore(aside: list[tuple[Path, Path]]) -> None:
    for path, back in aside:
        os.replace(back, path)


def decide(bits: dict, frames_kept: int, r0_same: bool, load: dict, readers: dict) -> list[str]:
    """The checks that failed; empty where the copy may replace the stored file."""
    failed = []
    if not (bits["index_ok"] and not bits["extra_frames"] and bits["different"] == 0
            and bits["identical"] == bits["checked"] == frames_kept):
        failed.append("bits")
    if not r0_same:
        failed.append("minimap_rows")
    if not load.get("ok"):
        failed.append("load")
    if any(c["differ"] for c in readers.values()):
        failed.append("readers")
    return failed


def migrate_session(sid: str, out: Path, replace: bool = False, keep: bool = False,
                    store_root: Path = STORE, readers=run_readers) -> dict:
    """Thin one session's tray file into `out/<sid>/`, check it, and with
    `replace` put it in place of the stored one (see the module docstring).
    `readers` runs the tray readers on a cache (`run_readers`)."""
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache, compare_thinned, grid_thin_rect, stored_record
    from reticle.store import Store
    cache = cache_root(store_root)
    res = {"sid": sid, "replaced": False}
    rec = stored_record(store_root, sid, SET)
    if rec is None or not (cache / f"{sid}.r1.mkv").is_file():
        return {**res, "status": "no_tray_file"}
    res["bytes_before"] = int((cache / f"{sid}.r1.mkv").stat().st_size)
    if not rec.get("spans"):
        return {**res, "status": "whole_capture"}
    if (rec.get("thinned_rois") or {}).get(ROI) is not None:
        return {**res, "status": "already_thinned"}
    why = busy(sid, cache)
    if why is not None:
        return {**res, "status": "busy", "why": why}
    work = Path(out) / sid
    if shutil.disk_usage(Path(out).anchor or ".").free - res["bytes_before"] < MIN_FREE:
        return {**res, "status": "failed", "failed": "disk"}
    before = snapshot(sid, cache)
    swapped = False
    try:
        res.update(grid_thin_rect(cache, sid, ROI, work, f"{TOOL_VERSION} migrate"))
        res["bits"] = compare_thinned(cache, work, sid, rect=res["rect"])
        old, new = np.load(cache / f"{sid}.idx.npy"), np.load(work / f"{sid}.idx.npy")
        k = res["rect"]
        r0_same = bool(np.array_equal(old[old[:, 2] != k], new[new[:, 2] != k]))
        man = Store(store_root).read_manifest(sid)
        prof = get_profile(man["source_profile"])
        full, why = RoiCache.load(store_root, man, prof, SET)
        if full is None:
            return {**res, "status": "failed", "failed": "load", "why": why}
        thin = full.with_index(new, json.loads((work / f"{sid}.json").read_text(encoding="utf-8")),
                               {res["rect"]: work / f"{sid}.r{res['rect']}.mkv"})
        res["load"] = load_checks(full, thin)
        t0 = time.time()
        base = readers(sid, full)
        got = readers(sid, thin)
        res["readers_s"] = round(time.time() - t0, 1)
        res["readers"] = {s: compare_stream_rows(base["rows"].get(s), got["rows"].get(s))
                          for s in STREAMS}
        res["full_vs_stored_differ"] = stored_compare(sid, base["rows"], store_root)
        res["printed_full"] = base["printed"][-2000:]
        if snapshot(sid, cache) != before:
            return {**res, "status": "busy", "why": "the stored cache files changed during the check"}
        failed = decide(res["bits"], res["frames_kept"], r0_same, res["load"], res["readers"])
        if failed:
            return {**res, "status": "failed", "failed": ",".join(failed)}
        # A reader holding a file open does not change what the check read,
        # but a swap must not move a file from under it.
        res["open_at_end"] = busy(sid, cache)
        if not replace:
            return {**res, "status": "checked"}
        if res["open_at_end"] is not None:
            return {**res, "status": "busy", "why": res["open_at_end"]}
        try:
            aside = _swap_in(sid, cache, work)
        except OSError as e:
            return {**res, "status": "busy", "why": f"the swap could not move a file: {e}"}
        swapped = True
        try:
            got_cache, why = RoiCache.load(store_root, man, prof, SET)
            if (got_cache is None or got_cache.thinned(ROI) is None
                    or got_cache.holds() != full.holds()):
                raise RuntimeError(f"the swapped cache does not load as thinned: {why}")
        except Exception:
            for n in (f"{sid}.json", f"{sid}.idx.npy", f"{sid}.r1.mkv"):
                if (cache / n).is_file():
                    os.replace(cache / n, work / n)
            _restore(aside)
            swapped = False
            raise
        for _path, back in aside:
            back.unlink()
        res["replaced"] = True
        return {**res, "status": "replaced"}
    finally:
        if not keep and not swapped and work.is_dir():
            shutil.rmtree(work, ignore_errors=True)


def cmd_migrate(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from reticle.roi_cache import GRID_THIN_VERSION
    sids = args.sessions or sorted(p.name.split(".")[0] for p in cache_root().glob("*.r1.mkv"))
    rows = []
    for sid in sids:
        t0 = time.time()
        r = migrate_session(sid, out, args.replace, args.keep)
        r["seconds"] = round(time.time() - t0, 1)
        rows.append(r)
        (out / f"{sid}.tray_thin.json").write_text(json.dumps(r, indent=1, default=str),
                                                   encoding="utf-8")
        print(json.dumps({k: r.get(k) for k in ("sid", "status", "failed", "why", "frames_before",
                                                "frames_kept", "bytes_before", "bytes_after",
                                                "seconds")}), flush=True)
        if args.record and r["status"] not in ("no_tray_file", "whole_capture"):
            from reticle import metrics
            rd = r.get("readers") or {}
            metrics.record("tray_thin", part="migrate" if args.replace else "migrate-check",
                           session=sid,
                           deps={"tool": TOOL_VERSION, "grid": GRID_THIN_VERSION,
                                 "procedure": "roi_cache.grid_thin_rect, FFV1 level 3 bgr0"},
                           context={"status": r["status"], "failed": r.get("failed"),
                                    "why": r.get("why"),
                                    "bits": r.get("bits"),
                                    "load": {k: v for k, v in (r.get("load") or {}).items()
                                             if k != "ok"},
                                    "full_vs_stored_differ": r.get("full_vs_stored_differ"),
                                    "examples": {s: c.get("example") for s, c in rd.items()
                                                 if c.get("differ")}},
                           values={"frames_before": r.get("frames_before") or 0,
                                   "frames_kept": r.get("frames_kept") or 0,
                                   "bytes_before": r.get("bytes_before") or 0,
                                   "bytes_after": r.get("bytes_after") or 0,
                                   "seconds": r["seconds"],
                                   "replaced": int(bool(r.get("replaced"))),
                                   **{f"{s}__rows": c["rows_full"] for s, c in rd.items()},
                                   **{f"{s}__differ": c["differ"] for s, c in rd.items()},
                                   "rows_compared": sum(c["rows_full"] for c in rd.values()),
                                   "rows_differ": sum(c["differ"] for c in rd.values())})
    done = [r for r in rows if r.get("replaced")]
    passed = [r for r in rows if r["status"] in ("checked", "replaced")]
    total = {"sessions": len(rows), "passed": len(passed), "replaced": len(done),
             "failed": sum(r["status"] == "failed" for r in rows),
             "busy": sum(r["status"] == "busy" for r in rows),
             "kept_whole_capture": sum(r["status"] == "whole_capture" for r in rows),
             "bytes_freed": sum(r["bytes_before"] - r.get("bytes_after", 0) for r in done),
             "bytes_freed_if_passed_replaced": sum(r["bytes_before"] - r.get("bytes_after", 0)
                                                   for r in passed),
             "rows_compared": sum(sum(c["rows_full"] for c in (r.get("readers") or {}).values())
                                  for r in rows),
             "rows_differ": sum(sum(c["differ"] for c in (r.get("readers") or {}).values())
                                for r in rows)}
    print(json.dumps(total))
    if args.record and passed:
        from reticle import metrics
        metrics.record("tray_thin", part="migrate" if args.replace else "migrate-check",
                       session=f"sample-{len(rows)}" if args.sessions else f"corpus-{len(rows)}",
                       deps={"tool": TOOL_VERSION, "grid": GRID_THIN_VERSION},
                       values={**total, "gb_freed": round(total["bytes_freed"] / 1e9, 3)},
                       context={"sessions": [r["sid"] for r in rows],
                                "failed_sessions": [r["sid"] for r in rows
                                                    if r["status"] == "failed"]})
    return 0


def project(store_root: Path = STORE) -> dict:
    """Per session with a tray file: its bytes and frames, the frames on the
    readers' grid (`grid_keep`; a whole-capture cache keeps all), and the
    bytes the grid would take at the file's mean bytes a frame."""
    from reticle.roi_cache import GRID_ROIS, grid_keep
    cache = cache_root(store_root)
    step = GRID_ROIS[SET][ROI]
    per = {}
    for p in sorted(cache.glob("*.r1.mkv")):
        sid = p.name.split(".")[0]
        rec = json.loads((cache / f"{sid}.json").read_text(encoding="utf-8"))
        idx = np.load(cache / f"{sid}.idx.npy")
        if idx.shape[1] == 4:
            continue
        n = int((idx[:, 2] == 1).sum())
        size = int(p.stat().st_size)
        if rec.get("thinned_rois", {}).get(ROI) is not None or not rec.get("spans"):
            kept = n
        else:
            kept = len(grid_keep(idx[:, 0], rec["spans"], step))
        per[sid] = {"spans": bool(rec.get("spans")), "frames": n, "grid": kept, "bytes": size,
                    "bytes_grid": int(round(size * kept / max(n, 1)))}
    rs = [v for v in per.values() if v["spans"]]
    return {"per": per, "sessions": len(per), "round_span_sessions": len(rs),
            "bytes_all": sum(v["bytes"] for v in per.values()),
            "bytes_round": sum(v["bytes"] for v in rs),
            "bytes_round_grid": sum(v["bytes_grid"] for v in rs),
            "frames_round": sum(v["frames"] for v in rs),
            "grid_round": sum(v["grid"] for v in rs)}


def cmd_projection(args) -> int:
    p = project()
    p["bytes_freed"] = p["bytes_round"] - p["bytes_round_grid"]
    print(json.dumps({k: v for k, v in p.items() if k != "per"}, indent=1))
    if args.record:
        from reticle import metrics
        from reticle.roi_cache import GRID_THIN_VERSION
        metrics.record("tray_thin", part="projection", session=f"corpus-{p['sessions']}",
                       deps={"tool": TOOL_VERSION, "grid": GRID_THIN_VERSION},
                       values={k: v for k, v in p.items() if k != "per"}
                       | {"gb_freed": round(p["bytes_freed"] / 1e9, 3),
                          "gb_round": round(p["bytes_round"] / 1e9, 3)},
                       context={"per": p["per"],
                                "rule": "bytes a grid file takes = the file's bytes x grid "
                                        "frames / frames; whole-capture caches keep every frame"})
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--out", required=True,
                   help="where each thinned copy and check result goes (the store's drive)")
    m.add_argument("--replace", action="store_true",
                   help="put each checked copy in place of the stored tray file")
    m.add_argument("--keep", action="store_true", help="keep each checked copy in --out")
    m.add_argument("--record", action="store_true")
    m.add_argument("sessions", nargs="*")
    j = sub.add_parser("project")
    j.add_argument("--record", action="store_true")
    args = p.parse_args(argv)
    below_normal()
    return {"migrate": cmd_migrate, "project": cmd_projection}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
