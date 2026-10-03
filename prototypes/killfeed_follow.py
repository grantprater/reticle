r"""Step 1 of the prior-driven killfeed reader: the queue follow beside the full parse.

    .\.venv\Scripts\python.exe prototypes\killfeed_follow.py trial SESSION --out DIR [--cut C] [--between T0 T1]
    .\.venv\Scripts\python.exe prototypes\riot_ground_truth.py SESSION --no-minimap --no-status --offline --deaths-from DIR\k_all
    .\.venv\Scripts\python.exe prototypes\killfeed_follow.py fit DIR [DIR ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_follow.py score DIR [DIR ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_follow.py sheet DIR KIND OUT.png

The plan is [docs/KILLFEED_QUEUE_PRIOR.md](../docs/KILLFEED_QUEUE_PRIOR.md),
section 9 step 1, with the player's and orchestrator's step-1 decisions: a
fingerprint verify, descriptors tagged by view, and deaths scored from the
first k views of each entry.

What runs
---------
`trial` reruns the `hud` reader and the killfeed portrait reader over the
killfeed crop cache (`reticle.trial.run`, `--from cache`: no decode), exactly
as `killfeed_trial_deaths.py` does, and wraps the portrait reader
(`killfeed.KillfeedPortraitReader`, [owns:killfeed-event]'s descriptors) in a
`FollowReader` that runs the follow on every sample before the full parse:

* **prediction** -- the queue state from earlier samples only: each entry's
  age against the lifetime [domain:killfeed/entry-lifetime], the order
  [domain:killfeed/stack-order] [domain:killfeed/stack-queue];
* **fingerprint** -- each predicted entry's template, cut at its first full
  parse, correlated over every row it could have risen to and a few below
  (to see a fall); then the queue order resolves the answers: entries keep
  their order half a pitch apart, the better score keeps a contested slot,
  and an unverified entry a newer one has risen past is gone. Soft maps, never
  binarised: whiteness (opaque text and icons) and a signed plate colour
  (green minus red, which carries the seam), both at native size. Vertical
  placement snaps to whole pixels [domain:killfeed/subpixel-placement], so
  the search is over integer rows. The rest pitch is the measured 39 px
  [domain:killfeed/slot-pitch], not `killfeed.PITCH`;
* **probe** -- the owner's band finder (`killfeed._plate_masks`,
  `killfeed._entry_bands`) over the crop: a band below the stack is an
  arrival, a band elsewhere a surprise.

A sample whose prediction fails (the kinds of the plan's section 3), an
arrival, the first sample after a hole, and the audit cadence of section 4
ask for the full parse. In step 1 the full parse runs on every sample
anyway (the wrapped reader's `entries` step), so the follow READS the
parse only where it asked for one; everywhere else the parse is the
comparator, stored apart, never fed back.

Every descriptor row the wrapped reader writes (portrait, weapon, name,
second life) is tagged by `(t_ms, y0)` with the follow's entry id, the view's
index within that entry (0 = first view) and whether it is a surprise view.
A view the follow holds only as a prediction (under the overlay mask, or
unseen before its due time) carries `scope: predicted` and `rests_on`, no
view index, and is never a descriptor source.

`trial` then builds deaths (`cli.death_streams`, the death owner) from the
descriptor rows kept at k = 1, 2, 3, 5 and all (every observed view plus
every surprise view), and from every row (`master`, the comparator), and
writes `DIR/k_<k>/events/death/SID.jsonl` for the Riot scorer.

Timing: the follow's steps are `usage.step`s (`prediction`, `fingerprint`,
`probe`), recorded per sample with the wrapped reader's (`entries`,
`second_life`, `weapon`, `portraits`, `names`), so `score` can price each k:
timed per-sample step costs, summed over the samples and views a follow at
that k would run them on (arithmetic).

Result, 2026-10-02 (8 sessions, cut 0.612; outcome row in the store's
`notes/predictions.jsonl`, task `killfeed-prior-step1-20261002`): k = all
scores as master on every session, and no finite k keeps the floor. At every
k <= 5 the death owner splits a risen plate into slot pieces (bdfdcf009dba
687 s), and pieces whose views fall past k lose the weapon that types them
as a revive; the owner must key entries by the follow id before a k cut can
save descriptor work. Surprises ran on 1.1% of samples; the follow's own
steps cost 4.7 ms per sample.

Not wired (`"wire": "no"`, same task): step 2 of the plan wires it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FOLLOW_VERSION = "killfeed-follow-proto-0.1.0"

#: [domain:killfeed/slot-pitch]: rest tops at 15.0 + 39.0 k at 1080p.
PITCH_PX = 39
FIRST_TOP = 15
#: [domain:killfeed/entry-lifetime]: content shows about 4.966 s.
LIFETIME_S = 4.966
#: Within half a sample of due, present and gone are both predicted.
DUE_SLACK_S = 0.5
#: A gap longer than this between samples is a hole; the state empties.
HOLE_MS = 750.0
#: Rows below an entry's last top the verify still searches, to see a fall.
SEARCH_DOWN = 6
#: Rows above the entry below's... the gap an entry keeps from the one above.
SLOT_GAP = PITCH_PX // 2              # two templates nearer than half a pitch claim one slot
#: A probe band within this of a followed top is that entry; a band's top
#: moves a few rows while its plate slides in.
BAND_TOL = 8
#: Association of a parse view with a followed entry: the parse's band top
#: jitters up to 6 rows on a resting plate (5822b6646448 969.0 s reads 21,
#: 971.0 s reads 15, one plate at 15), so the tolerance is BAND_TOL's.
ASSOC_TOL = BAND_TOL
#: The audit's position tolerance (plan section 4: "beyond 1 px").
AUDIT_TOL = 1
#: Audit cadence (plan section 4), fixed before reading.
AUDIT_NONEMPTY_EVERY = 4
AUDIT_EMPTY_EVERY = 20
#: An entry whose predicted rows are this much under the overlay mask is
#: occluded when it fails to verify.
OCCLUDED_FRAC = 0.3
#: Plate column fraction that bounds the template's columns.
TEMPLATE_COL_FRAC = 0.3
#: Provisional cut, used only by the fitting run (`trial --cut 0.5`, then `fit`).
PROVISIONAL_CUT = 0.5
#: The one cut, fitted by `fit` on the 448 labelled audit verifies of a full
#: 5822b6646448 run at the provisional cut: 1 misclassified, positives' 1st
#: percentile 0.692, negatives' 99th 0.645.
CUT = 0.612
KS = (1, 2, 3, 5)
DESCRIPTOR_STEPS = ("second_life", "weapon", "portraits", "names")
FOLLOW_STEPS = ("prediction", "fingerprint", "probe")
RESTS_ON = ["domain:killfeed/entry-lifetime", "domain:killfeed/stack-queue",
            "domain:killfeed/stack-order"]


def _below_normal() -> None:
    from killfeed_trial_deaths import _below_normal as bn
    bn()


# ------------------------------------------------------------------ soft maps

def soft_maps(crop: np.ndarray, usable: np.ndarray | None):
    """Whiteness and signed plate colour of the crop, soft, at native size.

    Whiteness ramps across the parse's own text gates (`killfeed.TEXT_V_MIN`,
    `TEXT_S_MAX`); plate colour is (G - R) / (max + 16),
    positive on a green plate, negative on a red one, near zero on white text
    and dark scenery. Masked pixels are zero in both."""
    import cv2
    from reticle import killfeed as kf
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)
    # Linear ramps 32 levels wide, centred on the gates: soft, and cheaper
    # than a logistic.
    white = (np.clip((v - (kf.TEXT_V_MIN - 16)) / 32.0, 0, 1)
             * np.clip(((kf.TEXT_S_MAX + 16) - s) / 32.0, 0, 1))
    f = crop.astype(np.float32)
    colour = (f[:, :, 1] - f[:, :, 2]) / (f.max(axis=2) + 16.0)
    if usable is not None:
        white = white * usable
        colour = colour * usable
    return white.astype(np.float32), colour.astype(np.float32)


def _ncc_column(strip: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    import cv2
    if strip.shape[0] < tpl.shape[0] or tpl.size == 0:
        return np.zeros(0, np.float32)
    r = cv2.matchTemplate(strip, tpl, cv2.TM_CCOEFF_NORMED)[:, 0]
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


# ---------------------------------------------------------------------- state

@dataclass
class Entry:
    id: int
    top: int
    h: int
    x0: int
    x1: int
    tw: np.ndarray
    tc: np.ndarray
    t_first: float
    wx0: int
    ally: bool | None
    n_views: int = 0
    status: str = "resting"        # resting | predicted | overdue
    last_seen: float = 0.0
    overdue_flagged: bool = False
    seen_now: bool = False         # observed (verified or parsed) this sample
    score_now: float | None = None
    # The template's frame less the parse's band top, measured at each parse:
    # a template cut from a padded slide-in band sits a few rows off.
    off: int = 0

    @property
    def ptop(self) -> int:
        """The entry's top in the parse's frame (band top)."""
        return self.top - self.off

    def age_s(self, t: float) -> float:
        return (t - self.t_first) / 1000.0


@dataclass
class Decision:
    t: float
    need_parse: list = field(default_factory=list)     # reasons
    surprises: list = field(default_factory=list)      # (kind, entry id or None, detail)
    audit: bool = False
    predicted_nonempty: bool = False
    verify: list = field(default_factory=list)         # per entry: id, best_y, score, ok
    bands: list = field(default_factory=list)


class Follow:
    """The queue follow. `pre` predicts and verifies from earlier samples
    only; `post` reads the parse when `pre` asked for one."""

    def __init__(self, usable: np.ndarray | None, cut: float, scale=None):
        from reticle import killfeed as kf
        self.scale = scale or kf.UNIT_SCALE
        self.usable = usable
        self.usable_f = usable.astype(np.float32) if usable is not None else None
        self.prefix = usable.astype(np.int32).cumsum(axis=1) if usable is not None else None
        self.cut = cut
        self.entries: list[Entry] = []
        self.next_id = 0
        self.last_t: float | None = None
        self.n_nonempty = 0
        self.n_empty = 0
        self.surprise_rows: list[dict] = []
        self.audit_rows: list[dict] = []
        self.predicted_rows: list[dict] = []
        self.parse_rows: list[dict] = []
        self.agree_rows: list[dict] = []
        self.verify_rows: list[dict] = []
        self.tags: dict[tuple[float, int], dict] = {}
        self.slot_keys: dict[tuple[float, int], tuple[float, int]] = {}
        self.ended: Counter = Counter()

    # -- helpers
    def _occluded_frac(self, e: Entry, top: int) -> float:
        if self.usable is None:
            return 0.0
        part = self.usable[max(0, top):top + e.h, e.x0:e.x1]
        return float(1.0 - part.mean()) if part.size else 0.0

    def _verify(self, e: Entry, W, C, lo: int, hi: int):
        H = W.shape[0]
        lo = max(0, lo)
        hi = min(hi, H - e.h)
        if hi < lo:
            return None, -1.0
        sw = _ncc_column(np.ascontiguousarray(W[lo:hi + e.h, e.x0:e.x1]), e.tw)
        sc = _ncc_column(np.ascontiguousarray(C[lo:hi + e.h, e.x0:e.x1]), e.tc)
        if not len(sw):
            return None, -1.0
        score = 0.5 * (sw + sc)
        j = int(np.argmax(score))
        return lo + j, float(score[j])

    def _new_entry(self, view, crop_maps, green, red, t: float) -> Entry:
        W, C = crop_maps
        a, z = int(view.y0), int(view.y1)
        plate = (green[a:z] | red[a:z]).mean(axis=0)
        cols = np.flatnonzero(plate >= TEMPLATE_COL_FRAC)
        x0, x1 = (int(cols[0]), int(cols[-1]) + 1) if len(cols) else (0, W.shape[1])
        e = Entry(id=self.next_id, top=a, h=z - a, x0=x0, x1=x1,
                  tw=np.ascontiguousarray(W[a:z, x0:x1]), tc=np.ascontiguousarray(C[a:z, x0:x1]),
                  t_first=t, wx0=int(view.wx0) if (view.killer_run and view.victim_run) else 0,
                  ally=view.victim_ally, last_seen=t)
        self.next_id += 1
        return e

    # -- the follow
    def pre(self, t: float, crop: np.ndarray, step) -> tuple[Decision, tuple]:
        from reticle import killfeed as kf
        d = Decision(t=t)
        with step("prediction"):
            hole = self.last_t is None or t - self.last_t > HOLE_MS
            if hole:
                if self.entries:
                    self.ended["hole"] += len(self.entries)
                self.entries = []
                d.need_parse.append("seed")
            self.last_t = t
            d.predicted_nonempty = bool(self.entries)
            if not hole:
                if self.entries:
                    self.n_nonempty += 1
                    d.audit = self.n_nonempty % AUDIT_NONEMPTY_EVERY == 0
                else:
                    self.n_empty += 1
                    d.audit = self.n_empty % AUDIT_EMPTY_EVERY == 0
            for e in self.entries:
                e.seen_now = False
                e.score_now = None
        with step("fingerprint"):
            W, C = soft_maps(crop, self.usable_f) if self.entries else (None, None)
            # Each entry searches every row it could have risen to, and a few
            # below; then the order decides: entries keep their queue order
            # and stand SLOT_GAP apart in template rows; of two claiming one slot the
            # better score keeps it. A held entry above a verified newer one
            # was passed, so it is gone.
            cands = []
            for e in self.entries:
                y, score = self._verify(e, W, C, 0, e.top + SEARCH_DOWN)
                e.score_now = score
                cands.append([e, y, score, y is not None and score >= self.cut])
            acc: list[int] = []
            for i, c in enumerate(cands):
                if not c[3]:
                    continue
                while acc:
                    p = cands[acc[-1]]
                    if c[1] >= p[1] + SLOT_GAP:
                        break
                    if c[2] > p[2]:
                        p[3] = False
                        acc.pop()
                    else:
                        c[3] = False
                        break
                if c[3]:
                    acc.append(i)
            passed = set()
            for i, c in enumerate(cands):
                if c[3]:
                    continue
                for j in acc:
                    q = cands[j]
                    if j > i and q[1] < c[0].top + SLOT_GAP:
                        passed.add(c[0].id)
            failed = []
            for e, y, score, ok in cands:
                age = e.age_s(t)
                if e.id in passed:
                    d.verify.append({"t_ms": t, "id": e.id, "top": e.top, "best_y": y,
                                     "score": round(score, 4), "ok": False, "age_s": round(age, 2),
                                     "status": "passed", "wx0": e.wx0, "ally": e.ally,
                                     "off": e.off})
                    continue
                row = {"t_ms": t, "id": e.id, "top": e.top, "best_y": y, "score": round(score, 4),
                       "ok": ok, "age_s": round(age, 2), "status": e.status, "wx0": e.wx0,
                       "ally": e.ally, "off": e.off}
                d.verify.append(row)
                if ok and y > e.top + AUDIT_TOL + 1:
                    d.surprises.append(("fall", e.id, {"from": e.top, "to": y}))
                    failed.append(e)
                elif ok:
                    e.top = int(y)
                    e.seen_now = True
                    e.last_seen = t
                    if age > LIFETIME_S and not e.overdue_flagged:
                        e.overdue_flagged = True
                        e.status = "overdue"
                        d.surprises.append(("overdue", e.id, {"age_s": round(age, 2)}))
                    elif e.status == "predicted":
                        e.status = "resting"      # re-acquired; scope prior
                        row["reacquired"] = True
                else:
                    failed.append(e)
            for e in [e for e in self.entries if e.id in passed]:
                self.entries.remove(e)
                self.ended["passed_by_rise"] += 1
            gone, kept = [], []
            for e in failed:
                age = e.age_s(t)
                if any(s[1] == e.id for s in d.surprises):
                    kept.append(e)
                elif self._occluded_frac(e, e.top) >= OCCLUDED_FRAC:
                    e.status = "predicted"
                    self.predicted_rows.append({"t_ms": t, "id": e.id, "top": e.ptop,
                                                "reason": "overlay_mask", "rests_on": RESTS_ON,
                                                "last_seen_ms": e.last_seen})
                    kept.append(e)
                elif age >= LIFETIME_S - DUE_SLACK_S:
                    gone.append(e)
                else:
                    kept.append(e)
            early = [e for e in kept if e.status != "predicted"
                     and not any(s[1] == e.id for s in d.surprises)]
            alive = [e for e in self.entries if e.seen_now]
            if early and not alive and len(self.entries) >= 2:
                d.surprises.append(("stack_gone", None, {"ids": [e.id for e in self.entries]}))
            else:
                for e in early:
                    d.surprises.append(("missing_early", e.id, {"age_s": round(e.age_s(t), 2),
                                                                "score": round(e.score_now, 4)}))
            for e in gone:
                self.entries.remove(e)
                self.ended["expired"] += 1
        with step("probe"):
            usable = self.usable if self.usable is not None else np.ones(crop.shape[:2], bool)
            green, red, _white = kf._plate_masks(crop, usable)
            bands = kf._entry_bands(green, red, usable, self.prefix, self.scale)
            d.bands = [(int(a), int(z)) for a, z in bands]
            present = [e for e in self.entries if e.seen_now or e.status == "predicted"
                       or e.age_s(t) < LIFETIME_S - DUE_SLACK_S]
            tops = [e.ptop for e in present]
            lowest = max(tops) if tops else None
            # The probe slot, then each consecutive slot below an arrival.
            expect = (lowest + PITCH_PX) if lowest is not None else FIRST_TOP
            for a, z in sorted(d.bands):
                if any(abs(a - tp) <= BAND_TOL for tp in tops):
                    continue
                if lowest is not None and a < lowest:
                    d.surprises.append(("arrival_above", None, {"band": [a, z]}))
                elif abs(a - expect) <= BAND_TOL:
                    d.need_parse.append("arrival")
                    expect = a + PITCH_PX
                else:
                    d.surprises.append(("extra_band", None, {"band": [a, z]}))
        if d.surprises:
            d.need_parse.append("surprise")
        if d.audit:
            d.need_parse.append("audit")
        return d, (W, C, green, red, crop)

    def post(self, d: Decision, views, maps) -> None:
        """Read the parse where `pre` asked; tag every view; store rows."""
        W, C, green, red, crop = maps
        t = d.t
        if W is None and d.need_parse:
            from reticle.usage import step
            with step("fingerprint"):
                W, C = soft_maps(crop, self.usable_f)
        ents = [v for v in views if v.verdict != "empty_band"]
        parse_tops = sorted(int(v.y0) for v in ents)
        follow_tops = sorted(e.ptop for e in self.entries if e.seen_now)
        reasons = sorted(set(d.need_parse))
        # Where the follow asked for the parse for its own reasons (not the
        # audit's), its answer is the parse's. Elsewhere it is its verified
        # tops: compared for presence (each entry within BAND_TOL, the parse's
        # band top jitters by up to 6 rows on a resting plate) and for
        # position beyond AUDIT_TOL (the plan's 1 px).
        anyway = bool(set(reasons) - {"audit"})
        present_ok = _same_tops(follow_tops, parse_tops, BAND_TOL)
        pos_ok = _same_tops(follow_tops, parse_tops, AUDIT_TOL)
        agree = anyway or present_ok
        raw_agree = pos_ok
        self.agree_rows.append({"t_ms": t, "parse": bool(reasons), "reasons": reasons,
                                "audit": d.audit, "agree": agree, "raw_agree": raw_agree,
                                "anyway": anyway, "present_ok": present_ok,
                                "n_follow": len(follow_tops), "n_parse": len(parse_tops),
                                "predicted_nonempty": d.predicted_nonempty})
        self.verify_rows.extend(d.verify)
        if d.audit and "seed" not in reasons:
            self.audit_rows.append({
                "t_ms": t, "kind": "audit", "follow": follow_tops, "parse": parse_tops,
                "predicted_nonempty": d.predicted_nonempty, "disagree": not agree,
                "pos_disagree": not (anyway or pos_ok), "reasons": reasons,
                "surprise": bool(d.surprises),
                "verify": [{"id": r["id"], "best_y": r["best_y"], "score": r["score"],
                            "label": _label(r, ents)} for r in d.verify]})
        surprise_ids = {s[1] for s in d.surprises if s[1] is not None}
        new_ids: set[int] = set()
        if reasons:
            new_ids = self._reseed(d, ents, (W, C), green, red)
            self.parse_rows.append({"t_ms": t, "reasons": reasons, "parse": parse_tops,
                                    "new": sorted(new_ids)})
        if d.surprises:
            for kind, eid, detail in d.surprises:
                self.surprise_rows.append({"t_ms": t, "kind": kind, "id": eid, "detail": detail,
                                           "parse": parse_tops, "follow": follow_tops,
                                           "new": sorted(new_ids)})
            # Entries the surprise names, and entries its parse seeded, are its views.
            surprise_ids |= new_ids
        # Tag every view the reader described.
        used: set[int] = set()
        for v in sorted(ents, key=lambda v: v.y0):
            best = None
            for e in self.entries:
                if e.id in used or abs(e.ptop - int(v.y0)) > ASSOC_TOL:
                    continue
                if best is None or abs(e.ptop - v.y0) < abs(best.ptop - v.y0):
                    best = e
            key = (float(t), int(v.y0))
            self.slot_keys[(float(t), int(v.slot))] = key
            if best is None:
                self.tags[key] = {"id": None, "view": None, "scope": "unfollowed",
                                  "surprise": False}
                continue
            used.add(best.id)
            if best.seen_now:
                self.tags[key] = {"id": best.id, "view": best.n_views,
                                  "scope": "parsed" if reasons else "verified",
                                  "surprise": best.id in surprise_ids}
                best.n_views += 1
            else:
                self.tags[key] = {"id": best.id, "view": None, "scope": "predicted",
                                  "surprise": False, "rests_on": RESTS_ON}

    def _reseed(self, d: Decision, ents, maps, green, red) -> set[int]:
        """Continue each parsed band's entry where its template verifies on it
        (or its trusted divider and victim side agree), in order; seed the rest."""
        W, C = maps
        t = d.t
        old = list(self.entries)
        out: list[Entry] = []
        new_ids: set[int] = set()
        i = 0
        for v in sorted(ents, key=lambda v: v.y0):
            a = int(v.y0)
            wx = int(v.wx0) if (v.killer_run and v.victim_run) else 0
            hit = None
            for j in range(i, len(old)):
                e = old[j]
                if a > e.ptop + BAND_TOL:
                    continue                          # the band lies below e
                y, score = self._verify(e, W, C, a - BAND_TOL, a + BAND_TOL)
                same_div = wx and e.wx0 and abs(wx - e.wx0) <= 2 and v.victim_ally == e.ally
                if y is not None and score >= self.cut:
                    hit, hit_y = j, int(y)
                    break
                if same_div:
                    hit, hit_y = j, a + e.off
                    break
            if hit is not None:
                e = old[hit]
                # Entries above the hit that no band continues are passed over.
                for e2 in old[i:hit]:
                    self._unseen(e2, t, out)
                i = hit + 1
                e.top, e.off = hit_y, hit_y - a
                e.seen_now = True
                e.last_seen = t
                if e.status == "predicted":
                    e.status = "resting"
                out.append(e)
            else:
                e = self._new_entry(v, (W, C), green, red, t)
                e.seen_now = True
                new_ids.add(e.id)
                out.append(e)
        for e2 in old[i:]:
            self._unseen(e2, t, out)
        # The queue: an entry held only as a prediction cannot sit below a
        # newer entry; one that does is gone.
        newest_top = max((e.ptop for e in out if e.id in new_ids), default=None)
        final = []
        for e in sorted(out, key=lambda e: e.ptop):
            if (e.status == "predicted" and not e.seen_now and newest_top is not None
                    and e.ptop > newest_top):
                self.ended["passed_by_arrival"] += 1
                continue
            final.append(e)
        self.entries = final
        return new_ids

    def _unseen(self, e: Entry, t: float, out: list) -> None:
        if e.seen_now:
            out.append(e)                      # verified, though the parse lacks it
            return
        if e.age_s(t) < LIFETIME_S - DUE_SLACK_S:
            e.status = "predicted"
            self.predicted_rows.append({"t_ms": t, "id": e.id, "top": e.ptop,
                                        "reason": "unseen", "rests_on": RESTS_ON,
                                        "last_seen_ms": e.last_seen})
            out.append(e)
        else:
            self.ended["expired_unseen"] += 1


def _same_tops(a: list[int], b: list[int], tol: int) -> bool:
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(sorted(a), sorted(b)))


def _label(r: dict, ents) -> bool | None:
    """Audit label of one verify: the parse holds a band at its best row
    whose victim side matches the entry's, and whose divider does where both
    are trusted. Another entry risen into the row is not this one."""
    if r["best_y"] is None:
        return None
    for v in ents:
        if abs(int(v.y0) - (r["best_y"] - r["off"])) > BAND_TOL:
            continue
        wx = int(v.wx0) if (v.killer_run and v.victim_run) else 0
        if r["ally"] is not None and v.victim_ally is not None and r["ally"] != v.victim_ally:
            continue
        if wx and r["wx0"] and abs(wx - r["wx0"]) > 2:
            continue
        return True
    return False


# --------------------------------------------------------------------- reader

class FollowReader:
    """`KillfeedPortraitReader` with the follow run before its parse."""

    def __init__(self, ctx, cut: float):
        from reticle.killfeed import KillfeedPortraitReader, killfeed_roi
        self.inner = KillfeedPortraitReader(ctx.profile, ctx.wh, mask=ctx.kf_mask(), hz=2.0,
                                            spans=None)
        self.name = self.inner.name
        self.cache_set = self.inner.cache_set
        self.roi = killfeed_roi(ctx.profile)
        self.w, self.h = ctx.wh
        from reticle.killfeed import KillfeedScale
        self.follow = Follow(self.inner.mask, cut, KillfeedScale.for_capture(self.w, self.h))
        self.samples: list[dict] = []

    @property
    def frames_from(self):
        return self.inner.frames_from

    @frames_from.setter
    def frames_from(self, v):
        self.inner.frames_from = v

    def feed(self, smp) -> None:
        from reticle import killfeed as kf
        from reticle import usage
        sink = getattr(usage._LOCAL, "sink", None)
        snap = lambda: ({k: v.total_ns for k, v in sink.steps.items()} if sink else {})
        before = snap()
        x0, y0, x1, y1 = self.roi.pixels(self.w, self.h)
        crop = smp.frame[y0:y1, x0:x1]
        d, maps = self.follow.pre(float(smp.t_ms), crop, usage.step)
        got = {}
        orig = kf.analyse_killfeed

        def capture(*a, **k):
            got["views"] = orig(*a, **k)
            return got["views"]
        kf.analyse_killfeed = capture
        try:
            self.inner.feed(smp)
        finally:
            kf.analyse_killfeed = orig
        views = got.get("views", [])
        self.follow.post(d, views, maps)
        after = snap()
        ns = {k: after.get(k, 0) - before.get(k, 0) for k in after}
        self.samples.append({"t_ms": float(smp.t_ms),
                             "n_views": sum(v.verdict != "empty_band" for v in views),
                             "parse": sorted(set(d.need_parse)),
                             "ns": {k: v for k, v in ns.items() if v}})


# ---------------------------------------------------------------------- trial

def _tag_of(follow: Follow, row: dict) -> dict | None:
    """A descriptor row's tag by its view's band top, else by its slot (a
    portrait row's y0 carries its band shift)."""
    t = float(row["t_ms"])
    tag = follow.tags.get((t, int(row["y0"]))) if "y0" in row else None
    if tag is None and "slot" in row:
        key = follow.slot_keys.get((t, int(row["slot"])))
        tag = follow.tags.get(key) if key else None
    return tag


def keep_row(tag: dict | None, k) -> bool:
    """Whether a descriptor row is read at k: one of the entry's first k
    observed views, or a surprise view; k == "all" keeps every observed view."""
    if tag is None or tag["id"] is None or tag["scope"] == "predicted":
        return False
    if tag["surprise"]:
        return True
    return k == "all" or tag["view"] < k


def trial(sid: str, out: Path, cut: float, between=None, deaths: bool = True) -> dict:
    import time
    from reticle import trial as tr
    from reticle.cli import death_streams
    from reticle.store import Store
    from killfeed_trial_deaths import merged_events, merged_hud

    store = Store()
    out = out.resolve()
    if Path(store.root).resolve() in [out, *out.parents]:
        raise SystemExit("--out must lie outside the store")
    man = store.read_manifest(sid)
    sid = man["session_id"]
    holder = {}

    def build(ctx):
        holder["r"] = FollowReader(ctx, cut)
        return holder["r"]

    def rows(reader, s):
        return tr._killfeed_rows(reader.inner, s)

    tr.TRIAL_READERS["killfeed_follow"] = (
        "killfeed", build, rows, ("killfeed_portrait", "killfeed_weapon", "killfeed_name"),
        tr._hud_timeline)
    t0 = time.perf_counter()
    hud_t = tr.run(store, man, reader="hud", source="cache", windows="all", between=between)
    kf_t = tr.run(store, man, reader="killfeed_follow", source="cache", windows="all",
                  between=between)
    reader: FollowReader = holder["r"]
    fol = reader.follow
    hud, hit = merged_hud(store.read_hud(sid, man["ingested_at"][:10]), hud_t["rows"]["hud"])
    at = {float(r["t_ms"]) for r in hud_t["rows"]["hud"]}
    kat = set(at)
    for rs in kf_t["rows"].values():
        kat |= {float(r["t_ms"]) for r in rs if "t_ms" in r}
    obs = lambda r: str(r.get("kind", "")).endswith("_observation")
    tag_counts = Counter()
    for s, rs in kf_t["rows"].items():
        for r in rs:
            if obs(r):
                tg = _tag_of(fol, r)
                tag_counts[(s, "untagged" if tg is None else tg["scope"])] += 1
    builds = {}
    for k in (("master", "all") + KS) if deaths else ():
        trial_rows = {s: [r for r in rs if not obs(r)
                          or k == "master" or keep_row(_tag_of(fol, r), k)]
                      for s, rs in kf_t["rows"].items()}
        streams = {s: merged_events(store.read_events(s, sid) or [], trial_rows[s], kat)
                   for s in ("killfeed_portrait", "killfeed_weapon", "killfeed_name")}
        if between is not None:
            # Outside the window the stored rows stand in; inside, the trial's.
            pass
        dd = death_streams(store, man, hud=hud, portraits=streams["killfeed_portrait"],
                           weapons=streams["killfeed_weapon"], names=streams["killfeed_name"])
        p = out / f"k_{k}" / "events" / "death" / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for r in [dd["head"]] + dd["rows"] + dd["collisions"]:
                f.write(json.dumps(r, default=str) + "\n")
        builds[str(k)] = {"deaths": len(dd["rows"]) - dd["head"]["revives"],
                          "revives": dd["head"]["revives"],
                          "rows_kept": {s: sum(obs(r) for r in rs)
                                        for s, rs in trial_rows.items()}}
    meta = {"session_id": sid, "version": FOLLOW_VERSION, "cut": cut, "between": between,
            "hud_frames": hud_t["frames"], "hud_replaced": hit, "kf_frames": kf_t["frames"],
            "refused": kf_t["refused"], "usage": kf_t["usage"], "kf_seconds": kf_t["seconds"],
            "wall_s": round(time.perf_counter() - t0, 1), "builds": builds,
            "tags": {f"{s}:{c}": n for (s, c), n in sorted(tag_counts.items())},
            "ended": dict(fol.ended)}
    fdir = out / "follow"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / f"{sid}.meta.json").write_text(json.dumps(meta, indent=1, default=str), "utf-8")
    for name, rs in (("surprise", fol.surprise_rows), ("audit", fol.audit_rows),
                     ("predicted", fol.predicted_rows), ("parse", fol.parse_rows),
                     ("agree", fol.agree_rows), ("verify", fol.verify_rows),
                     ("samples", reader.samples)):
        with (fdir / f"{sid}.{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r, default=str) + "\n")
    with (fdir / f"{sid}.tags.jsonl").open("w", encoding="utf-8") as f:
        for (t, y), tg in sorted(fol.tags.items()):
            f.write(json.dumps({"t_ms": t, "y0": y, **tg}) + "\n")
    return meta


# ------------------------------------------------------------------- analysis

def _rows_of(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def fit(dirs: list[Path]) -> dict:
    """The one cut, from audit rows: labelled verifies (the parse holds a band
    at the best row, or not); the cut minimises misclassified rows, midpoint
    of the best interval."""
    rows = []
    for d in dirs:
        for p in sorted((d / "follow").glob("*.audit.jsonl")):
            for r in _rows_of(p):
                rows += [v for v in r["verify"] if v["label"] is not None]
    pos = np.array([v["score"] for v in rows if v["label"]])
    neg = np.array([v["score"] for v in rows if not v["label"]])
    cands = np.unique(np.concatenate([pos, neg, [-1.0, 1.0]]))
    errs = [(int((pos < c).sum() + (neg >= c).sum()), c) for c in cands]
    best = min(e for e, _ in errs)
    good = [c for e, c in errs if e == best]
    # The interval of cuts with the fewest errors: take its middle.
    lo = max([s for s in neg if s < good[0]], default=good[0])
    cut = round(float((lo + good[0]) / 2), 3) if lo < good[0] else float(good[0])
    q = lambda a: [round(float(x), 3) for x in np.percentile(a, [1, 5, 50, 95, 99])] if len(a) else []
    return {"rows": len(rows), "pos": len(pos), "neg": len(neg), "errors_at_cut": best,
            "cut": cut, "pos_pct_1_5_50_95_99": q(pos), "neg_pct_1_5_50_95_99": q(neg)}


BUILDS = ("master", "all") + tuple(str(k) for k in KS)
SCORE_KEYS = ("riot_kills", "stored_deaths", "matched", "matched_kind_ability", "riot_kind_ability",
              "victim_right", "victim_wrong", "victim_refused", "killer_right", "killer_wrong",
              "killer_refused", "weapon_right", "weapon_wrong", "weapon_refused")


def riot_scores(d: Path, sid: str) -> dict:
    """`riot_ground_truth.py SID --no-minimap --no-status --offline
    --deaths-from DIR/k_<k> --json`, once per build, cached in DIR/scores."""
    import subprocess
    out = {}
    (d / "scores").mkdir(exist_ok=True)
    for b in BUILDS:
        j = d / "scores" / f"{sid}.{b}.json"
        if not j.is_file():
            subprocess.run([sys.executable, str(Path(__file__).parent / "riot_ground_truth.py"), sid,
                            "--no-minimap", "--no-status", "--offline",
                            "--deaths-from", str(d / f"k_{b}"), "--json", str(j)],
                           check=True, stdout=subprocess.DEVNULL)
        out[b] = json.loads(j.read_text("utf-8"))["sessions"][0]
    return out


def _items(ss: dict) -> dict:
    """Matched kills keyed by Riot's side of the pair (round, victim, killer,
    weapon, n-th such), holding the stored names."""
    seen, items = Counter(), {}
    for r in ss["death_rows"]:
        k = (r["round"], r["victim"][0], r["killer"][0], r["weapon"][0])
        seen[k] += 1
        items[k + (seen[k],)] = r
    return items


def _wrong(r: dict, role: str) -> bool:
    truth, got = r[role]
    return got is not None and truth is not None and str(got).lower() != str(truth).lower()


def compare(base: dict, other: dict) -> dict:
    """What `other` changes against `base`: lost and gained matches, new
    false deaths, and names that became wrong or refused."""
    bi, oi = _items(base), _items(other)
    bf = {round(x["t_ms"]) for x in base["deaths"]["false"]}
    of = {round(x["t_ms"]) for x in other["deaths"]["false"]}
    ch = {"lost": [list(k) for k in bi if k not in oi], "gained": [list(k) for k in oi if k not in bi],
          "new_false": sorted(of - bf), "gone_false": sorted(bf - of),
          "new_wrong": [], "fixed": [], "new_refused": [], "named_now": []}
    for k in bi.keys() & oi.keys():
        a, b = bi[k], oi[k]
        for role in ("victim", "killer", "weapon"):
            if _wrong(b, role) and not _wrong(a, role):
                ch["new_wrong"].append([role, b["t_ms"], *b[role], a[role][1]])
            elif _wrong(a, role) and not _wrong(b, role):
                ch["fixed"].append([role, b["t_ms"], *b[role], a[role][1]])
            if b[role][1] is None and a[role][1] is not None:
                ch["new_refused"].append([role, b["t_ms"], a[role][1]])
            if a[role][1] is None and b[role][1] is not None:
                ch["named_now"].append([role, b["t_ms"], *b[role]])
    ch["floor_ok"] = not (ch["lost"] or ch["new_false"] or ch["new_wrong"])
    # The brief's floor counts wrong names; a name lost to a refusal is a
    # loss too, so the strict floor counts it.
    ch["strict_ok"] = ch["floor_ok"] and not ch["new_refused"]
    return ch


def table(dirs: list[Path]) -> dict:
    """The Riot scorer per session and build, pooled; each build against
    master and against k = all; the smallest k whose deaths lose no match,
    add no false death and add no wrong name against k = all on every
    session."""
    per, pooled = {}, {b: Counter() for b in BUILDS}
    for d in dirs:
        for mp in sorted((d / "follow").glob("*.meta.json")):
            sid = mp.name.split(".")[0]
            sc = riot_scores(d, sid)
            row = {b: {k: sc[b]["deaths"].get(k, 0) for k in SCORE_KEYS} for b in BUILDS}
            for b in BUILDS:
                row[b]["false"] = len(sc[b]["deaths"]["false"])
                pooled[b].update(row[b])
            row["vs_master"] = {b: compare(sc["master"], sc[b]) for b in BUILDS if b != "master"}
            row["vs_all"] = {b: compare(sc["all"], sc[b]) for b in BUILDS
                             if b not in ("master", "all")}
            per[sid] = row
    ok = {b: all(per[s]["vs_all"][b]["floor_ok"] for s in per) for b in BUILDS
          if b not in ("master", "all")}
    strict = {b: all(per[s]["vs_all"][b]["strict_ok"] for s in per) for b in ok}
    ok_master = all(per[s]["vs_master"]["all"]["floor_ok"] for s in per)
    smallest = next((b for b in (str(k) for k in KS) if ok[b]), "all")
    smallest_strict = next((b for b in (str(k) for k in KS) if strict[b]), "all")
    return {"pooled": {b: dict(v) for b, v in pooled.items()}, "per_session": per,
            "floor_vs_all": ok, "strict_vs_all": strict, "k_all_floor_vs_master": ok_master,
            "smallest_k_floor": smallest, "smallest_k_strict": smallest_strict}


def score(dirs: list[Path]) -> dict:
    """Per session: surprises by kind, audit disagreement, agreement on
    samples the follow parsed nothing, and the cost per k."""
    out = {}
    for d in dirs:
        for mp in sorted((d / "follow").glob("*.meta.json")):
            sid = mp.name.split(".")[0]
            out[sid] = session_summary(d, sid)
    return out


def session_summary(d: Path, sid: str) -> dict:
    f = d / "follow"
    meta = json.loads((f / f"{sid}.meta.json").read_text("utf-8"))
    sur = _rows_of(f / f"{sid}.surprise.jsonl")
    aud = _rows_of(f / f"{sid}.audit.jsonl")
    agr = _rows_of(f / f"{sid}.agree.jsonl")
    smp = _rows_of(f / f"{sid}.samples.jsonl")
    tags = {(r["t_ms"], r["y0"]): r for r in _rows_of(f / f"{sid}.tags.jsonl")}
    ver = _rows_of(f / f"{sid}.verify.jsonl")
    n = len(smp)
    parse_reasons = Counter(r for s in smp for r in s["parse"])
    sur_samples = len({r["t_ms"] for r in sur})
    aud_ne = [r for r in aud if r["predicted_nonempty"]]
    no_parse = [r for r in agr if not r["parse"]]
    # Cost: timed per-sample steps.
    tot = Counter()
    for s in smp:
        for k, v in s["ns"].items():
            tot[k] += v
    sec = lambda ns: round(ns / 1e9, 2)
    follow_ns = sum(tot[k] for k in FOLLOW_STEPS)
    today_ns = sum(v for k, v in tot.items() if k not in FOLLOW_STEPS)
    cost = {}
    by_t = {}
    for (t, y), tg in tags.items():
        by_t.setdefault(t, []).append(tg)
    for k in ("all",) + KS:
        parse_ns = desc_ns = 0
        for s in smp:
            ns = s["ns"]
            sel = sum(keep_row(tg, k) for tg in by_t.get(s["t_ms"], []))
            nv = s["n_views"]
            dns = sum(ns.get(x, 0) for x in DESCRIPTOR_STEPS)
            if nv:
                desc_ns += dns * sel / nv
            if s["parse"] or sel:
                parse_ns += ns.get("entries", 0)
        cost[str(k)] = {"follow_s": sec(follow_ns), "parse_s": sec(parse_ns),
                        "descriptor_s": sec(desc_ns),
                        "total_s": sec(follow_ns + parse_ns + desc_ns)}
    sc = np.array([v["score"] for v in ver if v["ok"]]) if ver else np.zeros(0)
    return {
        "samples": n, "parse_reasons": dict(parse_reasons),
        "surprise_samples": sur_samples,
        "surprise_share": round(sur_samples / n, 4) if n else None,
        "surprises_by_kind": dict(Counter(r["kind"] for r in sur)),
        "audit_rows": len(aud), "audit_nonempty": len(aud_ne),
        "audit_disagree_nonempty": sum(r["disagree"] for r in aud_ne),
        "audit_disagree_all": sum(r["disagree"] for r in aud),
        "audit_pos_disagree_nonempty": sum(r["pos_disagree"] for r in aud_ne),
        "audit_parsed_anyway_nonempty": sum(bool(set(r["reasons"]) - {"audit"}) for r in aud_ne),
        "no_parse_samples": len(no_parse), "no_parse_agree": sum(r["agree"] for r in no_parse),
        "no_parse_pos_agree": sum(r["raw_agree"] for r in no_parse),
        "verified_score_median": round(float(np.median(sc)), 3) if len(sc) else None,
        "tags": meta["tags"], "ended": meta["ended"],
        "timed_s": {k: sec(v) for k, v in sorted(tot.items())},
        "timed_today_s": sec(today_ns), "cost_by_k": cost,
        "builds": meta["builds"], "cut": meta["cut"],
    }


def sheet(d: Path, kind: str, out_png: Path, n: int = 30, sid: str | None = None,
          seed: int = 0) -> list[dict]:
    """Crop sheets of surprise rows of one kind (or `audit` disagreements):
    the sample before, at and after, the killfeed crop at native size."""
    import cv2
    import random
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    from reticle.killfeed import killfeed_roi
    store = Store()
    rows = []
    for p in sorted((d / "follow").glob("*.surprise.jsonl" if kind != "audit"
                                         else "*.audit.jsonl")):
        s = p.name.split(".")[0]
        if sid and s != sid:
            continue
        for r in _rows_of(p):
            if (r["disagree"] if kind == "audit" else (kind == "any" or r.get("kind") == kind)):
                rows.append({**r, "sid": s})
    random.Random(seed).shuffle(rows)
    rows = sorted(rows[:n], key=lambda r: (r["sid"], r["t_ms"]))
    tiles = []
    for s in sorted({r["sid"] for r in rows}):
        man = store.read_manifest(s)
        prof = get_profile(man["source_profile"])
        cache, _ = RoiCache.load(store.root, man, prof, "killfeed")
        x0, y0, x1, y1 = killfeed_roi(prof).pixels(*cache.record["wh"])
        mine = [r for r in rows if r["sid"] == s]
        ts = sorted({float(r["t_ms"] + dt) for r in mine for dt in (-500, 0, 500)})
        frames = {smp.t_ms: smp.frame[y0:y1, x0:x1] for smp in cache.samples(ts, rois="killfeed")}
        for r in mine:
            row = []
            for dt in (-500, 0, 500):
                fr = frames.get(float(r["t_ms"] + dt))
                fr = np.zeros((y1 - y0, x1 - x0, 3), np.uint8) if fr is None else fr.copy()
                if dt == 0:
                    for tp in r.get("parse", []):
                        cv2.line(fr, (0, tp), (6, tp), (0, 255, 255), 1)
                    for tp in r.get("follow", []):
                        cv2.line(fr, (fr.shape[1] - 7, tp), (fr.shape[1] - 1, tp), (255, 0, 255), 1)
                row.append(fr)
                row.append(np.full((fr.shape[0], 3, 3), 128, np.uint8))
            img = np.hstack(row)
            lab = np.zeros((16, img.shape[1], 3), np.uint8)
            cv2.putText(lab, f"{s} {r['t_ms'] / 1000:.1f}s {r.get('kind', 'audit')} "
                             f"id={r.get('id')} {json.dumps(r.get('detail', ''))[:60]}",
                        (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            tiles.append(np.vstack([lab, img]))
    if tiles:
        w = max(t.shape[1] for t in tiles)
        tiles = [np.pad(t, ((0, 0), (0, w - t.shape[1]), (0, 0))) for t in tiles]
        cv2.imwrite(str(out_png), np.vstack(tiles))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("trial")
    a.add_argument("session")
    a.add_argument("--out", required=True)
    a.add_argument("--cut", type=float, default=CUT)
    a.add_argument("--between", type=float, nargs=2, default=None, help="seconds")
    a.add_argument("--no-deaths", action="store_true", help="tag and time only")
    b = sub.add_parser("fit")
    b.add_argument("dirs", nargs="+")
    c = sub.add_parser("score")
    c.add_argument("dirs", nargs="+")
    t = sub.add_parser("table")
    t.add_argument("dirs", nargs="+")
    e = sub.add_parser("sheet")
    e.add_argument("dir")
    e.add_argument("kind")
    e.add_argument("out_png")
    e.add_argument("--n", type=int, default=30)
    e.add_argument("--sid", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "trial":
        _below_normal()
        btw = tuple(x * 1000.0 for x in args.between) if args.between else None
        meta = trial(args.session, Path(args.out), args.cut, btw, not args.no_deaths)
        print(json.dumps({k: v for k, v in meta.items() if k != "usage"}, indent=1, default=str))
    elif args.cmd == "fit":
        print(json.dumps(fit([Path(x) for x in args.dirs]), indent=1))
    elif args.cmd == "score":
        print(json.dumps(score([Path(x) for x in args.dirs]), indent=1))
    elif args.cmd == "table":
        res = table([Path(x) for x in args.dirs])
        Path(args.dirs[0], "table.json").write_text(json.dumps(res, indent=1), "utf-8")
        print(json.dumps({k: v for k, v in res.items() if k != "per_session"}, indent=1))
    elif args.cmd == "sheet":
        rows = sheet(Path(args.dir), args.kind, Path(args.out_png), args.n, args.sid)
        print(f"{len(rows)} rows -> {args.out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
