r"""Measure the live restock of Sova's Recon Bolt and Skye's Guiding Light.

    .\.venv\Scripts\python.exe prototypes\restock_measure.py [--record] [--json OUT]

The question
------------
The client's tuning gives both abilities a 50 s restock; the wiki catalogue,
which the mechanics sheet cites, gives 60 s
[domain:abilities/catalogue-restock-and-ult-points-confirmed]. A restock is a
charge that comes back by itself during a round after being spent, with no
kill and no buy [domain:abilities/recharge-kinds].

What it reads
-------------
Only stored rows: `events/ability_state/<sid>.jsonl` (`adjudication.
ability_state`, which reads the tray's fills on a 0.5 s grid) and the stored
death verdicts (`events/death/<sid>.jsonl`, for the player's kills). It
decodes nothing and reads no crop. A session counts when the identity
arbiter's agent, as the ability-state coverage row carries it, is Sova or
Skye and the kit's E slot names the ability; each ability is measured on its
own sessions only [domain:abilities/ability-rules-are-unique].

The pairing
-----------
Per round, in the live phases (`round_live`, `post_plant`), a verdict on slot
E whose charges fall is a spend, and a `recharge` verdict is a return; the
buy phase's rises are `buy`, between rounds `refill_between_rounds`, and
neither counts. Every spend opens a pending charge; a return closes the
earliest one. The interval is reported three ways, since how a second spend
during a restock is timed is unknown:

* `from_spend`: from the spend the return closes (the earliest pending);
* `serial`: from that spend or the previous return of the round, whichever is
  later (one timer at a time, restarted per charge);
* `from_latest`: from the latest spend before the return.

For a one-charge slot the three agree. Each time is the verdict's sample; the
event lies in the half-second before it, so an interval is good to +-0.5 s,
more where a refused sample bridges the gap (`bounds_s`).

A spend never returned is kept, never dropped: it is censored at the end of
its round's readable tray (death, round end or the kit witness), and the
watched time says what it rules out. A spend watched for more than
50 s + `SLACK_S` without a return contradicts a 50 s timer; one watched past
60 s + `SLACK_S`, both. A return with no pending spend, or one a player kill
precedes within `KILL_S`, is an outlier with its reason.

What it found (2026-10-04)
--------------------------
The stored rows cannot answer. Over 8 Sova and 6 Skye match sessions they
hold 104 and 69 live E spends but only 2 and 3 live returns, at 5 to 22 s,
while 4 Recon Bolt and 2 Guiding Light spends stay empty past 61 s with the
tray readable and the player alive. The crops say why: the client draws a
restocked charge as a gold segment, and `tray.slot_counts` counts only teal,
so a restock never raises the stored fill. The two crops of the short
"returns" show a cyan screen streak over the bar with the countdown still
running (`96aa1ae9b96f` 672.0 s, '38'; `e37fdeca944f` 396.6 s, '29'). The
crops (`CROP_READS`) measure both restocks at 50 s, within half a second, on
three spends each, and the countdown reads '50' on the spend sample. Those
reads are now facts [domain:abilities/sova-recon-bolt-restock-observed]
[domain:abilities/skye-guiding-light-restock-observed]
[domain:hud/ability-tray-restock-countdown], and the tray reader classes the
gold segment (`tray.segment_classes`), so `ability_state` stores a live
return from `ability-state-0.8.0`. This prototype still pairs `recharge`
verdicts only; it predates the `live_return` transition.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

STORE = Path.home() / "reticle-store"
#: The abilities measured, per agent: the E slot's ability name in the kit.
TARGETS = {"Sova": "Recon Bolt", "Skye": "Guiding Light"}
SLOT = "E"
LIVE = ("round_live", "post_plant")
#: The two candidate restocks (s): client tuning and wiki catalogue.
CANDIDATES = (50.0, 60.0)
#: Sampling slack (s): one grid step on each side.
SLACK_S = 1.0
#: A player kill this long before a return (s) explains it as a kill restock.
KILL_S = 3.0
BIN_S = 2.0
VERSION = "restock-measure-0.1.0"

#: Hand reads of the tray crops (`roi_cache` hud_abilities, no decode), three
#: spends per ability that the stored rows leave unreturned past 50 s. The
#: client draws a countdown above the slot from the cast ("50" on the spend
#: sample), whole seconds above one and tenths below, and the returned charge
#: as a gold segment, which the tray reader's teal mask does not count.
#: Each row: (session, fall after s, fall by s, return after s, return by s,
#: what bounds the return). The fall bounds are the stored verdict's two
#: samples; the return bounds come from the countdown's last reading and the
#: first gold sample.
CROP_READS = {
    "Recon Bolt": [
        ("9acf02f98283", 1850.5, 1851.0, 1900.0, 1901.0, "'10' at 1891.0, '1' at 1900.0, gold at 1902.0"),
        ("59c70f1ef720", 1271.5, 1272.5, 1321.5, 1322.0, "'50' at 1272.5, gold at 1322.0"),
        ("043bafca271a", 1011.0, 1011.5, 1061.35, 1061.45, "'50' at 1011.5, '0.4' at 1061.0, gold at 1062.0"),
    ],
    "Guiding Light": [
        ("bfad2778a372", 1962.5, 1963.0, 2012.0, 2012.5, "'50' at 1963.0, gold at 2012.5"),
        ("c62c2b06bcfb", 462.57, 463.07, 513.05, 513.15, "'0.6' at 512.5, gold at 514.0"),
        ("c62c2b06bcfb", 1241.0, 1242.05, 1291.2, 1291.45, "'0.7' at 1290.7, '0.1' at 1291.2, gold at 1291.6"),
    ],
}


def crop_bounds(reads) -> dict:
    """Each read's interval bounds and the intersection over all reads (s)."""
    each = [(r[3] - r[2], r[4] - r[1]) for r in reads]
    if not each:
        return {"n": 0}
    lo, hi = max(a for a, _ in each), min(b for _, b in each)
    return {"n": len(each), "each": [[round(a, 2), round(b, 2)] for a, b in each],
            "min_lo": round(min(a for a, _ in each), 2), "max_hi": round(max(b for _, b in each), 2),
            "common_lo": round(lo, 2), "common_hi": round(hi, 2)}


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def player_kills_ms(rows: list[dict]) -> list[float]:
    """Times of the player's kills from stored death verdicts."""
    out = []
    for r in rows:
        if r.get("kind") == "death_verdict" and r.get("kf_player_kill"):
            t = r.get("t_first_ms", r.get("t_ms", r.get("t_last_ms")))
            if t is not None:
                out.append(float(t))
    return sorted(out)


def _phase_at(states: list[dict], t: float) -> tuple[str | None, int | None]:
    """Phase and round of the slot's state row that starts at or holds `t`."""
    for s in states:
        if s["t_first_ms"] - 1 <= t <= s["t_last_ms"] + 1:
            return s.get("phase"), s.get("round")
    return None, None


def _charges(side: dict | None):
    return None if not side else side.get("charges")


def events(rows: list[dict], slot: str = SLOT) -> tuple[list[dict], list[dict]]:
    """Spends and returns on `slot` in live phases, and the slot's state rows.

    Returns (events, states). An event: {t_ms, t_lo_ms, kind, round, transition,
    reason, before, after}; kind is "spend" or "return"."""
    states = sorted((r for r in rows if r.get("kind") == "state" and r.get("slot") == slot),
                    key=lambda s: s["t_first_ms"])
    out = []
    for v in rows:
        if v.get("kind") != "verdict" or v.get("slot") != slot:
            continue
        b, a = _charges(v.get("before")), _charges(v.get("after"))
        tr = v.get("transition")
        if tr == "recharge":
            kind = "return"
        elif b is not None and a is not None and a < b:
            kind = "spend"
        else:
            continue
        t = float(v["t_ms"])
        phase, rnd = _phase_at(states, t)
        if phase not in LIVE:
            continue
        lo = (v.get("before") or {}).get("t_ms", t)
        out.append({"t_ms": t, "t_lo_ms": float(lo), "kind": kind, "round": rnd,
                    "transition": tr, "reason": v.get("reason"), "before": b, "after": a,
                    "fill_before": (v.get("before") or {}).get("fill"),
                    "fill_after": (v.get("after") or {}).get("fill")})
    out.sort(key=lambda e: e["t_ms"])
    return out, states


def watched_until(states: list[dict], rnd, t: float) -> float:
    """Last readable live sample of round `rnd` at or after `t` (ms)."""
    ends = [s["t_last_ms"] for s in states
            if s.get("round") == rnd and s.get("phase") in LIVE
            and s.get("unreadable_reason") is None and s["t_last_ms"] >= t]
    return max(ends) if ends else t


def pair(evs: list[dict], states: list[dict], kills_ms=()) -> tuple[list[dict], list[dict], list[dict]]:
    """(intervals, censored spends, outlier returns) for one session's slot."""
    kills = np.asarray(sorted(kills_ms), float)
    intervals, censored, outliers = [], [], []
    rounds = sorted({e["round"] for e in evs if e["round"] is not None})
    for rnd in rounds:
        pending, last_return = [], None
        for e in (x for x in evs if x["round"] == rnd):
            if e["kind"] == "spend":
                pending.append(e)
                continue
            near = kills[(kills <= e["t_ms"]) & (kills >= e["t_lo_ms"] - KILL_S * 1000)]
            if not pending:
                outliers.append(dict(e, why="return_without_a_pending_spend",
                                     kill_ms=float(near[-1]) if len(near) else None))
                last_return = e
                continue
            if len(near):
                outliers.append(dict(e, why="player_kill_before_return", kill_ms=float(near[-1]),
                                     spend_ms=pending[0]["t_ms"]))
                pending.pop(0)
                last_return = e
                continue
            sp = pending.pop(0)
            start = sp if last_return is None or last_return["t_ms"] < sp["t_ms"] else last_return
            latest = max((p for p in [sp, *pending] if p["t_ms"] <= e["t_ms"]),
                         key=lambda p: p["t_ms"])
            intervals.append({
                "round": rnd, "spend_ms": sp["t_ms"], "return_ms": e["t_ms"],
                "from_spend": (e["t_ms"] - sp["t_ms"]) / 1000.0,
                "serial": (e["t_ms"] - start["t_ms"]) / 1000.0,
                "from_latest": (e["t_ms"] - latest["t_ms"]) / 1000.0,
                "bounds_s": [(e["t_lo_ms"] - sp["t_ms"]) / 1000.0, (e["t_ms"] - sp["t_lo_ms"]) / 1000.0],
                "spend_transition": sp["transition"], "spend_reason": sp["reason"],
                "charges": [sp["before"], sp["after"], e["before"], e["after"]],
                "pending_after": len(pending)})
            last_return = e
        for sp in pending:
            end = watched_until(states, rnd, sp["t_ms"])
            censored.append({"round": rnd, "spend_ms": sp["t_ms"], "spend_lo_ms": sp["t_lo_ms"],
                             "watched_s": (end - sp["t_ms"]) / 1000.0,
                             "spend_transition": sp["transition"], "spend_reason": sp["reason"]})
    return intervals, censored, outliers


def summarise(values) -> dict:
    v = np.asarray(sorted(values), float)
    if not len(v):
        return {"n": 0, "median": None, "q1": None, "q3": None, "iqr": None, "min": None, "max": None}
    q1, med, q3 = np.percentile(v, [25, 50, 75])
    return {"n": int(len(v)), "median": round(float(med), 2), "q1": round(float(q1), 2),
            "q3": round(float(q3), 2), "iqr": round(float(q3 - q1), 2),
            "min": round(float(v[0]), 2), "max": round(float(v[-1]), 2)}


def histogram(values, bin_s: float = BIN_S) -> dict:
    v = np.asarray(values, float)
    if not len(v):
        return {}
    lo = np.floor(v.min() / bin_s) * bin_s
    hi = np.ceil((v.max() + 1e-9) / bin_s) * bin_s
    edges = np.arange(lo, hi + bin_s, bin_s)
    counts, edges = np.histogram(v, bins=edges)
    return {f"{edges[i]:.0f}-{edges[i + 1]:.0f}": int(c) for i, c in enumerate(counts) if c}


def censored_against(censored: list[dict]) -> dict:
    """Unreturned spends watched past each candidate: each contradicts it."""
    w = np.asarray([c["watched_s"] for c in censored], float)
    return {f"watched_past_{int(c)}s": int((w > c + SLACK_S).sum()) for c in CANDIDATES}


def restock_verdict(stats: dict, against: dict, intervals=()) -> str:
    """50 s, 60 s, neither, or cannot-answer with its reason.

    The instrument check comes first: spends the tray watched past both
    candidates without a return, while no return falls near either, say the
    stored rows do not see a restock at all; a median of what they do see
    would measure something else."""
    top = f"watched_past_{int(max(CANDIDATES))}s"
    plausible = [i for i in intervals if min(CANDIDATES) - 10 <= i["serial"] <= max(CANDIDATES) + 10]
    if against.get(top) and not plausible:
        return (f"cannot-answer: {against[top]} spend(s) watched past {int(max(CANDIDATES))} s "
                f"with no stored return, and no stored return within 10 s of either candidate; "
                f"the stored tray rows do not see the restock")
    med = stats["median"]
    if med is None:
        return "cannot-answer: no paired return"
    near = [c for c in CANDIDATES if abs(med - c) <= 2.0]
    if len(near) != 1:
        return f"neither: median {med} s"
    c = near[0]
    if against.get(f"watched_past_{int(c)}s"):
        return f"{int(c)} s contradicted by {against[f'watched_past_{int(c)}s']} unreturned spend(s)"
    return f"{int(c)} s"


def measure(store: Path = STORE) -> dict:
    out = {}
    for path in sorted((store / "events" / "ability_state").glob("*.jsonl")):
        rows = load_rows(path)
        cov = rows[0] if rows and rows[0].get("kind") == "coverage" else {}
        agent = (cov.get("agent") or {}).get("agent")
        if agent not in TARGETS or (cov.get("kit") or {}).get(SLOT) != TARGETS[agent]:
            continue
        sid = cov["session_id"]
        dpath = store / "events" / "death" / f"{sid}.jsonl"
        kills = player_kills_ms(load_rows(dpath)) if dpath.exists() else []
        evs, states = events(rows)
        iv, cen, outl = pair(evs, states, kills)
        a = out.setdefault(TARGETS[agent], {"agent": agent, "sessions": [], "intervals": [],
                                            "censored": [], "outliers": [], "spends": 0,
                                            "ability_state_versions": []})
        a["sessions"].append(sid)
        ver = cov.get("ability_state_version")
        if ver not in a["ability_state_versions"]:
            a["ability_state_versions"] = sorted([*a["ability_state_versions"], ver], key=str)
        a["spends"] += sum(1 for e in evs if e["kind"] == "spend")
        for lst, src in (("intervals", iv), ("censored", cen), ("outliers", outl)):
            a[lst].extend(dict(x, session=sid) for x in src)
    for name, a in out.items():
        for k in ("from_spend", "serial", "from_latest"):
            a[f"stats_{k}"] = summarise([i[k] for i in a["intervals"]])
        a["histogram_serial"] = histogram([i["serial"] for i in a["intervals"]])
        a["against"] = censored_against(a["censored"])
        a["verdict"] = restock_verdict(a["stats_serial"], a["against"], a["intervals"])
        a["crops"] = crop_bounds(CROP_READS.get(name, []))
    return out


def record_ledger(res: dict) -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from reticle import metrics
    out = []
    for name, a in res.items():
        part = name.lower().replace(" ", "_")
        st = a["stats_serial"]
        vals = {"n": st["n"], "median_s": st["median"], "q1_s": st["q1"], "q3_s": st["q3"],
                "iqr_s": st["iqr"], "min_s": st["min"], "max_s": st["max"],
                "median_from_spend_s": a["stats_from_spend"]["median"],
                "median_from_latest_s": a["stats_from_latest"]["median"],
                "spends": a["spends"], "censored": len(a["censored"]),
                "outliers": len(a["outliers"]), **a["against"],
                "crop_n": a["crops"]["n"], "crop_min_lo_s": a["crops"].get("min_lo"),
                "crop_max_hi_s": a["crops"].get("max_hi"),
                "crop_common_lo_s": a["crops"].get("common_lo"),
                "crop_common_hi_s": a["crops"].get("common_hi")}
        status = "cannot-answer" if a["verdict"].startswith("cannot-answer") else "pass"
        metrics.record("restock_measure", part=part, session="all-sessions", values=vals,
                       deps={"version": VERSION, "ability_state": ",".join(map(str, a["ability_state_versions"]))},
                       context={"sessions": a["sessions"], "agent": a["agent"]},
                       status=status, note=a["verdict"])
        out.append(f"restock_measure/{part}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--store", default=str(STORE))
    args = ap.parse_args(argv)
    res = measure(Path(args.store))
    for name, a in res.items():
        print(f"== {name} ({a['agent']}, {len(a['sessions'])} sessions, {a['spends']} live spends)")
        for k in ("serial", "from_spend", "from_latest"):
            print(f"  {k:12s} {a['stats_' + k]}")
        print(f"  histogram (serial, {BIN_S:.0f} s bins): {a['histogram_serial']}")
        for i in a["intervals"]:
            print(f"    {i['session']} r{i['round']} spend {i['spend_ms'] / 1000:.1f} -> return "
                  f"{i['return_ms'] / 1000:.1f}: serial {i['serial']:.1f} s, from spend {i['from_spend']:.1f}, "
                  f"bounds {i['bounds_s']}, charges {i['charges']}")
        print(f"  censored: {len(a['censored'])} {a['against']}")
        for c in sorted(a["censored"], key=lambda c: -c["watched_s"])[:8]:
            print(f"    {c['session']} r{c['round']} spend {c['spend_ms'] / 1000:.1f} watched {c['watched_s']:.1f} s")
        for o in a["outliers"]:
            print(f"  outlier {o['session']} r{o['round']} {o['t_ms'] / 1000:.1f}: {o['why']} kill={o.get('kill_ms')}")
        print(f"  verdict (stored rows): {a['verdict']}")
        print(f"  crop reads (countdown and gold segment): {a['crops']}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    if args.record:
        print("recorded", record_ledger(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
