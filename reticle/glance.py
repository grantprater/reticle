"""One grammar for every perceptual question this project asks itself.

    .\\.venv\\Scripts\\python.exe -m reticle.glance --self-test
    .\\.venv\\Scripts\\python.exe -m reticle.glance answer <sheet> --answers 01=yes,02=no
    .\\.venv\\Scripts\\python.exe -m reticle.glance calibration

Why this exists
---------------
`notes/predictions.jsonl` holds the only measurement of my own sensory fidelity
in this repo, and its first read is brutal: **claims about what a rendered image
contains, 5 of 5 wrong at a mean stated confidence of 0.85.** Five-for-five
wrong is not a throughput failure -- throughput failures produce uncertainty,
not confident wrongness -- so more pixels would only have made all five claims
wrong at higher resolution. Two things actually cause it:

* **acuity against feature size.** The enemy rim is 1-4 px (see the capture note
  on 4:2:0). A whole 1080p frame reaches a model downsampled to roughly a
  thousand tokens, so the thing this project measures is BELOW the delivered
  sensory floor. The fix is not a bigger image, it is magnification at a stated
  factor: a 200x200 crop at 4x costs about what the full frame costs and
  resolves the rim. `overlay --scale` already carries this bug in the other
  direction -- text is rasterised before scaling, so the debug view silently
  degrades its own signal depending on a flag;
* **no pooling.** Every debug view here is bespoke -- the killfeed contact sheet
  was built in a scratch script, `label_dynamic` invented its own panel layout,
  `paint_map` another -- so an error rate measured on killfeed bands says
  nothing about minimap glyphs, and calibration restarts at n=1 in every module.

So this module is not a nicer renderer. It is a FIXED ENCODING, whose point is
that error rates measured through it are poolable across domains, and whose unit
of honesty is the control.

The structure everything folds into
-----------------------------------
**A sheet is a backdrop plus ringed items, each answered from a closed set.**
That covers all six question shapes without six renderers:

    present      is the ringed thing an X?          per-item, closed set
    which_of_k   which of these k references is it? per-item, refs on the sheet
    boundary     inside or outside this region?     ringed probes over an overlay
    count        how many?                          sheet-level integer
    correspond   are these two the same thing?      per-item over aligned pairs
    ordering     what order did these happen in?    sheet-level permutation

Invariants, enforced here rather than remembered
------------------------------------------------
* magnification is **INTER_NEAREST**, always, and the factor is printed on every
  panel. Minification is INTER_AREA and is printed with a `v` marker, because a
  minified panel has had detail destroyed and the sheet must say so;
* a **10-source-pixel scale bar** on every panel. Without it a magnified crop
  and a native one are indistinguishable, which is how a 2 px rim gets argued
  about as though it were a shape;
* the candidate is **ringed in every panel it appears in**. The tile is not the
  object -- a 36 px minimap crop routinely holds a cam AND two X marks AND a
  dropped spike -- so the question has to point;
* out-of-source padding is filled with the **void** colour, never silently
  clipped, so "there is no data here" and "there is nothing here" cannot be
  confused;
* **structural colour is about the QUESTION, domain colour is about the ANSWER.**
  The five roles below never mean anything else on any sheet. `occluded` is
  amber and `void` is magenta everywhere, matching `overlay.py`.

The control is the mechanism
----------------------------
Each sheet plants items whose answer is already known, shuffled in and
indistinguishable. The footer states HOW MANY there are and not which. If the
controls are missed the sheet is scored `VOID` and its other answers are
discarded, not merely doubted.

Controls must come from someone else's labels. `truth_source` is required, and
`answer()` refuses a sheet whose controls trace back to a `claude-*` provenance
-- that is the seeding mistake in a new costume: seeding `minimap_agent` with
provisional rows produced a number that was scoring my own clustering against
itself. A control built from my own prior claim measures nothing.

This is a self-honesty instrument, not an adversarial one. The key file sits
next to the sheet and could simply be read. What makes the number mean anything
is that the truth is GRANT'S, written before the question was asked, and that
the answer file is written before the score is revealed.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ENCODING = "glance-1"
STORE = Path.home() / "reticle-store"

# Structural roles. BGR, and deliberately the same values overlay.py uses for
# the two that overlap, so amber and magenta carry one meaning in this repo.
RING = (64, 255, 64)        # the thing you are being asked about
CONTEXT = (150, 150, 150)   # supporting pixels, not the question
MEASURE = (255, 255, 255)   # scale bars, ids, magnification
OCCLUDED = (60, 180, 245)   # something covers the evidence here
VOID = (200, 90, 200)       # no data: off the source, unparsed, missing
PAPER = (28, 24, 22)        # sheet background, matching overlay.PANEL

ROLES = [("ring", RING, "the question"), ("context", CONTEXT, "context"),
         ("measure", MEASURE, "scale/id"), ("occluded", OCCLUDED, "covered"),
         ("void", VOID, "no data")]

FONT = cv2.FONT_HERSHEY_SIMPLEX
CANT_TELL = "cant-tell"     # always available, always kept out of scoring


@dataclass
class Item:
    """One ringed thing, and everything needed to draw and score it.

    `truth` is set ONLY on controls. `note` is printed under the panel and must
    never narrow the answer -- a timestamp is fine, "probably a cam" is not.
    """

    image: np.ndarray                    # source the crop is taken from, BGR
    box: tuple[int, int, int, int]       # x, y, w, h in SOURCE pixels
    key: str                             # stable identity, e.g. "t=1320129 x=252"
    truth: str | None = None
    note: str = ""
    overlay: np.ndarray | None = None    # optional bool mask, drawn as OCCLUDED

    @property
    def is_control(self) -> bool:
        return self.truth is not None


@dataclass
class Sheet:
    sheet_id: str
    kind: str
    question: str
    classes: list[str]
    scope: str                           # "per_item" | "sheet"
    image: np.ndarray
    order: list[str]                     # display ids, in reading order
    manifest: dict
    key: dict
    warnings: list[str] = field(default_factory=list)

    def write(self, out_dir: Path | None = None) -> Path:
        d = Path(out_dir) if out_dir else STORE / "glances"
        d.mkdir(parents=True, exist_ok=True)
        png = d / f"{self.sheet_id}.png"
        cv2.imwrite(str(png), self.image)
        (d / f"{self.sheet_id}.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8")
        (d / f"{self.sheet_id}.key.json").write_text(
            json.dumps(self.key, indent=2), encoding="utf-8")
        return png


# --------------------------------------------------------------------------
# drawing primitives
# --------------------------------------------------------------------------

def _text(img, s, org, colour=MEASURE, scale=0.38, thick=1):
    cv2.putText(img, s, org, FONT, scale, colour, thick, cv2.LINE_AA)


def _text_w(s, scale=0.38, thick=1):
    return cv2.getTextSize(s, FONT, scale, thick)[0][0]


def _wrap(s: str, width_px: int, scale=0.42) -> list[str]:
    out, line = [], ""
    for word in s.split():
        trial = f"{line} {word}".strip()
        if _text_w(trial, scale) > width_px and line:
            out.append(line)
            line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out


def _crop(img, box, pad):
    """Crop with `pad` source pixels of margin, filling off-source with VOID.

    Returns the tile, the box in tile coordinates, and the fraction of the tile
    that had no source behind it. Never clips silently: a candidate at the edge
    of the ROI must LOOK like it is at the edge.
    """
    x, y, w, h = box
    x0, y0, x1, y1 = x - pad, y - pad, x + w + pad, y + h + pad
    tile = np.empty((y1 - y0, x1 - x0, 3), np.uint8)
    tile[:] = VOID
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(img.shape[1], x1), min(img.shape[0], y1)
    covered = 0
    if sx1 > sx0 and sy1 > sy0:
        tile[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
        covered = (sx1 - sx0) * (sy1 - sy0)
    return tile, (x - x0, y - y0, w, h), 1.0 - covered / float(tile.shape[0] * tile.shape[1])


def _panel(item: Item, disp_id: str, zoom: int, pad: int, caption: str = ""):
    """One magnified, ringed, scale-barred crop. The unit of the whole grammar."""
    src = item.image
    if item.overlay is not None:
        src = src.copy()
        m = item.overlay.astype(bool)
        src[m] = (0.45 * np.array(OCCLUDED) + 0.55 * src[m]).astype(np.uint8)

    tile, (bx, by, bw, bh), void_frac = _crop(src, item.box, pad)
    interp = cv2.INTER_NEAREST if zoom >= 1 else cv2.INTER_AREA
    big = cv2.resize(tile, None, fx=zoom, fy=zoom, interpolation=interp)
    th = max(1, int(round(zoom / 2)))

    # ring: a rectangle 2 source px outside the box, so the box edge stays visible
    p = 2 * zoom
    cv2.rectangle(big, (int(bx * zoom - p), int(by * zoom - p)),
                  (int((bx + bw) * zoom + p), int((by + bh) * zoom + p)), RING, th)

    head, foot = 15, 17
    out = np.empty((big.shape[0] + head + foot, big.shape[1], 3), np.uint8)
    out[:] = PAPER
    out[head:head + big.shape[0]] = big

    mag = f"{zoom}x" if zoom >= 1 else f"v{zoom:g}x"
    _text(out, disp_id, (2, 11), MEASURE, 0.4)
    _text(out, mag, (out.shape[1] - _text_w(mag, 0.36) - 3, 11),
          MEASURE if zoom >= 1 else VOID, 0.36)

    # 10-source-pixel scale bar, bottom left of the image area
    bar = int(10 * zoom)
    yb = head + big.shape[0] - 4
    cv2.line(out, (4, yb), (4 + bar, yb), MEASURE, 1)
    cv2.line(out, (4, yb - 3), (4, yb + 1), MEASURE, 1)
    cv2.line(out, (4 + bar, yb - 3), (4 + bar, yb + 1), MEASURE, 1)
    _text(out, "10px", (4 + bar + 4, yb + 2), MEASURE, 0.32)

    cap = caption or item.note
    if void_frac > 0.001:
        cap = (cap + f"  void {void_frac:.0%}").strip()
    if cap:
        _text(out, cap[:44], (2, out.shape[0] - 5), CONTEXT, 0.34)
    cv2.rectangle(out, (0, 0), (out.shape[1] - 1, out.shape[0] - 1), CONTEXT, 1)
    return out, void_frac


def _grid(panels, cols, gap=6):
    if not panels:
        return np.full((1, 1, 3), PAPER, np.uint8)
    ch = max(p.shape[0] for p in panels)
    cw = max(p.shape[1] for p in panels)
    rows = (len(panels) + cols - 1) // cols
    out = np.empty((rows * (ch + gap) + gap, cols * (cw + gap) + gap, 3), np.uint8)
    out[:] = PAPER
    for i, p in enumerate(panels):
        r, c = divmod(i, cols)
        # Centre each panel in a uniform cell. Boxes vary a lot in size, so
        # laying panels flush left made the Lotus sheet read as a ragged pile
        # and cost real scanning effort -- a grid whose rows do not line up is
        # a worse contact sheet, and this encoding is only worth what a glance
        # can take off it.
        y = gap + r * (ch + gap) + (ch - p.shape[0]) // 2
        x = gap + c * (cw + gap) + (cw - p.shape[1]) // 2
        out[y:y + p.shape[0], x:x + p.shape[1]] = p
    return out


def _chrome(body, question, classes, scope, n_items, n_controls, sheet_id, warnings):
    """Legend above, footer below. Identical on every sheet, by design."""
    w = max(body.shape[1], 460)
    lines = _wrap(question, w - 16, 0.44)
    head_h = 20 + 17 * len(lines) + 20
    foot_h = 22 + 14 * (2 + len(warnings))
    out = np.empty((head_h + body.shape[0] + foot_h, w, 3), np.uint8)
    out[:] = PAPER
    y = 20
    for ln in lines:
        _text(out, ln, (8, y), MEASURE, 0.44)
        y += 17
    x = 8
    for name, colour, meaning in ROLES:
        cv2.rectangle(out, (x, y - 8), (x + 10, y + 1), colour, -1)
        _text(out, f"{name}={meaning}", (x + 14, y), CONTEXT, 0.32)
        x += 14 + _text_w(f"{name}={meaning}", 0.32) + 12
    out[head_h:head_h + body.shape[0], :body.shape[1]] = body

    y = head_h + body.shape[0] + 16
    ans = ("one answer per ringed item" if scope == "per_item"
           else "one answer for the whole sheet")
    _text(out, f"{ans}, from: {' / '.join(classes)}", (8, y), MEASURE, 0.38)
    y += 14
    _text(out, f"{sheet_id}  {ENCODING}  {n_items} items, "
               f"{n_controls} of them controls (which ones is not stated)",
          (8, y), CONTEXT, 0.34)
    for wmsg in warnings:
        y += 14
        _text(out, f"! {wmsg}", (8, y), VOID, 0.34)
    return out


# --------------------------------------------------------------------------
# the sheet builder every question kind goes through
# --------------------------------------------------------------------------

def build(items: list[Item], *, question: str, classes: list[str],
          kind: str = "present", scope: str = "per_item", zoom: int = 4,
          pad: int = 20, cols: int = 6, truth_source: str = "",
          extra_panels: list[np.ndarray] | None = None,
          domain: str = "vision", seed: int | None = None) -> Sheet:
    """Render a sheet, shuffling controls in among the open items.

    `truth_source` says where the controls' answers came from and is REQUIRED
    when any item carries one -- see the module docstring on why a control from
    my own prior claim measures nothing.
    """
    controls = [i for i in items if i.is_control]
    if controls and not truth_source:
        raise ValueError("controls present but truth_source is empty")
    classes = list(classes)
    if CANT_TELL not in classes:
        classes.append(CANT_TELL)
    for it in items:
        if it.truth is not None and it.truth not in classes:
            raise ValueError(f"control {it.key!r} has truth {it.truth!r}, "
                             f"which is not in {classes}")

    rng = random.Random(seed if seed is not None else int(time.time() * 1000) % 2**31)
    shown = list(items)
    rng.shuffle(shown)

    panels, warnings, void_hits = [], [], 0
    order, key, meta = [], {}, []
    for n, it in enumerate(shown, 1):
        disp = f"{n:02d}"
        p, vf = _panel(it, disp, zoom, pad)
        panels.append(p)
        order.append(disp)
        if vf > 0.001:
            void_hits += 1
        if it.truth is not None:
            key[disp] = it.truth
        meta.append({"id": disp, "key": it.key, "note": it.note,
                     "box": list(it.box), "void_frac": round(vf, 4)})
    if extra_panels:
        panels.extend(extra_panels)
    if zoom < 1:
        warnings.append(f"minified to {zoom}x -- detail destroyed, do not read fine structure")
    if void_hits:
        warnings.append(f"{void_hits} panel(s) run off the source; magenta is missing data")

    body = _grid(panels, cols)
    sheet_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{rng.randrange(16**4):04x}"
    img = _chrome(body, question, classes, scope, len(items), len(controls),
                  sheet_id, warnings)
    manifest = {
        "sheet_id": sheet_id, "encoding": ENCODING, "kind": kind,
        "question": question, "classes": classes, "scope": scope,
        "domain": domain, "zoom": zoom, "pad": pad,
        "n_items": len(items), "n_controls": len(controls),
        "truth_source": truth_source, "items": meta,
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "warnings": warnings,
    }
    return Sheet(sheet_id, kind, question, classes, scope, img, order,
                 manifest, key, warnings)


# --------------------------------------------------------------------------
# the six question kinds
# --------------------------------------------------------------------------

def present(items, *, question, classes, **kw):
    """Is the ringed thing an X? The default shape; `classes` is the closed set."""
    return build(items, question=question, classes=classes, kind="present", **kw)


def which_of_k(items, references, *, question, zoom=4, pad=20, **kw):
    """Which of k references is the ringed thing?

    The references are rendered as panels on the same sheet at the SAME zoom --
    that is the point. `minimap_portrait` compared a candidate against a gallery
    the reader never saw, which is how what I called `sage` stayed Skye through
    a whole measured evaluation.
    """
    refs = [_panel(r, r.key[:10], zoom, pad, caption="REFERENCE")[0]
            for r in references]
    return build(items, question=question, classes=[r.key for r in references],
                 kind="which_of_k", zoom=zoom, pad=pad, extra_panels=refs, **kw)


def boundary(items, *, question, classes=("inside", "outside"), **kw):
    """Inside or outside the region? Items carry `overlay`, drawn in amber.

    A boundary question becomes answerable AND scorable by asking about ringed
    probe points rather than about the region -- which also means it takes
    controls like every other kind. The searchable mask was derived five times
    without ever being asked this way.
    """
    return build(items, question=question, classes=list(classes),
                 kind="boundary", **kw)


def count(items, *, question, **kw):
    """How many? Sheet-level integer, panels indexed so a disagreement localises."""
    return build(items, question=question, classes=["<integer>"],
                 kind="count", scope="sheet", **kw)


def correspond(items, *, question, classes=("same", "different"), **kw):
    """Are these two the same thing? Items are pre-composed aligned pairs."""
    kw.setdefault("cols", 4)
    return build(items, question=question, classes=list(classes),
                 kind="correspond", **kw)


def ordering(items, *, question, **kw):
    """What order did these happen in? Sheet-level permutation of the ids."""
    kw.setdefault("cols", 8)
    return build(items, question=question, classes=["<permutation of ids>"],
                 kind="ordering", scope="sheet", **kw)


# --------------------------------------------------------------------------
# scoring, and the log that makes it pool
# --------------------------------------------------------------------------

def answer(sheet_id: str, answers: dict[str, str], *, confidence: float,
           by: str = "claude", out_dir: Path | None = None,
           retrospective: bool = False, log_path: Path | None = None) -> dict:
    """Score the controls, mark the sheet VALID or VOID, and log one row.

    A missed control voids the whole sheet: its open answers are recorded but
    flagged, because the sheet has just demonstrated that this reader could not
    resolve this question at this magnification. That is the finding, and it is
    worth more than the answers would have been.
    """
    d = Path(out_dir) if out_dir else STORE / "glances"
    manifest = json.loads((d / f"{sheet_id}.json").read_text(encoding="utf-8"))
    key = json.loads((d / f"{sheet_id}.key.json").read_text(encoding="utf-8"))

    src = manifest.get("truth_source", "")
    if key and src.startswith("claude"):
        raise ValueError(
            f"truth_source is {src!r}: the controls are my own prior claims, so "
            "this sheet cannot measure anything. See 'never seed the file'.")

    hits, misses, skipped = [], [], []
    for disp, truth in key.items():
        got = answers.get(disp)
        if got is None or got == CANT_TELL:
            skipped.append(disp)
        elif got == truth:
            hits.append(disp)
        else:
            misses.append([disp, got, truth])

    verdict = "VOID" if misses else ("VALID" if key else "UNCONTROLLED")
    n_told = len(hits) + len(misses)
    outcome = "wrong" if misses else ("right" if n_told else "couldnt-tell")

    rec = {
        "sheet_id": sheet_id, "encoding": ENCODING, "verdict": verdict,
        "answers": answers, "confidence": confidence, "by": by,
        "controls": {"hit": hits, "missed": misses, "cant_tell": skipped},
        "answered": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (d / f"{sheet_id}.answer.json").write_text(json.dumps(rec, indent=2),
                                               encoding="utf-8")

    log = Path(log_path) if log_path else STORE / "notes" / "predictions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "when": time.strftime("%Y-%m-%d"),
            "domain": manifest.get("domain", "vision"),
            "claim": manifest["question"],
            "confidence": confidence,
            "outcome": outcome,
            "retrospective": retrospective,
            "via": ENCODING, "sheet": sheet_id, "kind": manifest["kind"],
            "zoom": manifest["zoom"], "n_items": manifest["n_items"],
            "n_controls": manifest["n_controls"],
            "controls_hit": len(hits), "controls_told": n_told,
            "truth_source": src, "by": by,
        }) + "\n")
    return rec


def calibration(path: Path | None = None) -> str:
    """Pooled calibration by domain and confidence band -- the reason for all this.

    This is the BAND view: am I calibrated at the confidence I claim. The TIME
    view -- is this domain predictable at all, and has its regime changed since
    the calibration was measured -- lives in `reticle.judgement`. Keep them
    separate deliberately; they answer different questions off the same log.

    Gate on CALIBRATION, not hit rate: right 80% of the time while claiming 0.9
    means fix the confidence, not the resolution. A rising `couldnt-tell` share
    means the technique is decaying into ritual.
    """
    p = Path(path) if path else STORE / "notes" / "predictions.jsonl"
    if not p.exists():
        return "no predictions log yet"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return "predictions log is empty"

    def band(c):
        return ("0.9+" if c >= 0.9 else "0.8-0.9" if c >= 0.8
                else "0.7-0.8" if c >= 0.7 else "<0.7")

    via = sum(1 for r in rows if r.get("via") == ENCODING)
    out = [f"{len(rows)} predictions  ({via} through {ENCODING})", "",
           f"{'domain':<12} {'band':>8} {'n':>4} {'right':>6} {'wrong':>6} "
           f"{'ct':>4} {'acc':>6}  gap"]
    seen: dict = {}
    for r in rows:
        seen.setdefault((r.get("domain", "?"), band(float(r.get("confidence", 0)))), []).append(r)
    for (dom, b), rs in sorted(seen.items()):
        right = sum(1 for r in rs if r["outcome"] == "right")
        wrong = sum(1 for r in rs if r["outcome"] == "wrong")
        ct = len(rs) - right - wrong
        scored = right + wrong
        mean_c = sum(float(r.get("confidence", 0)) for r in rs) / len(rs)
        if scored:
            acc = right / scored
            out.append(f"{dom:<12} {b:>8} {len(rs):>4} {right:>6} {wrong:>6} "
                       f"{ct:>4} {acc:>6.2f}  {acc - mean_c:+.2f}")
        else:
            out.append(f"{dom:<12} {b:>8} {len(rs):>4} {right:>6} {wrong:>6} "
                       f"{ct:>4} {'--':>6}")
    ct_all = sum(1 for r in rows if r["outcome"] not in ("right", "wrong"))
    out += ["", f"couldnt-tell share: {ct_all / len(rows):.0%}  "
                "(rising = the technique is decaying into ritual)",
            "gap = accuracy minus mean stated confidence; negative is overconfidence."]
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _self_test(out_dir: Path) -> int:
    """Synthetic sheet exercising every kind. Proves the renderer, not the eye."""
    rng = np.random.default_rng(7)
    src = (rng.integers(20, 60, (300, 300, 3))).astype(np.uint8)
    truths = {}
    items = []
    for i in range(8):
        cx, cy = 30 + (i % 4) * 70, 40 + (i // 4) * 120
        ring_like = i % 2 == 0
        if ring_like:
            cv2.circle(src, (cx, cy), 7, (40, 40, 210), 1)
        else:
            cv2.line(src, (cx - 9, cy), (cx + 9, cy + 4), (200, 200, 200), 1)
        truths[f"s{i}"] = "cam" if ring_like else "not-cam"
        items.append(Item(image=src, box=(cx - 8, cy - 8, 16, 16), key=f"s{i}",
                          truth=truths[f"s{i}"] if i < 3 else None,
                          note=f"t={1000 * i}ms"))
    # one item deliberately off the source edge, to prove void is visible
    items.append(Item(image=src, box=(292, 8, 16, 16), key="edge", note="at the ROI edge"))

    sh = present(items, question="SELF TEST -- is the ringed thing a ring (cam) "
                                 "or a line (not-cam)?",
                 classes=["cam", "not-cam"], zoom=6, pad=14,
                 truth_source="synthetic (self-test)", domain="selftest", seed=1)
    png = sh.write(out_dir)
    assert sh.manifest["n_controls"] == 3, sh.manifest["n_controls"]
    assert len(sh.key) == 3
    assert any("run off the source" in w for w in sh.warnings), sh.warnings
    assert CANT_TELL in sh.classes

    perfect = {d: sh.key[d] for d in sh.key}
    log = out_dir / "selftest-predictions.jsonl"
    rec = answer(sh.sheet_id, perfect, confidence=0.7, out_dir=out_dir, log_path=log)
    assert rec["verdict"] == "VALID", rec
    bad = {d: ("cam" if v == "not-cam" else "not-cam") for d, v in sh.key.items()}
    sh2 = present(items, question="SELF TEST -- void path", classes=["cam", "not-cam"],
                  zoom=6, pad=14, truth_source="synthetic (self-test)",
                  domain="selftest", seed=2)
    sh2.write(out_dir)
    bad2 = {d: ("cam" if v == "not-cam" else "not-cam") for d, v in sh2.key.items()}
    rec2 = answer(sh2.sheet_id, bad2, confidence=0.9, out_dir=out_dir, log_path=log)
    assert rec2["verdict"] == "VOID", rec2

    # a claude-sourced control must be refused outright
    sh3 = present(items[:4], question="SELF TEST -- seeded control", classes=["cam", "not-cam"],
                  zoom=4, pad=10, truth_source="claude-provisional",
                  domain="selftest", seed=3)
    sh3.write(out_dir)
    try:
        answer(sh3.sheet_id, {d: v for d, v in sh3.key.items()},
               confidence=0.5, out_dir=out_dir, log_path=log)
    except ValueError as e:
        assert "cannot measure anything" in str(e)
    else:
        raise AssertionError("a claude-* truth_source was accepted")

    # every other kind renders. `plain` drops the truths: a control is only
    # meaningful when its answer is in THIS sheet's class set, which build()
    # enforces -- the first draft of this self-test tripped it.
    plain = [Item(image=i.image, box=i.box, key=i.key, note=i.note) for i in items]
    refs = [Item(image=src, box=(22, 32, 16, 16), key="cam"),
            Item(image=src, box=(92, 32, 16, 16), key="spike")]
    which_of_k(plain[:4], refs, question="SELF TEST -- which reference?",
               zoom=5, pad=12, domain="selftest", seed=4).write(out_dir)
    mask = np.zeros(src.shape[:2], bool)
    mask[100:200, 100:200] = True
    boundary([Item(image=src, box=(140, 140, 8, 8), key="p0", overlay=mask, truth="inside"),
              Item(image=src, box=(40, 40, 8, 8), key="p1", overlay=mask, truth="outside")],
             question="SELF TEST -- inside the amber region?", zoom=4, pad=24,
             truth_source="synthetic", domain="selftest", seed=5).write(out_dir)
    count(plain[:6], question="SELF TEST -- how many rings?", zoom=4, pad=10,
          domain="selftest", seed=6).write(out_dir)
    correspond(plain[:4], question="SELF TEST -- same object?", zoom=4, pad=10,
               domain="selftest", seed=7).write(out_dir)
    ordering(plain[:5], question="SELF TEST -- chronological order?", zoom=3, pad=8,
             domain="selftest", seed=8).write(out_dir)

    print(calibration(log))
    print(f"self-test OK -- 8 sheets in {out_dir}")
    print(f"  first sheet: {png}  ({sh.image.shape[1]}x{sh.image.shape[0]})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="calibration",
                    choices=["answer", "calibration"])
    ap.add_argument("sheet", nargs="?")
    ap.add_argument("--answers", default="", help="01=cam,02=not-cam,...")
    ap.add_argument("--confidence", type=float, default=0.7)
    ap.add_argument("--by", default="claude")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    out_dir = Path(a.dir) if a.dir else STORE / "glances"

    if a.self_test:
        out_dir.mkdir(parents=True, exist_ok=True)
        return _self_test(out_dir)
    if a.cmd == "calibration":
        print(calibration())
        return 0
    if not a.sheet:
        ap.error("answer needs a sheet id")
    answers = dict(kv.split("=", 1) for kv in a.answers.split(",") if kv.strip())
    rec = answer(a.sheet, answers, confidence=a.confidence, by=a.by, out_dir=out_dir)
    print(f"{rec['verdict']}  controls {len(rec['controls']['hit'])} hit, "
          f"{len(rec['controls']['missed'])} missed, "
          f"{len(rec['controls']['cant_tell'])} cant-tell")
    for disp, got, truth in rec["controls"]["missed"]:
        print(f"  MISSED {disp}: said {got!r}, truth {truth!r}")
    if rec["verdict"] == "VOID":
        print("  -> this sheet's open answers are discarded, not doubted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
