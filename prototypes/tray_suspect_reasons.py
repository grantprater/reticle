r"""Why `ability_hud` flags most match tray drops suspect, and a death-gated rule.

    .\.venv\Scripts\python.exe prototypes\tray_suspect_reasons.py collect [SID ...]
    .\.venv\Scripts\python.exe prototypes\tray_suspect_reasons.py report
    .\.venv\Scripts\python.exe prototypes\tray_suspect_reasons.py montage OUT.png [N [KIND]]

Purpose. `ability_mined_references.py` found 2121 of 2764 cached tray drops
flagged suspect across the match sessions, which caps every tray-based
ability witness. This tabulates the suspect drops by the reason
`ability_hud` had and by context the tray cannot see: the player's own death
(stored `death` verdicts with `is_player_death`), the round bounds (stored
`l2/rounds`) and the cache span (barrier drop - 1 s to next round start).

Reasons. `ability_hud.casts` marks a drop suspect for one of two causes; the
module stores only the boolean, so the cause is derived here from the owner:
`forced` -- the drop lands on the first refused frame after a drawn one (the
sample at t fails `ability_hud.drawn`); `cooccur` -- `ability_hud.flag_suspect`
over the same drops with `forced` cleared still flags it (another slot dropped
within `SUSPECT_S`).

Rule. The tray shows the player's kit only while the player lives. A drop at
or after the player's first death in that round, less DEATH_LEAD_S, is not
the player's cast. Suspicion is then recomputed by `flag_suspect` over the
surviving drops alone, so a pre-death cast is no longer tainted by the
spectator switch it happened to sit near.

Outcome (2026-09-26, 19 sessions, 2764 drops, 2121 suspect). Reasons:
forced+cooccur 1371, cooccur only 544, forced only 206. By context: 1771
(83%) at or after the player's death -- 580 within 3 s of it (the death
camera blanks the tray, then it returns with a teammate's kit) and 1191
later (spectated kits changing and emptying as teammates die); 138 in the
post-round phase (the tray dims); 7 at the barrier; 205 live and alive.
Of the 643 drops `ability_hud` calls clean, 226 fall after the player's
death: spectated teammates' casts, false as the player's. The death gate
(live phase only) keeps 420 clean casts: 226 false removed, 5 recovered.
232 live, pre-death suspects remain: 85 forced (tray blank while alive) and
147 co-occurring, 124 of them in two-slot clusters; the montage shows a
purple countdown overlay replacing the icons, genuine casts beside an X-pip
jitter, and tray blanks. The pixels do not separate those from genuine
double casts; that needs the player's labels.

Inputs. Tray crops from the 15 Hz `minimap` roi cache at 0.5 s, read by
`ability_hud.slot_counts` unchanged, spans joined by a refused row exactly as
`ability_mined_references.tray_casts_cached` does. No decode; nothing is
written to the store. Work cache: `--work` (system temp by default).
Predictions and outcome: task `tray-suspect-drops` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import glob
import json
import pickle
import sys
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_hud as ah  # noqa: E402
import ability_mined_references as amr  # noqa: E402

STORE = amr.STORE
WORK = Path(tempfile.gettempdir()) / "tray_suspect_reasons"
#: A drop this long before the stored player death already belongs to it:
#: the verdict's time is the killfeed entry, which trails the death screen.
DEATH_LEAD_S = 1.0


def read_tray(cache):
    """(ts, counts, clean, span) at the tray step; a refused row joins spans."""
    ts, rows, clean, span = [], [], [], []
    for si, (a, b) in enumerate(cache.record["spans"]):
        for smp in cache.samples(amr.grid(cache, a, b, amr.TRAY_STEP_S), rois=["hud_abilities"]):
            c, ok = ah.slot_counts(smp.frame)
            ts.append(smp.t_ms / 1000.0)
            rows.append(c)
            clean.append(ok)
            span.append(si)
        ts.append((ts[-1] if ts else 0.0) + 0.01)
        rows.append([0, 0, 0, 0])
        clean.append(False)
        span.append(-1)
    return np.asarray(ts), np.asarray(rows, float), np.asarray(clean, bool), np.asarray(span)


def player_deaths(sid: str) -> list[float]:
    """Stored player death times (s), from death verdicts."""
    out = []
    p = STORE / "events" / "death" / f"{sid}.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("kind") == "death_verdict" and (r.get("metadata") or {}).get("is_player_death"):
            out.append(r["t_ms"] / 1000.0)
    return sorted(out)


def stored_rounds(sid: str) -> list[dict]:
    f = glob.glob(str(STORE / "l2" / "rounds" / "*" / f"session={sid}" / "rounds.parquet"))
    return pq.read_table(f[0]).to_pylist() if f else []


def collect_session(sid: str) -> dict:
    _man, cache = amr.open_cache(sid)
    ts, counts, clean, span = read_tray(cache)
    return {"sid": sid, "ts": ts, "counts": counts, "clean": clean, "span": span,
            "spans": cache.record["spans"], "rounds": stored_rounds(sid)}


def drop_rows(d: dict) -> list[dict]:
    """Every `ability_hud.casts` drop, with its derived reason and context."""
    ts, counts, clean = d["ts"], d["counts"], d["clean"]
    deaths = player_deaths(d["sid"])
    ev = ah.casts(list(ts), counts, clean)
    f = ah.fills(counts, clean)
    idx = {round(float(t), 3): i for i, t in enumerate(ts)}
    forced = [not ah.drawn(f[idx[round(float(t), 3)]]) for t, *_ in ev]
    near = ah.flag_suspect([(t, k, a, b, False) for t, k, a, b, _s in ev])
    out = []
    for (t, k, a, b, sus), fo, (*_x, co) in zip(ev, forced, near):
        i = idx[round(float(t), 3)]
        sa, sb = d["spans"][int(d["span"][i])]
        rnd = next((r for r in d["rounds"] if r["t_start_ms"] <= sa + 1000 < r["t_close_ms"] + 1),
                   None)
        t_end = rnd["t_end_ms"] / 1000.0 if rnd else sb / 1000.0
        dth = [x for x in deaths if sa / 1000.0 <= x <= sb / 1000.0]
        phase = ("barrier" if t < sa / 1000.0 + 1.0 else "live" if t <= t_end else "post_round")
        out.append({"t": float(t), "slot": k, "from": a, "to": b, "suspect": sus,
                    "forced": fo, "cooccur": co, "span": int(d["span"][i]), "phase": phase,
                    "death": dth[0] if dth else None,
                    "rel_death": float(t - dth[0]) if dth else None})
    # Cluster size: slots dropping within SUSPECT_S of each other.
    for r in out:
        r["n_slots"] = len({o["slot"] for o in out if abs(o["t"] - r["t"]) <= ah.SUSPECT_S})
    return out


def after_death(r: dict) -> bool:
    return r["rel_death"] is not None and r["rel_death"] >= -DEATH_LEAD_S


def gated(rows: list[dict], live_only: bool = False) -> list[dict]:
    """Drops before the player's death, suspicion recomputed among them only.

    `live_only` also drops the post-round phase, where the tray dims.
    """
    keep = [r for r in rows if not after_death(r)
            and not (live_only and r["phase"] == "post_round")]
    out = []
    for sid in dict.fromkeys(r.get("sid") for r in keep):
        mine = [r for r in keep if r.get("sid") == sid]
        ev = ah.flag_suspect([(r["t"], r["slot"], r["from"], r["to"], r["forced"]) for r in mine])
        out += [{**r, "suspect_gated": s} for r, (*_x, s) in zip(mine, ev)]
    return out


def kind(r: dict) -> str:
    if r["rel_death"] is not None and abs(r["rel_death"]) <= 3.0:
        return "at_death"
    if after_death(r):
        return "after_death"
    if r["phase"] == "post_round":
        return "post_round_alive"
    if r["phase"] == "barrier":
        return "barrier"
    return "live_alive"


def report(work: Path) -> dict:
    data = [pickle.loads(f.read_bytes()) for f in sorted(work.glob("*.pkl"))]
    rows = [dict(r, sid=d["sid"]) for d in data for r in drop_rows(d)]
    sus = [r for r in rows if r["suspect"]]
    out = {"sessions": len(data), "drops": len(rows), "suspect": len(sus),
           "reason": dict(Counter(("forced" if r["forced"] else "") + ("+cooccur" if r["cooccur"] else "")
                                  for r in sus)),
           "suspect_by_kind": dict(Counter(kind(r) for r in sus)),
           "clean_by_kind": dict(Counter(kind(r) for r in rows if not r["suspect"])),
           "suspect_n_slots": dict(sorted(Counter(r["n_slots"] for r in sus).items())),
           "suspect_to_zero": sum(r["to"] <= 0.05 for r in sus),
           "suspect_after_death": sum(after_death(r) for r in sus),
           "clean_after_death": sum(after_death(r) and not r["suspect"] for r in rows)}
    g = gated(rows)
    before = [r for r in rows if not after_death(r)]
    out["before_death"] = {"drops": len(before), "suspect_now": sum(r["suspect"] for r in before),
                           "suspect_gated": sum(r["suspect_gated"] for r in g)}
    kept = [r for r in g if not r["suspect_gated"]]
    out["rule"] = {"clean_now": len(rows) - len(sus), "clean_gated": len(kept),
                   "recovered": sum(r["suspect"] for r in kept),
                   "removed_false": out["clean_after_death"],
                   "clean_gated_by_slot": dict(Counter(r["slot"] for r in kept)),
                   "gated_suspect_by_reason": dict(Counter(
                       ("forced" if r["forced"] else "cooccur") for r in g if r["suspect_gated"]))}
    g2 = gated(rows, live_only=True)
    kept2 = [r for r in g2 if not r["suspect_gated"]]
    out["rule_live_only"] = {"clean_gated": len(kept2), "recovered": sum(r["suspect"] for r in kept2),
                             "lost_clean_post_round": sum(1 for r in kept if r["phase"] == "post_round")}
    alive = [r for r in g2 if r["suspect_gated"]]
    out["alive_live_suspect"] = {
        "n": len(alive),
        "reason": dict(Counter(("forced" if r["forced"] else "cooccur") for r in alive)),
        "with_ult_in_cluster": sum(any(o["slot"] == "X" and abs(o["t"] - r["t"]) <= ah.SUSPECT_S
                                       for o in alive) for r in alive),
        "n_slots": dict(sorted(Counter(r["n_slots"] for r in alive).items()))}
    rd = [r["rel_death"] for r in sus if r["rel_death"] is not None and abs(r["rel_death"]) <= 10]
    out["suspect_rel_death_hist_s"] = dict(sorted(Counter(int(np.floor(x)) for x in rd).items()))
    return out


def montage(work: Path, out_png: Path, n: int = 4, only: str | None = None) -> None:
    """Tray crops at -1, 0, +1, +3 s around n suspect drops of each kind."""
    data = {f.stem: pickle.loads(f.read_bytes()) for f in sorted(work.glob("*.pkl"))}
    rng = np.random.default_rng(7)
    by = {}
    for sid, d in data.items():
        for r in drop_rows(d):
            if r["suspect"] and (only is None or kind(r) == only):
                by.setdefault(kind(r), []).append((sid, r))
    tiles = []
    for k in sorted(by):
        pick = [by[k][i] for i in rng.choice(len(by[k]), min(n, len(by[k])), replace=False)]
        for sid, r in pick:
            _man, cache = amr.open_cache(sid)
            x0, y0, x1, y1 = cache.rect_of("hud_abilities")
            row = []
            for dt in (-1.0, 0.0, 1.0, 3.0):
                smp = next(iter(cache.samples([(r["t"] + dt) * 1000.0], rois=["hud_abilities"])), None)
                img = (smp.frame[y0:y1, x0:x1] if smp is not None
                       else np.zeros((y1 - y0, x1 - x0, 3), np.uint8))
                row.append(cv2.resize(img, None, fx=0.5, fy=0.5))
            strip = np.hstack(row)
            lab = np.zeros((16, strip.shape[1], 3), np.uint8)
            rel = "-" if r["rel_death"] is None else f"{r['rel_death']:+.1f}"
            cv2.putText(lab, f"{k} {sid} t={r['t']:.1f} {r['slot']} {r['from']}->{r['to']} "
                        f"dth{rel} n{r['n_slots']}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (255, 255, 255), 1)
            tiles.append(np.vstack([lab, strip]))
    cv2.imwrite(str(out_png), np.vstack(tiles))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "report", "montage"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "collect":
        for sid in a.args or amr.session_ids():
            f = a.work / f"{sid}.pkl"
            if not f.exists():
                f.write_bytes(pickle.dumps(collect_session(sid)))
                print(sid, flush=True)
    elif a.cmd == "report":
        print(json.dumps(report(a.work), indent=1))
    else:
        montage(a.work, Path(a.args[0]), int(a.args[1]) if len(a.args) > 1 else 4,
                a.args[2] if len(a.args) > 2 else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
