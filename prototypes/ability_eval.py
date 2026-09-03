"""Score ability-candidate DETECTION against the answers.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_eval.py <session>...
    .\\.venv\\Scripts\\python.exe prototypes\\ability_eval.py --fit A --score B

Why this exists
---------------
`dynamic_eval.py` scores the OTHER label path -- `kind: ability` rows produced
by `label_dynamic.py` over a full match -- and cannot read the candidate stream
that `scan_ability_clip.py` writes for a controlled clip. So the clip path, which
is where every 2026-09-02 finding was measured, has had no scorer at all: the
numbers in `NOTES.md` (`self_icon_dist` separating 8.0-31.5 px from 2.6-6.5 px)
were counted by hand off five rows.

The features are NOT recomputed here, unlike `dynamic_eval.features`. They are
already written to every candidate row by `scan_ability_clip.py` -- `area`,
`aspect`, `colour`, `device_*`, `self_icon_dist`, and, unexamined until now,
**`n_observations` and `duration_ms`**. Recomputing would mean re-decoding the
video to rediscover numbers already on disk.

What the first run found, 2026-09-03
------------------------------------
**Lifetime was never a missing feature.** It was a recorded one nothing had
looked at, and it roughly DOUBLES precision at zero recall cost on both
sessions -- the two different widget sizes, which is the transfer that matters:

                                        79a706a7ce4c      eb10db50b1fb
                                        (bigmap, 4 real)  (small, 5 real)
    no filter                            100% /  6.1%      100% / 16.1%
    self_icon_dist >= 7  (SHIPPED)       100% /  7.3%      100% / 21.7%
    self>=7 AND n_obs>=5                 100% / 12.9%      100% / 33.3%
    self>=7 AND n_obs>=5 AND born>0      100% / 13.8%      100% / 55.6%
    self>=7 AND n_obs>=20                 50% / 25.0%      100% / 38.5%

**An ability is an EVENT, so it has a birth.** No real object in either session
starts at `t_ms == 0`; a candidate present in the very first sampled frame was
never placed during the clip. The gate has never yet cost a true positive, and
on the small widget it takes precision from 33.3% to 55.6%.

**But do NOT fit the threshold -- that is the sharpest finding here.** Fitting
the operating point by F1 and scoring it on the other session collapses:

    fit bigmap -> score small    held out  100% recall / 38.5% precision
    fit small  -> score bigmap   held out   50% recall / 12.5% precision

The second direction loses half the trapwires, because the fitted point
(`n_obs>=8`) is tuned to a session whose objects live longer. With 4-5 positives
per session, F1 buys precision with recall it cannot afford. The FIXED
conservative point `self>=7 AND n_obs>=5 AND born>0` holds 100% recall on both
and still gains ~2x precision -- so ship the fixed point and leave the sweep as
a diagnostic. NOTES.md predicted this ("icon size and cone geometry both scale
with widget size"); it is now measured rather than feared.

Three limits, stated because the numbers above are small enough to mislead:
**n = 9 positives total** (4 + 5, after dropping 3 `uncertain` rows); the sweep
numbers are picked on the rows they are scored on, which is what `--fit/--score`
exists to expose; and the joined set is two sessions of the five that have
`labels/ability/` files. Every real object in both is a Cypher trapwire, so this
measures ONE ability class, not the class list.

Which sessions can be scored at all, and why most cannot
--------------------------------------------------------
This refuses rather than guessing, and the refusals are the interesting half:

* **`a06f04a0059f`, `5822b6646448` -- identity-only labels, NO negatives.** Every
  row is `not_ability: false`, because those came through `--source dynamic`
  where `label_dynamic` had already confirmed the row was an ability and this
  pass only asked WHICH. Precision is undefined on a set with no negatives, and
  computing recall alone against a pool pre-filtered by a different detector
  would be a population mismatch of exactly the kind CLAUDE.md records twice.
  Recorded `cannot-answer`;
* **`2ba870ccbd50` -- 1 of 40 labels join; `eb10db50b1fb` -- 31 of 50.** The
  candidate file was REGENERATED after the player labelled it, so the labels are
  keyed `(t_ms, x, y)` to rows that no longer exist. The `(x, y)` alone does not
  match either, so this is not an ROI shift -- it is a different scan;
* **`d95cfad5693a` -- 47 reviewed candidates and zero labels.** The cheapest
  available way to grow this set.

**The key is not stable, and that is a defect this file only measures.** The
label store is append-only last-write-wins on `(t_ms, x, y)` (the convention
`dynamic_eval.load` relies on), which silently assumes candidate rows outlive
the labelling. Re-running `scan_ability_clip.py` breaks that assumption and
orphans every answer. The candidate file content hash is therefore a **dep**
here, not context: a run against regenerated candidates is not comparable to one
against the file the player actually answered, and `metrics` must refuse to diff them
rather than show a delta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import metrics                                       # noqa: E402

STORE = Path.home() / "reticle-store"

#: Rows this close together are one physical object. Same constant and the same
#: reasoning as `dynamic_eval.COLLAPSE_PX`.
COLLAPSE_PX = 8


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else "absent"


def _rows(p: Path):
    """Last write for a `(t_ms, x, y)` wins -- the store-wide convention."""
    if not p.is_file():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[(d["t_ms"], d["x"], d["y"])] = d
    return out


def join(sid):
    """Candidate features carrying the verdict. Returns (rows, diagnosis)."""
    cand = _rows(STORE / "labels" / "ability_candidates" / f"{sid}.jsonl")
    lab = _rows(STORE / "labels" / "ability" / f"{sid}.jsonl")
    rows, skipped = [], 0
    for k, d in lab.items():
        if d.get("uncertain"):
            skipped += 1
            continue
        c = cand.get(k)
        if c is None:
            continue
        r = dict(c)
        r["_true"] = not d.get("not_ability")
        r["_agent"] = d.get("agent")
        r["_ability"] = d.get("ability")
        rows.append(r)
    diag = {"n_cand": len(cand), "n_lab": len(lab), "n_joined": len(rows),
            "n_uncertain": skipped,
            "n_pos": sum(1 for r in rows if r["_true"]),
            "n_neg": sum(1 for r in rows if not r["_true"])}
    return rows, diag


def collapse(rows, px=COLLAPSE_PX):
    """One row per position -- objects, not tracks.

    Deliberately NOT `label_ability.collapse_positions`, which overwrites
    `n_observations` with the size of the group it collapsed. That is right for
    an identity question (it records "labelled once, backs 33 sightings") and
    would be silently wrong here, because `n_observations` is the very field
    being gated on -- collapsing would replace a track lifetime with a count of
    tracks and the sweep would fit to an artefact of the collapse.

    Kept instead: the earliest onset, and the LONGEST lifetime at that position,
    which is what "how long did the object last" means once a real object has
    been split into several tracks (see `--fragments`).
    """
    groups: dict = {}
    for r in rows:
        groups.setdefault((int(r["x"]) // px, int(r["y"]) // px), []).append(r)
    out = []
    for g in groups.values():
        rep = dict(min(g, key=lambda r: r["t_ms"]))
        rep["n_observations"] = max((r.get("n_observations") or 0) for r in g)
        rep["duration_ms"] = max((r.get("duration_ms") or 0) for r in g)
        rep["_true"] = any(r["_true"] for r in g)
        rep["_n_tracks"] = len(g)
        out.append(rep)
    return out


def gate(r, self_min, nobs_min, onset):
    """The three gates, each monotone in one stored field.

    `self_icon_dist is None` means no self ring was fitted in that frame, i.e.
    no evidence either way -- kept, matching `scan_ability_clip`'s own
    `drop_self_icon and sd is not None and sd < SELF_ICON_DIST_MIN`. Treating an
    absent measurement as a failing one would quietly reject every frame where
    the widget was unreadable.
    """
    sd = r.get("self_icon_dist")
    if self_min and sd is not None and sd < self_min:
        return False
    if (r.get("n_observations") or 0) < nobs_min:
        return False
    if onset and (r.get("t_ms") or 0) <= 0:
        return False
    return True


def at_point(rows, pt, name):
    """Score one fixed operating point. No choosing happens here."""
    pos = [r for r in rows if r["_true"]]
    if not pos:
        print(f"   {name}: no positive rows -- cannot score")
        return None
    tp = sum(1 for r in pos if gate(r, *pt))
    fp = sum(1 for r in rows if not r["_true"] and gate(r, *pt))
    rec = tp / len(pos)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    print(f"   {name:<36} TP {tp:3d}  FP {fp:4d}  FN {len(pos) - tp:3d}   "
          f"recall {rec * 100:5.1f}%  prec {prec * 100:5.1f}%")
    return {"n": len(rows), "pos": len(pos), "tp": tp, "fp": fp,
            "recall": round(rec, 4), "precision": round(prec, 4)}


#: The sweep. Small and enumerable on purpose: three monotone gates, so every
#: point is nameable in a commit message rather than being a fitted vector.
SELF_MINS = (0, 7, 12)
NOBS_MINS = (0, 3, 5, 8, 12, 20, 30)
ONSETS = (False, True)

#: Points always printed, so a run is readable without the sweep. The second is
#: what ships today (`filter_ability_candidates.SELF_PX` is 12; the scanner's
#: `SELF_ICON_DIST_MIN` is 7).
POINTS = (((0, 0, False), "no filter"),
          ((7, 0, False), "self_icon_dist >= 7  (SHIPPED)"),
          ((7, 5, False), "self>=7 AND n_obs>=5"),
          ((7, 5, True), "self>=7 AND n_obs>=5 AND born>0"),
          ((7, 20, False), "self>=7 AND n_obs>=20"))


def sweep_best(rows):
    """Best (self, n_obs, onset) on THESE rows by F1. Only ever the fit session."""
    pos = [r for r in rows if r["_true"]]
    neg = [r for r in rows if not r["_true"]]
    if not pos or not neg:
        return None
    best = None
    for s in SELF_MINS:
        for n in NOBS_MINS:
            for o in ONSETS:
                tp = sum(1 for r in pos if gate(r, s, n, o))
                fp = sum(1 for r in neg if gate(r, s, n, o))
                if not tp:
                    continue
                rec, prec = tp / len(pos), tp / (tp + fp)
                f1 = 2 * rec * prec / (rec + prec)
                if best is None or f1 > best[0]:
                    best = (f1, (s, n, o), rec, prec)
    return best


def name_point(pt):
    s, n, o = pt
    return f"self>={s},nobs>={n},onset={int(o)}"


def deps_for(sid, extra=None):
    d = {"gates": metrics.fingerprint(gate, join, collapse),
         "candidates_sha": _sha(STORE / "labels" / "ability_candidates" / f"{sid}.jsonl"),
         "labels_sha": _sha(STORE / "labels" / "ability" / f"{sid}.jsonl")}
    d.update(extra or {})
    return d


def refuse(sid, diag, why):
    print(f"   REFUSED: {why}")
    metrics.record("ability_eval", part="detect", session=sid, values={},
                   deps=deps_for(sid), context=diag,
                   status=metrics.CANNOT_ANSWER, note=why)


def prep(sid, by_position, header=False):
    rows, diag = join(sid)
    if header:
        # Printed BEFORE any refusal, or a refusal lands under the previous
        # session's heading and reads as that session's counts.
        print(f"\n=== {sid} ===  {diag['n_joined']} of {diag['n_lab']} labels joined "
              f"({diag['n_pos']} real, {diag['n_neg']} not, "
              f"{diag['n_uncertain']} unsure dropped)")
    if not rows:
        why = ("never went through scan_ability_clip.py -- these are --source "
               "dynamic labels, so there is no candidate file to join to"
               if diag["n_cand"] == 0 else
               "the candidate file was regenerated after labelling, orphaning "
               "the (t_ms, x, y) keys")
        refuse(sid, diag, f"no joined rows ({diag['n_lab']} labels, "
                          f"{diag['n_cand']} candidates -- {why})")
        return None, diag
    if diag["n_pos"] == 0 or diag["n_neg"] == 0:
        refuse(sid, diag, f"identity-only labels: {diag['n_pos']} positive / "
                          f"{diag['n_neg']} negative -- no detection to score")
        return None, diag
    return (collapse(rows) if by_position else rows), diag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--fit", help="session to CHOOSE the operating point on")
    ap.add_argument("--score", help="session to report it on, never fitted")
    ap.add_argument("--by-position", action="store_true",
                    help="collapse to one row per position: objects, not tracks")
    ap.add_argument("--fragments", action="store_true",
                    help="report how many tracks each physical object shattered into")
    args = ap.parse_args()
    unit = "objects" if args.by_position else "tracks"

    if args.fit and args.score:
        fit_rows, fit_diag = prep(args.fit, args.by_position)
        score_rows, score_diag = prep(args.score, args.by_position)
        if fit_rows is None or score_rows is None:
            return 1
        best = sweep_best(fit_rows)
        if best is None:
            raise SystemExit("could not fit: the fit session lacks positives or negatives")
        f1, pt, rec, prec = best
        print()
        print(f"FIT on {args.fit} ({len(fit_rows)} {unit}): "
              f"{name_point(pt)}  (F1 {f1:.2f} in-sample)")
        print(f"SCORE on {args.score} ({len(score_rows)} {unit}) -- never fitted:")
        print()
        at_point(fit_rows, pt, f"{args.fit} (in-sample)")
        held = at_point(score_rows, pt, f"{args.score} (HELD OUT)")
        print()
        print("The held-out row is the number to quote. These two sessions are")
        print("different WIDGET SIZES, so a held-out figure here is also the only")
        print("evidence that a threshold survives the bigmap rescale.")
        metrics.record(
            "ability_eval", part=f"held-out/{unit}", session=args.score,
            values=held or {},
            status=None if held else metrics.CANNOT_ANSWER,
            note="" if held else "no positive rows in the scoring session",
            deps=deps_for(args.score, {"fit_session": args.fit,
                                       "fit_sha": _sha(STORE / "labels" /
                                                       "ability_candidates" /
                                                       f"{args.fit}.jsonl"),
                                       "operating_point": name_point(pt),
                                       "unit": unit}),
            context={"n_score_rows": len(score_rows), "n_fit_rows": len(fit_rows),
                     "n_score_pos": score_diag["n_pos"], "n_fit_pos": fit_diag["n_pos"]},
        )
        print()
        print(metrics.report(tool="ability_eval"))
        return 0

    for sid in args.sessions:
        rows, diag = prep(sid, args.by_position, header=True)
        if rows is None:
            continue
        if args.by_position:
            print(f"   collapsed to {len(rows)} objects at {COLLAPSE_PX} px")
        for pt, nm in POINTS:
            at_point(rows, pt, nm)
        if args.fragments:
            byp = rows if args.by_position else collapse(rows, COLLAPSE_PX)
            for lbl, sel in (("REAL", True), ("NOT ", False)):
                n = sorted(r.get("_n_tracks", 1) for r in byp if r["_true"] is sel)
                print(f"   {lbl} objects: {len(n):3d}   tracks each: {n}")
            print("   Reals fragment too, so many-tracks-per-position is NOT a flicker")
            print("   discriminator -- TRACK_GAP_MS=600 is simply short for this class.")
            print("   Recorded because it was predicted to work and did not.")
        best = sweep_best(rows)
        if best:
            f1, pt, rec, prec = best
            print(f"   in-sample best: {name_point(pt)}  "
                  f"recall {rec * 100:.1f}%  prec {prec * 100:.1f}%  (F1 {f1:.2f}) "
                  f"-- fitted here, not a quotable number")
        cats = Counter(f"{r['_agent']}:{r['_ability']}" for r in rows if r["_true"])
        print("   real objects:", dict(cats))
        metrics.record(
            "ability_eval", part=f"in-sample/{unit}", session=sid,
            values=at_point(rows, (7, 5, False), "  recorded point") or {},
            deps=deps_for(sid, {"operating_point": name_point((7, 5, False)),
                                "unit": unit}),
            context={"n_lab": diag["n_lab"], "n_joined": diag["n_joined"],
                     "n_pos": diag["n_pos"]},
        )
    print()
    print(metrics.report(tool="ability_eval"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
