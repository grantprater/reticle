r"""Score candidate roster SPLIT RULES against each other, from stored data.

    .\.venv\Scripts\python.exe prototypes\roster_split_eval.py

`docs/ROSTER_FINDINGS.md` localized a confirmed roster undercount and named the
next experiment. It could not be run, because `l1/roster` stored only the COUNT
and not the detail vector it was adjudicated from -- so trying a different rule
meant re-reading the video. `roster-0.2.0` stores the ten floats, and this is
the experiment that became free as a result.

WHERE EACH RULE CAME FROM, because the order matters
------------------------------------------------------
`absolute` is the shipped rule: choose the split maximising `min(occupied) -
max(empty)`, subject to `DETAIL_FLOOR`.

`ratio` maximises `min(occupied) / max(empty)` instead, and is now SHIPPED as
`reticle.roster.alive_from_detail` -- so re-running this compares the current
reader against the rule it replaced. **The argument for it
is the compositing mechanism `roster.py` already documents, not the failing
frame.** The bar is a semi-transparent tinted panel, so scenery behind it
arrives dimmed and blurred by a roughly constant transmittance while the
portrait is crisp art composited on top. Both populations therefore SCALE with
how detailed the scene behind the bar is, and a boundary between two
multiplicative populations is a ratio, not a difference. The shipped rule's
`14.70 > 13.05` failure at 1483.0s is what made anyone look; it is not what
chose the statistic, and that window is excluded from the totals below.

WHAT SCORES THEM, and how independent each score actually is
--------------------------------------------------------------
Three, in increasing order of independence from the thing that motivated the
change -- stated plainly because it is easy to pass off a generalisation of the
observed defect as a fresh confirmation of it:

    excursions   a count that leaves a value and returns to it within a
                 second. Deaths do not undo, and a revive that completes and
                 reverses inside 1.0s is not a thing. NOT independent: this is
                 exactly the 1483.0s failure mode, measured corpus-wide. It
                 says HOW MUCH of that defect there is, not that it is real.
    invariants   per round: opens at 5, never exceeds 5, mid-round increases.
                 Increases are REPORTED, never penalised -- Sage and Clove
                 revive. Weakly independent: bounds, and a rule that can only
                 emit 0..5 passes the `<= 5` half for free.
                 **`opens-at-5` and `increases` are CONFOUNDED by round
                 boundaries and must not be read as rule quality.**
                 `round_bounds` starts a round at the score increment, which is
                 the instant the PREVIOUS round ended -- usually with a wipe --
                 so the correct count there is 0, not 5. Gating the empty bar
                 takes `opens-at-5` from 21/38 to 4/38 by ANSWERING those rows
                 correctly where the old rule refused and was skipped. Verified
                 by hand at 255.0s and 1315.5s on `587c15b07779`: allies all
                 dim, four enemies crisp, score stepping to the enemy.
    audit        `reconciliation.audit_roster_deltas` against the killfeed,
                 re-run with each rule's counts. INDEPENDENT: a different
                 channel, read by different code, from different pixels.

Only the third can move the decision on its own. The first two describe cost.

None of these is an accuracy estimate. There are no labels here and none is
requested: this compares two rules on a corpus neither was fitted to.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from reticle.reconciliation import audit_roster_deltas, round_bounds   # noqa: E402
from reticle.roster import (DETAIL_FLOOR, N_SLOTS,                     # noqa: E402
                            alive_from_detail)
from reticle.store import Store                                        # noqa: E402

#: An excursion shorter than this cannot be a death and a revive.
EXCURSION_MS = 1000.0
#: The one sequence that is EVIDENCE rather than data. Held out of every total.
HELD_OUT = {"587c15b07779": (1474000.0, 1484500.0)}


def _splits(detail, pack_right):
    """(n, occupied, empty) for every split `DETAIL_FLOOR` does not veto."""
    seq = list(reversed(detail)) if pack_right else list(detail)
    for n in range(0, N_SLOTS + 1):
        occ, emp = seq[:n], seq[n:]
        if occ and min(occ) < DETAIL_FLOOR:
            continue
        yield n, occ, emp


def split_absolute(detail, pack_right, hud_drawn=None):
    """The rule this replaced -- widest ABSOLUTE gap, as it stood at 0.1.0."""
    best, best_gap = None, -1.0
    for n, occ, emp in _splits(detail, pack_right):
        if not occ:
            gap = -max(emp) if emp else 0.0
        elif not emp:
            gap = min(occ)
        else:
            gap = min(occ) - max(emp)
        if gap > best_gap:
            best, best_gap = n, gap
    return best


# `split_ratio` is SHIPPED and lives in `reticle.roster.alive_from_detail`
# (roster-split-0.2.0). It is imported here rather than kept as a second copy:
# promotion is deletion plus re-export, and `floor_mask` forked for ten days the
# other way. `split_absolute` stays because nothing in `reticle/` implements it
# any more -- it is the historical baseline this comparison is against.
def split_ratio(detail, pack_right, hud_drawn=None):
    """The SHIPPED rule. See `reticle.roster.alive_from_detail`."""
    return alive_from_detail(detail, pack_right, hud_drawn)


RULES = {"absolute": split_absolute, "ratio": split_ratio}


def derive(v, rule, gate=None):
    """Re-adjudicate both teams' counts from the stored detail vectors.

    `gate` is the per-row `hud_drawn` answer, applied to BOTH rules so refusal
    counts stay comparable -- without it the shipped rule looks like it lost 189
    answers on `c40d950031bb`, when what happened is that its zeros moved from
    "the bar is dark" to "the scoreline says the HUD is there".
    """
    f = RULES[rule]
    g = gate or [None] * len(v["t_ms"])
    def one(col, pack):
        return [None if d is None else f(list(d), pack, g[i])
                for i, d in enumerate(v[col])]
    return one("detail_ally", True), one("detail_enemy", False)


def hud_gate(h, t, join_ms=1000.0):
    """Per roster row: did the SCORELINE read at the nearest earlier HUD sample."""
    from bisect import bisect_right
    if not h:
        return None
    drawn = [l is not None and r is not None
             for l, r in zip(h["score_left"], h["score_right"])]
    out = []
    for x in t:
        i = bisect_right(h["t_ms"], x) - 1
        out.append(drawn[i] if 0 <= i < len(drawn) and x - h["t_ms"][i] <= join_ms
                   else None)
    return out


def excursions(t, counts, bounds):
    """Values that leave and return inside `EXCURSION_MS`, within one round."""
    out = []
    for r in bounds:
        idx = [i for i, x in enumerate(t)
               if r["t_start_ms"] <= x <= r["t_end_ms"] and counts[i] is not None]
        i = 0
        while i < len(idx) - 2:
            a = idx[i]
            j = i + 1
            while j < len(idx) and counts[idx[j]] != counts[a]:
                j += 1
            if j < len(idx) and j > i + 1 and t[idx[j]] - t[a] <= EXCURSION_MS:
                out.append((t[a], counts[a], counts[idx[i + 1]]))
                i = j
            else:
                i += 1
    return out


def invariants(t, counts, bounds):
    c = Counter()
    for r in bounds:
        seen = [counts[i] for i, x in enumerate(t)
                if r["t_start_ms"] <= x <= r["t_end_ms"] and counts[i] is not None]
        if not seen:
            c["round_unreadable"] += 1
            continue
        c["rounds"] += 1
        c["opens_at_5"] += seen[0] == 5
        c["over_5"] += sum(x > 5 for x in seen)
        c["increases"] += sum(y > x for x, y in zip(seen, seen[1:]))
    return c


def held_out(sid):
    lo, hi = HELD_OUT.get(sid, (None, None))
    return (lambda x: False) if lo is None else (lambda x: lo <= x <= hi)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None)
    a = ap.parse_args(argv)
    store = Store(a.store) if a.store else Store()

    paths = sorted(pathlib.Path(store.root, "l1", "roster").rglob("roster.parquet"))
    if not paths:
        raise SystemExit("no l1/roster tables -- run `reticle scan --only roster`")

    for path in paths:
        table = pq.read_table(path)
        v = table.to_pydict()
        sid = v["session_id"][0]
        if "detail_ally" not in v:
            print(f"{sid}  SKIP -- stored before roster-0.2.0, no detail vectors")
            continue
        date = path.parent.parent.name.split("=", 1)[1]
        hp = store.hud_path(sid, date)
        hud = pq.read_table(hp) if hp.is_file() else None
        h = hud.to_pydict() if hud is not None else None
        bounds = (round_bounds(h["t_ms"], h["score_left"], h["score_right"])[1:]
                  if h else [])
        t = v["t_ms"]
        drop = held_out(sid)
        n_held = sum(drop(x) for x in t)
        keep = [i for i, x in enumerate(t) if not drop(x)]
        kt = [t[i] for i in keep]

        print(f"\n=== {sid}  {len(t)} rows, {len(bounds)} rounds"
              f"{f', {n_held} rows held out' if n_held else ''} ===")
        gate = hud_gate(h, t)
        for name in RULES:
            ally, enemy = derive(v, name, gate)
            ka = [ally[i] for i in keep]
            ke = [enemy[i] for i in keep]
            answered = sum(x is not None and y is not None for x, y in zip(ka, ke))
            zero = sum(x == 0 and y == 0 for x, y in zip(ka, ke))
            exc = excursions(kt, ka, bounds) + excursions(kt, ke, bounds)
            inv = invariants(kt, ka, bounds) + invariants(kt, ke, bounds)
            moved = (sum(x != y for x, y in zip(ally, v["alive_ally"]))
                     + sum(x != y for x, y in zip(enemy, v["alive_enemy"])))
            print(f"  {name:9s} answered {answered}/{len(keep)} "
                  f"({answered / len(keep) * 100:.1f}%)  0/0 {zero}  "
                  f"excursions {len(exc)}  [confounded: opens-at-5 "
                  f"{inv['opens_at_5']}/{inv['rounds']}  increases "
                  f"{inv['increases']}]  over-5 {inv['over_5']}  "
                  f"cells moved {moved}")
            if hud is not None:
                # DROP the detail columns: `audit_roster_deltas` re-adjudicates
                # from them with the shipped rule, so leaving them in would make
                # every row of this table report the same audit -- answering a
                # different question than the one being asked.
                cols = {k: table.column(k) for k in table.column_names
                        if not k.startswith("detail_")}
                cols["alive_ally"] = pa.array(ally, type=pa.int8())
                cols["alive_enemy"] = pa.array(enemy, type=pa.int8())
                c = audit_roster_deltas(hud, pa.table(cols))["counts"]
                print(f"             audit  agree {c.get('agree',0)}  "
                      f"disagree {c.get('disagreement',0)}  "
                      f"ambiguous {c.get('timing_ambiguous',0)}  "
                      f"unreadable {c.get('unreadable_roster',0)}  "
                      f"increase {c.get('count_increase_requires_explanation',0)}")
        if n_held:
            print("  held out (evidence, not data):")
            got = {n: derive(v, n)[0] for n in RULES}
            for i, x in enumerate(t):
                if drop(x):
                    row = " ".join(f"{y:6.2f}" for y in v["detail_ally"][i])
                    print(f"    {x/1000:8.1f}s  [{row}]  "
                          + "  ".join(f"{k}={got[k][i]}" for k in RULES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
