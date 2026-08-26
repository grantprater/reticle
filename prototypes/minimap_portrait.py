"""Identify WHICH enemy a minimap icon is, from the portrait inside its ring.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_portrait.py mine  <session>
    .\\.venv\\Scripts\\python.exe prototypes\\minimap_portrait.py eval  <session> [--sheet out.png]

The ring finder in `minimap_ring_fit.py` answers "is that an enemy". This asks
"which one", which is the difference between counting enemies and tracking
them: an icon that keeps its identity across frames is a trajectory, and a
trajectory is what every SS4 duel metric actually needs.

The signal is real and it is bigger than it has any right to be
--------------------------------------------------------------
The interior of an enemy icon is the agent's portrait, drawn at roughly 11 px
across, composited over live scenery, through 4:2:0 chroma. It survives all of
that. Clustering 71 hand-marked enemy icons on `a06f04a0059f` by nothing but
their interiors produced 19 groups, every one of them visually pure, merging by
eye into exactly the five agents the enemy roster shows -- Skye, Iso, Jett,
Omen, Killjoy -- plus a sixth, entirely separate group for the question-mark
icons. Nothing was tuned to make that happen.

(I first recorded that lineup as Sage and Yoru rather than Skye and Iso, and
Grant corrected it off the labeller's own key. It changed no measurement -- the
classes were consistent -- but see the note in CLAUDE.md on why no check in the
capture could have caught a wrong NAME on a right class.)

Why the portrait survives when the ring barely does: the ring is a 1-2 px
COLOUR feature and colour is exactly what 4:2:0 halves, but the portrait is a
~11 px LUMA structure, and luma is carried at full resolution. The same
subsampling that cost the seal test its whole detection costs this almost
nothing.

Measured, leave-one-out, on those 71 icons (`eval`)
---------------------------------------------------
    nearest exemplar (1-NN)              93.0%
    3-NN                                 84.5%
    one median template per agent        70.4%

**Read the provenance line `eval` prints before quoting any of these.** As of
2026-08-26 the store holds 107 labelled icons of which only 36 are Grant's; the
other 71 are still `claude-provisional`, so 93.0% is my clustering scored
against itself. On the mixed set with question marks added as a sixth class it
reads 85.0% overall and 87.3% over the five agents alone.

The question mark is NOT solved and two guesses about it were wrong
-------------------------------------------------------------------
A `?` icon -- an enemy last seen at that spot, drawn as a glyph rather than a
portrait -- clustered perfectly cleanly on its own when nothing was supervising
it, so it looked like a free sixth class. Scored properly it is the dominant
error: 13 of 16 misses on the mixed set involve a `?`, in BOTH directions.

Two explanations were measured and neither survived:

* **"masking the ring's red erases the `?` glyph, leaving a flat patch."** No.
  Red inside the interior is the same for both -- median 0.08 for question
  marks against 0.09 for agents -- and no threshold on it separates them
  usefully (at a cut that catches 29% of question marks it costs half the
  agents);
* **"the glyph sits outside the sampled radius."** No. Sweeping INTERIOR_FRAC
  from 0.55 to 0.94 moves 6-class accuracy between 82.2% and 86.0% with no
  trend, and question-mark recall stays in 75-82% throughout. The radius is not
  what is wrong, which is also why 0.55 was left alone rather than tuned to the
  0.62 that happened to peak -- one point on 107 samples is noise.

What the numbers do say is that the `?` interior is often nearly featureless:
raw interior contrast has p10 5.9 for question marks against 31.1 for agents,
while the medians are close (32.0 against 42.3). So a minority of `?` icons are
flat, and NCC is scale-invariant -- it normalises a flat patch up to full
weight and correlates noise. That points at a different treatment rather than a
tuned one: a `?` is a fixed GLYPH, the same shape every time, which is the case
template matching handles well and appearance clustering handles badly. Treat
it the way the digit glyphs are treated, decide it before the 5-way agent
match, and keep the portrait descriptor for portraits.

**Nearest exemplar, not a per-agent template.** This is the load-bearing
result and it was a surprise. A single template per agent scores 70.4% because
the same agent's icons do not correlate well with *each other*: the facing
triangle sweeps across the interior as the player turns, the map floor bleeds
in at the rim, and the local player's icon draws over the top at close range.
Within-agent variation is larger than between-agent distance, so an average
over it is a blur that matches nobody. Keeping the exemplars and taking the
nearest one costs nothing and recovers 23 points. It is the same reason the
clustering above produced 19 groups rather than 5, and those extra groups are
not noise to be tuned away -- they are the appearance modes, and holding them
is the whole job of a gallery.

The roster names the gallery; it is not the template source (yet)
-----------------------------------------------------------------
The top-right enemy roster carries the same five agents at 40 px, which makes
it the obvious template source -- mined from footage on a surface the pipeline
already locates, exactly the convention `reticle glyphs` uses. Measured, using
roster art directly as the template, sweeping every crop and scale and picking
the crop ON THE TEST SET ITSELF:

    roster art as template, unmirrored      63.4%
    roster art as template, mirrored        74.6%

against 93.0% for exemplars mined from the minimap itself. Both roster numbers
are optimistic upper bounds -- the crop was fitted to the answers -- so the
in-domain gallery is what ships today.

**Grant, on why mirrored won by 11 points, and it is not what I first wrote:**
the mirroring is a property of the ENEMY SIDE OF THE ROSTER, which flips the
art so the two teams face each other. It is not a property of the minimap.
*The Tab scoreboard and the minimap hold every agent in the same orientation,
always.* And the minimap icon is a **circular crop** of that art -- not the
whole bust -- **at a consistent size and scale**.

That last sentence is the important one, because it says a fixed
crop-and-scale transform EXISTS. The 74.6% ceiling above is then not evidence
that cross-surface matching cannot work; it is evidence that I swept the wrong
family, cropping busts out of a mirrored surface. The transform should be
fitted once, against the unmirrored surface, and `reticle/scoreboard.py`
already locates it. What that would buy is worth more than the 18 points:
**a gallery mined once per agent transfers to every future session**, and a new
capture needs no labelling at all -- which is exactly the position the digit
templates are already in.

Ground truth here is PROVISIONAL and it is mine, not Grant's
-----------------------------------------------------------
The 71 agent labels were made by clustering the icons and then reading each
cluster by eye against the mined roster art. That is good enough to measure a
matcher and not good enough to call a number settled, because the labels and
the descriptor share a failure mode: an agent pair the descriptor cannot
separate is an agent pair I would have merged into one cluster and labelled
once. `label_icon_agent.py` puts the same question to Grant, and until it has
been run every accuracy on this page should be read with that caveat attached.

One independent check is already in: for 70 of the 71 icons, the agent I
labelled it was one the enemy roster shows ALIVE at that instant (mean 3.9 of 5
alive, so chance is 78%). Running the same test over all 120 ways of naming the
five clusters ranks my labelling first at 98.6% -- but the runner-up scores
97.2%, one observation behind. So the alive constraint CORROBORATES the naming
and cannot yet establish it alone. It would sharpen with more observations; 71
came from the hand-labelled frames only, and the match holds thousands.

Two things this does not do yet
-------------------------------
* **it says nothing about allies or about the question-mark icons.** The `?`
  icons formed their own clean cluster, which means they are separable and
  should become a sixth class rather than a source of confident wrong answers;
* **it is one session with one lineup.** Every number here is fitted to five
  agents on one map, and the project's history says a new map is where these
  break. `5822b6646448` (Lotus) and `c62c2b06bcfb` (Split) were recorded on the
  same enlarged widget with different lineups and are the held-out test.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
from minimap_icons import red_mask                                # noqa: E402

STORE = Path.home() / "reticle-store"

# ---------------------------------------------------------------------------
# Roster geometry, in pixels at 1920x1080, measured 2026-08-26 on a06f04a0059f.
#
# Pixels rather than profile fractions on purpose, for the same reason
# `minimap_icons.ROI` is: this is a HUD widget anchored to the scoreline at a
# fixed HUD scale, and until a second resolution exists a fraction would be an
# invented generalisation. The profile's `hud_roster_enemy` ROI is a generous
# box around all of this and is not precise enough to cut slots from.
#
# Slot 0 is the one NEAREST the scoreline. Portraits are drawn only for players
# who are ALIVE, and the survivors PACK toward the scoreline keeping team
# order -- so with three alive, slots 0,1,2 hold an ordered subsequence of the
# five. Slot index is therefore not identity; the sequence is. (The profile's
# note that portraits "right-align toward the scoreline as teammates die" is
# right about the ally side and describes this same packing.)
#
# The enemy side draws its art MIRRORED, so the two teams face each other
# (Grant). Anything comparing this surface against the minimap or the Tab
# scoreboard has to flip it first; those two share one orientation.
ROSTER_ENEMY_X0, ROSTER_PITCH = 1175, 65.75
ROSTER_Y0, ROSTER_H = 30, 40
ROSTER_ALLY_X0 = 711.0          # slot 0; slot k sits at X0 - PITCH*k

# Descriptor. N=11 and FRAC=0.55 were swept together against the labels: every
# N in 11..17 scored the same to within 1.5 points, which says the information
# is in the ~11 px the icon actually carries and resampling finer invents
# nothing. FRAC is a fraction of the FITTED ring radius, so the descriptor is
# scale-free and survives the widget being resized again -- the same argument
# that made `minimap_ring_fit` refuse to let its radius float.
N_GRID, INTERIOR_FRAC = 11, 0.55
_gy, _gx = np.mgrid[0:N_GRID, 0:N_GRID]
_u = (_gx - (N_GRID - 1) / 2) / ((N_GRID - 1) / 2)
_v = (_gy - (N_GRID - 1) / 2) / ((N_GRID - 1) / 2)
INSIDE = (_u * _u + _v * _v) <= 1.0
# Enough unmasked cells to compare at all. Below this the icon is mostly
# triangle or mostly occluded and the correlation is being taken over a sliver,
# which is how a confident wrong answer gets made.
MIN_CELLS = 25


def descriptor(crop, red, cx, cy, r):
    """The icon interior on a fixed grid, with the ring's own red masked out.

    Resampled with INTER_AREA rather than point-sampled. That is not a detail:
    point-sampling a 40 px roster portrait down to 11 aliases it into something
    that correlates with nothing, which is what sent the first version of this
    chasing a degenerate crop and reporting 46 of 71 icons as one agent.
    """
    hs = max(3, int(round(r * INTERIOR_FRAC)))
    y0, x0 = cy - hs, cx - hs
    if y0 < 0 or x0 < 0 or y0 + 2 * hs > crop.shape[0] or x0 + 2 * hs > crop.shape[1]:
        return None, None
    p = cv2.resize(crop[y0:y0 + 2 * hs, x0:x0 + 2 * hs], (N_GRID, N_GRID),
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    m = cv2.resize((red[y0:y0 + 2 * hs, x0:x0 + 2 * hs]).astype(np.uint8) * 255,
                   (N_GRID, N_GRID), interpolation=cv2.INTER_AREA) < 64
    m = m & INSIDE
    return (p, m) if m.sum() >= MIN_CELLS else (None, None)


def similarity(pa, ma, pb, mb):
    """Masked normalised cross-correlation, averaged over the three channels.

    Per channel rather than over one stacked vector: the widget is composited
    over live scenery and the whole icon shifts in level with what is behind
    it, so each channel needs its own mean removed. Correlation rather than
    absolute difference for the same reason -- the level moves, the pattern
    does not. This is the minimap's version of the convention the rest of the
    project already follows: never test an absolute level against this HUD.
    """
    m = ma & mb
    if m.sum() < MIN_CELLS:
        return -1.0
    s = 0.0
    for ch in range(3):
        a = pa[:, :, ch][m]
        b = pb[:, :, ch][m]
        a = a - a.mean()
        b = b - b.mean()
        d = np.linalg.norm(a) * np.linalg.norm(b)
        s += float(a @ b / d) if d > 0 else 0.0
    return s / 3


def classify(p, m, gallery):
    """Nearest exemplar over a gallery of (patch, mask, name).

    Returns (name, score, margin). The margin is between the best exemplar of
    the winning agent and the best exemplar of the RUNNER-UP AGENT, not the
    second-best exemplar overall -- two views of the same player sitting first
    and second is the CONFIDENT case, and a margin that called it ambiguous
    would have the sign backwards.
    """
    best: dict[str, float] = {}
    for gp, gm, name in gallery:
        s = similarity(p, m, gp, gm)
        if s > best.get(name, -2.0):
            best[name] = s
    if not best:
        return None, -1.0, 0.0
    order = sorted(best.items(), key=lambda kv: -kv[1])
    runner = order[1][1] if len(order) > 1 else -1.0
    return order[0][0], order[0][1], order[0][1] - runner


# ---------------------------------------------------------------------------
# The roster: naming the gallery, and saying who is alive.

def roster_slot(frame, k, dx=0):
    x = int(round(ROSTER_ENEMY_X0 + ROSTER_PITCH * k)) - 2 + dx
    return frame[ROSTER_Y0:ROSTER_Y0 + ROSTER_H, x:x + ROSTER_H]


def _flat_ncc(a, b):
    s = 0.0
    for ch in range(3):
        p = a[:, :, ch].ravel().astype(np.float32)
        q = b[:, :, ch].ravel().astype(np.float32)
        p = p - p.mean()
        q = q - q.mean()
        d = np.linalg.norm(p) * np.linalg.norm(q)
        s += float(p @ q / d) if d > 0 else 0.0
    return s / 3


# A slot matches its own portrait at ~0.9 and an empty slot matches the best of
# five at well under 0.5, so this sits in a wide gap. Swept 0.55/0.65/0.75
# against the alive check: 0.55 and 0.65 agree exactly, and 0.75 starts dropping
# live players -- the expensive direction, since a missing agent turns a correct
# identification into a violation and would flatter nothing.
ALIVE_NCC_MIN = 0.60


def alive(frame, lineup):
    """Which of the five enemies the roster shows alive on this frame.

    `lineup` is a list of (name, 40x40 portrait) in team order. Matching here is
    same-surface and same-scale, which is why it is reliable where matching
    roster art against a minimap icon is not.

    Searched +/-3 px in x because the pitch is fractional (65.75) and rounding
    walks by a pixel across the five slots.
    """
    out = {}
    for k in range(len(lineup)):
        best = (-1.0, None)
        for dx in (-3, -1, 0, 1, 3):
            sub = roster_slot(frame, k, dx)
            if sub.shape[:2] != (ROSTER_H, ROSTER_H):
                continue
            for name, tpl in lineup:
                s = _flat_ncc(sub, tpl)
                if s > best[0]:
                    best = (s, name)
        if best[0] >= ALIVE_NCC_MIN:
            out[best[1]] = best[0]
    return out


def mine_lineup(cap, n_probe=240):
    """Five enemy portraits in team order, from a frame where all five live.

    Found rather than given: sample across the match and keep the frame whose
    five slots carry the most detail. All five are alive at the start of every
    round, so such a frame is common; picking the busiest one also steps around
    the round-transition fades, where the panel is half drawn.

    Detail rather than "is a portrait there", because that test needs the very
    templates this function exists to produce.
    """
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    best = None
    for i in np.linspace(tot * 0.02, tot * 0.98, n_probe).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        per = []
        for k in range(5):
            sub = roster_slot(fr, k)
            if sub.shape[:2] != (ROSTER_H, ROSTER_H):
                per = []
                break
            g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
            per.append(float(np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)).mean()))
        if not per:
            continue
        # The WEAKEST slot decides. A mean is won by one busy slot beside four
        # empty ones, which is exactly the frame this must not pick.
        score = min(per)
        if best is None or score > best[0]:
            best = (score, int(i), [roster_slot(fr, k).copy() for k in range(5)])
    return best


# ---------------------------------------------------------------------------
# Composition matching: identify an icon from art on ANOTHER surface.
#
# Grant asked whether there is a technique for fuzzy matching across downscaled
# or partial copies, after pixel-wise correlation failed to carry identity from
# the scoreboard to the minimap at any crop. There is, and it is the one thing
# tried here that does not need the two framings to agree at all: throw the
# spatial layout away and compare COLOUR COMPOSITION. "How much blue, how much
# yellow, how much skin" survives a reframe, a rescale and a partial crop,
# because it never depended on where anything sat.
#
# Measured on a06f04a0059f, scoreboard art against Grant's 79 labelled icons,
# five agents, chance 20%:
#
#     whole portrait, NO parameters at all           77.2%
#     central disc, held out by agent                83.5%   (icon-weighted)
#     central disc, fitted on all five               92.4%   (in-sample)
#     in-domain control: icon histograms             91.1%   (leave-one-out)
#
# against 88.6% for the hand-labelled in-domain NCC gallery. So composition
# matching gets within five points of a fully labelled gallery **using no
# minimap labels whatsoever**, which is the whole point: it transfers.
#
# The held-out-agent fit is also STABLE -- three of five folds choose the same
# (cx 0.42, frac 0.28), where the pixel-wise fit chose a different crop every
# fold and scored below chance. A parametrisation that agrees with itself
# across folds is the signal that it found something real.
#
# Why it works where correlation did not: at 11 px there is very little layout
# to match, and what identity there is lives in the palette. The minimap's own
# narrow palette -- grey, black, red -- is what makes an agent's colours stand
# out, which was the original argument for portrait identification being
# tractable at all.
#
# 10 hue bins x 3 saturation x 3 value. Coarse deliberately: the icon is ~90
# unmasked cells, so a finer histogram is mostly empty bins and the intersection
# becomes noise.
HIST_H, HIST_S, HIST_V = 10, 3, 3
# The disc taken out of the source portrait, in units of its height. Fitted by
# held-out agent, not by hand -- and note that skipping the crop entirely still
# scores 77.2%, so this is a refinement rather than a load-bearing constant.
SRC_DISC_CX, SRC_DISC_FRAC = 0.42, 0.28


def composition(bgr, mask=None):
    """Colour histogram, L1-normalised. Layout-free by construction."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, sa, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    keep = np.ones(h.shape, bool) if mask is None else mask
    if not keep.any():
        return np.zeros(HIST_H * HIST_S * HIST_V, np.float32)
    hi = (h[keep].astype(int) * HIST_H // 180).clip(0, HIST_H - 1)
    si = (sa[keep].astype(int) * HIST_S // 256).clip(0, HIST_S - 1)
    vi = (v[keep].astype(int) * HIST_V // 256).clip(0, HIST_V - 1)
    out = np.bincount((hi * HIST_S + si) * HIST_V + vi,
                      minlength=HIST_H * HIST_S * HIST_V).astype(np.float32)
    return out / max(1.0, out.sum())


def source_composition(art, cx=SRC_DISC_CX, frac=SRC_DISC_FRAC):
    """Composition of a source portrait, over the disc that best transfers."""
    h = art.shape[0]
    r = int(h * frac)
    cyp, cxp = h // 2, int(h * cx)
    yy, xx = np.mgrid[0:art.shape[0], 0:art.shape[1]]
    return composition(art, ((yy - cyp) ** 2 + (xx - cxp) ** 2) <= r * r)


def classify_composition(hq, sources):
    """Nearest source by histogram intersection. `sources` is {name: hist}."""
    order = sorted(((float(np.minimum(hq, hs).sum()), n) for n, hs in sources.items()),
                   reverse=True)
    if not order:
        return None, 0.0, 0.0
    runner = order[1][0] if len(order) > 1 else 0.0
    return order[0][1], order[0][0], order[0][0] - runner


# ---------------------------------------------------------------------------
# The Tab scoreboard: ten portraits, unmirrored, dead players included.
#
# Grant: the scoreboard and the minimap hold every agent in ONE orientation,
# where the enemy side of the top roster is mirrored. Confirmed on the pixels
# -- Killjoy's yellow jacket sits bottom-LEFT on both surfaces and bottom-right
# on the roster. So this, not the roster, is the surface a cross-surface
# transform should be fitted against.
#
# Three things it has that the roster does not:
#
#   * it keeps DEAD players, so all ten rows are always there;
#   * it carries both teams at once -- ten agents per opening, not five;
#   * `scoreboard.py` already finds the rows from their own slab profile, so
#     the geometry is derived rather than measured, and the portrait is simply
#     the left end of a row it has already located.
#
# What it costs: it is only on screen while Grant holds Tab. a06f04a0059f has
# 22 openings, which is ample -- one is enough to mine from.

# The portrait occupies the left end of the row, slightly narrower than the row
# is tall. Measured off a06f04a0059f at 42 px rows, by vertical-structure
# density across all ten rows at once: the art peaks at x0+18..28 (detail 130),
# collapses to a TROUGH at x0+34..38 (detail 14) and rises again at x0+40 where
# the text starts. The trough is the separator and it is unambiguous, so this is
# a ratio rather than a pixel count and should survive a resolution change.
#
# The first value here was 1.4, eyeballed, and it swallowed the player name.
SB_PORTRAIT_ASPECT = 0.79
# Where the two text lines live, as fractions of row height from the row's left
# edge. The upper line is the PLAYER name and the lower is the AGENT name, and
# the agent name is what makes a session self-naming -- see the note in
# CLAUDE.md. Nothing reads these yet.
SB_TEXT_X0 = 0.95


def scoreboard_portraits(frame, sb):
    """(team, is_player, portrait) for every row of an open scoreboard."""
    if not sb.open_ or not sb.rows:
        return []
    h = sb.rows[0].y1 - sb.rows[0].y0
    w = int(h * SB_PORTRAIT_ASPECT)
    out = []
    for r in sb.rows:
        art = frame[r.y0:r.y1, sb.x0:sb.x0 + w]
        if art.shape[0] > 4 and art.shape[1] > 4:
            out.append((r.team, r.is_player, art.copy()))
    return out


def mine_scoreboard(cap, templates, n_probe=400, want_rows=10):
    """Ten portraits from the busiest full scoreboard opening in the capture.

    Scans for an opening rather than being handed a timestamp, and keeps the
    one whose rows carry the most detail -- the table animates in, so an
    opening caught mid-fade is readable enough to pass `read_scoreboard` and
    still too washed out to mine art from.
    """
    from reticle.scoreboard import read_scoreboard
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    best = None
    for i in np.linspace(tot * 0.02, tot * 0.98, n_probe).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        sb = read_scoreboard(fr, templates)
        if not sb.open_ or len(sb.rows) < want_rows:
            continue
        arts = scoreboard_portraits(fr, sb)
        if len(arts) < want_rows:
            continue
        g = [cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32) for _, _, a in arts]
        # Weakest row decides, same argument as `mine_lineup`.
        score = min(float(np.abs(cv2.Sobel(x, cv2.CV_32F, 0, 1, ksize=3)).mean()) for x in g)
        if best is None or score > best[0]:
            best = (score, int(i), arts)
    return best


# ---------------------------------------------------------------------------

def load_agent_labels(sid):
    p = STORE / "labels" / "minimap_agent" / f"{sid}.jsonl"
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    # Last write for a given (t, x, y) wins, so relabelling corrects a row
    # rather than duplicating it.
    keyed = {(r["t_ms"], r["x"], r["y"]): r for r in rows}
    return [r for r in keyed.values() if r.get("agent")]


def build_gallery(sid, src, rows):
    """Descriptors for every labelled icon, decoding each frame once."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    fps = float(src["fps"])
    cap = cv2.VideoCapture(src["path"])
    out = []
    for t in sorted({r["t_ms"] for r in rows}):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[my0:my1, mx0:mx1]
        red = red_mask(crop, 100)
        for r in [q for q in rows if q["t_ms"] == t]:
            p, m = descriptor(crop, red, r["x"], r["y"], r["r"])
            if p is None:
                continue
            out.append((p, m, r["agent"], r["t_ms"],
                        crop[max(0, r["y"] - 13):r["y"] + 13,
                             max(0, r["x"] - 13):r["x"] + 13].copy()))
    cap.release()
    return out


def cmd_mine(args):
    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    cap = cv2.VideoCapture(src["path"])
    found = mine_lineup(cap)
    cap.release()
    if found is None:
        print("no frame with five drawn enemy slots")
        return 1
    score, frame_i, boxes = found
    out = STORE / "rosters" / f"{args.session}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, frame=frame_i, **{f"slot{k}": b for k, b in enumerate(boxes)})
    strip = cv2.resize(np.hstack(boxes), None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    png = out.with_suffix(".png")
    cv2.imwrite(str(png), strip)
    print(f"mined 5 enemy portraits from frame {frame_i} (weakest slot detail {score:.1f})")
    print(f"  {out}")
    print(f"  {png}   <- these are MIRRORED (enemy side); name them left to right")
    return 0


def cmd_eval(args):
    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    rows = load_agent_labels(args.session)
    if not rows:
        print(f"no agent labels for {args.session} -- run label_icon_agent.py first")
        return 1
    g = build_gallery(args.session, src, rows)
    names = sorted({x[2] for x in g})
    print(f"{len(g)} labelled icons, {len(names)} classes: {', '.join(names)}")
    print("  per class:", {n: sum(1 for x in g if x[2] == n) for n in names})
    # Provenance, printed every run and not on request. Seeding this file with
    # provisional labels once caused the labeller to SKIP every row it had
    # seeded -- they counted as already done -- so a run can silently be scoring
    # my own clustering back to me. A number without this line beside it is not
    # interpretable.
    prov = {}
    for r in rows:
        prov[r.get("by", "grant")] = prov.get(r.get("by", "grant"), 0) + 1
    print("  labelled by:", prov)

    # Leave-one-out. Every exemplar is tested against a gallery that does not
    # contain it, which is the only honest way to score a nearest-neighbour
    # rule -- scored in-sample it is 100% by construction.
    res = []
    for i in range(len(g)):
        gal = [(p, m, n) for j, (p, m, n, _, _) in enumerate(g) if j != i]
        pred, sc, mg = classify(g[i][0], g[i][1], gal)
        res.append((pred == g[i][2], mg, pred, g[i][2], i))
    acc = sum(r[0] for r in res) / len(res)
    print(f"\nleave-one-out nearest exemplar: {sum(r[0] for r in res)}/{len(res)} = {acc*100:.1f}%")
    print("  abstain curve (margin between the best and the runner-up AGENT):")
    for mth in (0.0, 0.02, 0.05, 0.10, 0.15, 0.25):
        keep = [r for r in res if r[1] >= mth]
        if keep:
            print(f"    margin>={mth:.2f}   answered {len(keep)/len(res)*100:5.1f}%"
                  f"   correct {sum(r[0] for r in keep)/len(keep)*100:5.1f}%")
    wrong = [r for r in res if not r[0]]
    if wrong:
        print("  confusions:")
        seen: dict[tuple[str, str], int] = {}
        for _, mg, pred, true, _ in wrong:
            seen[(true, pred)] = seen.get((true, pred), 0) + 1
        for (true, pred), c in sorted(seen.items(), key=lambda kv: -kv[1]):
            print(f"    {true:>9s} read as {pred:<9s} x{c}")

    # The external check: does the roster agree this agent was alive?
    lin = STORE / "rosters" / f"{args.session}.npz"
    if lin.is_file() and args.names:
        z = np.load(lin)
        lineup = list(zip(args.names.split(","), [z[f"slot{k}"] for k in range(5)]))
        cap = cv2.VideoCapture(src["path"])
        fps = float(src["fps"])
        ok_ = tot = 0
        sizes = []
        for t in sorted({x[3] for x in g}):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
            okf, fr = cap.read()
            if not okf:
                continue
            a = alive(fr, lineup)
            sizes.append(len(a))
            for x in g:
                # A question mark names no agent and means vision was LOST, so
                # it can never be "alive in the roster" and scoring it here just
                # dilutes the check -- it dragged 98.7% down to 72.9% once.
                if x[3] == t and x[2] != "question":
                    tot += 1
                    ok_ += x[2] in a
        cap.release()
        chance = float(np.mean(sizes)) / 5
        print(f"\nroster alive check: {ok_}/{tot} = {ok_/tot*100:.1f}% "
              f"(mean {np.mean(sizes):.2f} of 5 alive, so chance is {chance*100:.0f}%)")

    if args.sheet:
        S = 60
        by: dict[str, list] = {}
        for hit, mg, pred, true, i in res:
            by.setdefault(true, []).append((hit, mg, pred, g[i][4]))
        cols = min(20, max(len(v) for v in by.values()))
        sheet = np.full((len(by) * (S + 18), (cols + 1) * (S + 3), 3), 20, np.uint8)
        for ri, (name, lst) in enumerate(sorted(by.items())):
            y = ri * (S + 18)
            cv2.putText(sheet, f"{name} n={len(lst)}", (2, y + S + 14),
                        cv2.FONT_HERSHEY_PLAIN, 0.9, (255, 255, 120), 1)
            # Sorted by margin so the least confident -- and every miss -- sit
            # to the left, where they get looked at.
            for ci, (hit, mg, pred, raw) in enumerate(sorted(lst, key=lambda z: z[1])[:cols]):
                x = (ci + 1) * (S + 3)
                sheet[y:y + S, x:x + S] = cv2.resize(raw, (S, S), interpolation=cv2.INTER_NEAREST)
                if not hit:
                    cv2.rectangle(sheet, (x, y), (x + S - 1, y + S - 1), (0, 0, 255), 2)
                    cv2.putText(sheet, pred[:5], (x + 2, y + S - 3),
                                cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 0, 255), 1)
        cv2.imwrite(args.sheet, sheet)
        print(f"\nwrote {args.sheet} -- misses are boxed red and sorted to the left")
    return 0


def cmd_mine_sb(args):
    from reticle.ocr import Templates
    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    cap = cv2.VideoCapture(src["path"])
    found = mine_scoreboard(cap, Templates.load(prof.name))
    cap.release()
    if found is None:
        print("no full scoreboard opening found -- does this capture use Tab?")
        return 1
    score, frame_i, arts = found
    out = STORE / "rosters" / f"{args.session}.scoreboard.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out, frame=frame_i,
        teams=np.array([t for t, _, _ in arts]),
        is_player=np.array([p for _, p, _ in arts]),
        **{f"row{k}": a for k, (_, _, a) in enumerate(arts)})
    h = max(a.shape[0] for _, _, a in arts)
    w = max(a.shape[1] for _, _, a in arts)
    def cell(a):
        return cv2.resize(a, (w, h), interpolation=cv2.INTER_NEAREST)
    ally = [cell(a) for t, _, a in arts if t == "ally"]
    enemy = [cell(a) for t, _, a in arts if t == "enemy"]
    strip = np.vstack([np.hstack(ally), np.hstack(enemy)])
    png = out.with_suffix(".png")
    cv2.imwrite(str(png), cv2.resize(strip, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    print(f"mined {len(arts)} scoreboard portraits from frame {frame_i} "
          f"(weakest row detail {score:.1f})")
    print(f"  {out}")
    print(f"  {png}   <- allies on top, enemies below, in row order; NOT mirrored")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("mine-sb", help="mine ten portraits from the Tab scoreboard")
    s.add_argument("session")
    s.set_defaults(fn=cmd_mine_sb)
    s = sub.add_parser("mine", help="mine the five enemy roster portraits")
    s.add_argument("session")
    s.set_defaults(fn=cmd_mine)
    s = sub.add_parser("eval", help="score identification against agent labels")
    s.add_argument("session")
    s.add_argument("--sheet", help="write a contact sheet of the result")
    s.add_argument("--names", help="comma-separated agent names in roster slot "
                                   "order, to run the roster alive check")
    s.set_defaults(fn=cmd_eval)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
