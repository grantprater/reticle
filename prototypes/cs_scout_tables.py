r"""Recompute the Counter-Strike scout's quoted numbers from the stored tables and record them.

    .\.venv\Scripts\python.exe prototypes\cs_scout_tables.py [--record]

Reads only files already in the store's external/cs/ (it downloads nothing):

* kaggle_mm_mirror/kills.parquet and meta.parquet, the ESEA part of the Kaggle
  "CS:GO Competitive Matchmaking Data" as re-uploaded to the HF mirror, and
  dmg_file_rank.parquet, the per-demo rank summary the scout built from the
  mirror's dmg.parquet;
* esta/sample_online_1.json.xz, one ESTA demo, when present. The scout recorded
  its sizes once and then deleted it, so a rerun without it skips that series.

`--record` appends one row per series to the store's notes/metrics.jsonl:
`cs_scout/esea` and `cs_scout/esea_ranks` from the tables, `cs_scout/esta_demo`
from the sample. docs/CS_TRANSFER_SAMPLE.md cites them.

Definitions, kept as the scout first measured them:

* a kill row's state is (ct_alive, t_alive) after the kill; win probability by
  state is the CT share of the rounds' winners over kill rows in that state;
* a round's first kill is its earliest kill row by tick; "the side left with
  five" is the side that did not lose a player;
* a refrag is a next kill in the same round whose victim is on the side of the
  previous kill's attacker; no player ids, so it is not a true trade.

Wire: no (notes/predictions.jsonl, task cs-scout-20261004). It measures external
data for a plan; nothing in reticle/ reads it.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import lzma
import os
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import metrics  # noqa: E402

VERSION = "cs-scout-tables-0.1.0"
STORE = metrics.STORE
CS = STORE / "external" / "cs"
MIRROR = CS / "kaggle_mm_mirror"
ESTA = CS / "esta" / "sample_online_1.json.xz"
STATES = ((4, 4), (2, 2), (1, 1))


def _below_normal() -> None:
    if os.name == "nt":
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)


def esea() -> dict:
    """Coverage, first-kill conversion, coarse win probability and refrags."""
    kills = pq.read_table(MIRROR / "kills.parquet")
    meta = pq.read_table(MIRROR / "meta.parquet")
    ca, ta = kills["ct_alive"].to_numpy(), kills["t_alive"].to_numpy()
    out = {
        "kills_parquet_bytes": (MIRROR / "kills.parquet").stat().st_size,
        "meta_parquet_bytes": (MIRROR / "meta.parquet").stat().st_size,
        "rounds": meta.num_rows,
        "demos": len(pc.unique(meta["file"])),
        "kill_rows": kills.num_rows,
        "negative_alive_rows": int(((ca < 0) | (ta < 0)).sum()),
    }
    kj = kills.join(meta.select(["file", "round", "winner_side"]),
                    keys=["file", "round"], join_type="inner")
    out["joined_kill_rows"] = kj.num_rows
    out["join_share"] = round(kj.num_rows / kills.num_rows, 6)
    kj = kj.sort_by([("file", "ascending"), ("round", "ascending"), ("tick", "ascending")])

    f = kj["file"].to_numpy(zero_copy_only=False)
    r = kj["round"].to_numpy()
    ct_win = kj["winner_side"].to_numpy(zero_copy_only=False) == "CounterTerrorist"
    planted = kj["is_bomb_planted"].to_numpy(zero_copy_only=False).astype(bool)
    ca, ta = kj["ct_alive"].to_numpy(), kj["t_alive"].to_numpy()
    first = np.ones(len(r), bool)
    first[1:] = (f[1:] != f[:-1]) | (r[1:] != r[:-1])

    m = first & ~planted
    side5_win = np.where(ta[m] < ca[m], ct_win[m], ~ct_win[m])
    out["first_kill_rounds"] = int(m.sum())
    out["first_kill_side5_win"] = round(float(side5_win.mean()), 6)

    for ct, t in STATES:
        for pl, tag in ((False, "noplant"), (True, "plant")):
            s = (ca == ct) & (ta == t) & (planted == pl)
            out[f"ct_win_{ct}v{t}_{tag}"] = (round(float(ct_win[s].mean()), 6)
                                             if s.any() else None)
            out[f"n_{ct}v{t}_{tag}"] = int(s.sum())

    # Refrags over all kill rows, joined or not, as the scout measured them.
    k = kills.sort_by([("file", "ascending"), ("round", "ascending"), ("tick", "ascending")])
    f = k["file"].to_numpy(zero_copy_only=False)
    r = k["round"].to_numpy()
    sec = k["seconds"].to_numpy()
    vic_ct = k["vic_side"].to_numpy(zero_copy_only=False) == "CounterTerrorist"
    att_ct = k["att_side"].to_numpy(zero_copy_only=False) == "CounterTerrorist"
    same = (f[1:] == f[:-1]) & (r[1:] == r[:-1])
    dt = sec[1:] - sec[:-1]
    refrag = same & (vic_ct[1:] == att_ct[:-1])
    out["next_kill_pairs"] = int(same.sum())
    out["refrag_share"] = round(float(refrag.sum() / same.sum()), 6)
    out["refrag_5s_share"] = round(float((refrag & (dt <= 5)).sum() / same.sum()), 6)
    out["refrag_gap_median_s"] = round(float(np.nanmedian(dt[refrag])), 6)
    out["kill_rows_without_seconds"] = int(np.isnan(sec).sum())
    return out


def esea_ranks() -> dict:
    """Whether the mirror carries any skill level."""
    rank = pq.read_table(MIRROR / "dmg_file_rank.parquet")
    return {
        "demos": rank.num_rows,
        "att_rank_max": float(pc.max(rank["att_rank_max"]).as_py()),
        "vic_rank_mean_max": float(pc.max(rank["vic_rank_mean"]).as_py()),
    }


def esta_demo() -> dict | None:
    """Sizes and shape of the one ESTA demo, if it is still on disk."""
    if not ESTA.exists():
        return None
    raw = lzma.open(ESTA).read()
    d = json.loads(raw)
    rounds = d["gameRounds"]
    return {
        "xz_bytes": ESTA.stat().st_size,
        "json_bytes": len(raw),
        "rounds": len(rounds),
        "frames_round1": len(rounds[0]["frames"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="append metrics rows")
    args = ap.parse_args()
    _below_normal()
    deps = {"version": VERSION, "pyarrow": pa.__version__}
    series = [("esea", esea(), {"source": "HF mirror HeadShottt/CS-GO kills+meta"}),
              ("esea_ranks", esea_ranks(), {"source": "dmg.parquet per-demo rank summary"})]
    e = esta_demo()
    if e is None:
        print("esta sample absent; cs_scout/esta_demo not recomputed")
    else:
        series.append(("esta_demo", e, {"source": "ESTA online demo 1 of the sample"}))
    for part, values, ctx in series:
        print(part, json.dumps(values))
        if args.record:
            metrics.record("cs_scout", part=part, values=values, deps=deps, context=ctx,
                           note="cs-scout-20261004; prototypes/cs_scout_tables.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
