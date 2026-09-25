r"""Time a killfeed-reader recheck three ways on one full session.

    .\.venv\Scripts\python.exe prototypes\scan_tiers.py a06f04a0059f

Columns: (1) today, `scan --only hud --force`: the whole HUD pass and the
killfeed reader over one sequential decode; (2) `plan`, then `trial --from
video`: the killfeed reader alone, seeking to stored occupied windows; (3)
`plan`, then `trial --from cache`: the same frames from the ROI crop cache,
no decode. Also timed: building the cache (`scan --only roi_cache`), a one-off
per session, and a cache trial over the whole timeline. Column 1 rewrites the
stored HUD streams, so their hashes are compared before and after: a rewrite
that changed evidence fails the run. Predictions are `scan-tiers` in the
store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import metrics  # noqa: E402
from reticle.store import Store  # noqa: E402

PY = str(Path(sys.executable))


def _run(*argv: str) -> tuple[float, str, int]:
    t0 = time.perf_counter()
    p = subprocess.run([PY, "-m", "reticle", *argv], capture_output=True, text=True)
    return time.perf_counter() - t0, p.stdout + p.stderr, p.returncode


def _hashes(store: Store, sid: str) -> dict[str, str]:
    man = store.read_manifest(sid)
    paths = {"hud": store.hud_path(sid, man["ingested_at"][:10]),
             "killfeed_portrait": store.events_path("killfeed_portrait", sid),
             "killfeed_weapon": store.events_path("killfeed_weapon", sid)}
    out = {}
    for k, p in paths.items():
        if k == "hud":
            import pyarrow.parquet as pq
            # The parquet file carries a write time; its rows are the evidence.
            t = pq.read_table(p)
            out[k] = hashlib.sha256(json.dumps(t.to_pydict(), sort_keys=True,
                                               default=str).encode()).hexdigest()
        else:
            out[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> None:
    sid = sys.argv[1]
    store = Store()
    res, log = {}, {}
    before = _hashes(store, sid)
    res["current_s"], log["current"], rc = _run("scan", sid, "--only", "hud", "--force")
    if rc:
        raise SystemExit(log["current"])
    after = _hashes(store, sid)
    changed = sorted(k for k in before if before[k] != after[k])
    res["cache_build_s"], log["cache_build"], rc = _run(
        "scan", sid, "--only", "roi_cache", "--cache-roi", "killfeed", "--force")
    if rc:
        raise SystemExit(log["cache_build"])
    res["plan_s"], log["plan"], _ = _run("plan", sid)
    res["windows_video_s"], log["windows_video"], rc_v = _run(
        "trial", sid, "--from", "video", "--windows", "occupied")
    res["windows_cache_s"], log["windows_cache"], rc_c = _run(
        "trial", sid, "--from", "cache", "--windows", "occupied")
    res["all_cache_s"], log["all_cache"], rc_a = _run(
        "trial", sid, "--from", "cache", "--windows", "all")
    for k in list(res):
        res[k] = round(res[k], 1)
    res["tier2_s"] = round(res["plan_s"] + res["windows_video_s"], 1)
    res["tier3_s"] = round(res["plan_s"] + res["windows_cache_s"], 1)
    res["identical_video"] = int(rc_v == 0)
    res["identical_cache"] = int(rc_c == 0)
    res["identical_all_cache"] = int(rc_a == 0)
    res["rewrite_changed_streams"] = len(changed)
    meta = json.loads(next((store.root / "roi_cache" / "killfeed").rglob(f"{sid}.json"))
                      .read_text(encoding="utf-8"))
    res["cache_mb"] = round(meta["bytes"] / 2**20)
    res["cache_frames"] = meta["frames"]
    for k, v in log.items():
        print(f"--- {k}\n{v.strip()}")
    print(json.dumps(res, indent=1))
    metrics.record("scan_tiers", part="killfeed-recheck", session=sid, values=res,
                   deps={"prototype": "scan_tiers-0.1.0"},
                   context={"changed_streams": changed},
                   controls=[{"name": "column 1 rewrite leaves stored streams identical",
                              "observed": len(changed), "expected": 0},
                             {"name": "cache trial over the whole timeline equals storage",
                              "observed": res["identical_all_cache"], "expected": 1}])


if __name__ == "__main__":
    main()
