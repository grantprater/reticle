"""What a crop LOOKS like, as one number vector, defined once.

Two readers draw the same agent art in different places -- the scoreboard row
and the killfeed entry -- and an adjudicator that wants to ask *are these the
same agent* needs both described by the same function. `scoreboard` computed
this histogram inline, and a second copy in `killfeed` would be the `floor_mask`
fork again: two definitions, the same name, free to drift for ten days.

**Composition, not pixels.** `minimap_portrait` established that colour
composition transfers across surfaces where pixel matching scores below chance,
and a histogram is layout-free, so a mirrored or rescaled drawing of one agent
still lands in the same place.

Why the name is qualified
--------------------------
A bare `composition` already meant something else: `prototypes/minimap_portrait`
defined a DIFFERENT histogram, and the agent gallery -- every lineup score and
margin -- is built with that one. This one shipped as `composition` for about
ten minutes before `doctor`'s DUPLICATE check named it a fork, which is what
that check is for. Two different things may not share a name; the fix is the
name, not an exemption. The gallery's histogram now lives here as
`portrait_composition` (2026-10-04), promoted so `lineup` no longer reaches
into `prototypes/`.

They stay two features on purpose. Every measured lineup result rests on
`portrait_composition`, and swapping it would move all of them at once with
nobody having re-scored a session. `BACKLOG.md` carries the unification and
what would trigger it.

`mask` is what makes this usable on a HUD
------------------------------------------
Agent art on the killfeed is drawn OVER a team-coloured plate, and the plate is
a strong saturated colour. Unmasked, every ally portrait would look like every
other ally portrait, because the plate would dominate the histogram. So the
caller passes the pixels it believes are art, and the pixels it knows are
furniture stay out of the vector.

Owns [owns:portrait-descriptor].
"""
from __future__ import annotations

import cv2
import numpy as np

#: Hue x saturation x value, 10 x 3 x 3. Coarse on purpose: the drawings differ
#: in scale, compression and the light behind them, and a fine histogram would
#: separate two renderings of one agent as readily as two agents.
H_BINS, S_BINS, V_BINS = 10, 3, 3
BINS = H_BINS * S_BINS * V_BINS

#: Below this many art pixels the histogram is noise rather than a description.
MIN_PIXELS = 64


def hsv_composition(bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Normalized HSV composition of a crop, or an empty vector when too thin.

    Returns a length-`BINS` float32 vector summing to 1, so two of them may be
    compared by histogram intersection -- `np.minimum(a, b).sum()` -- which is
    what the agent gallery is scored with.
    """
    if bgr is None or bgr.size == 0 or bgr.ndim != 3:
        return np.zeros(0, np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hb = (hsv[:, :, 0].astype(int) * H_BINS // 180).clip(0, H_BINS - 1)
    sb = (hsv[:, :, 1].astype(int) * S_BINS // 256).clip(0, S_BINS - 1)
    vb = (hsv[:, :, 2].astype(int) * V_BINS // 256).clip(0, V_BINS - 1)
    index = ((hb * S_BINS + sb) * V_BINS + vb)
    if mask is not None:
        index = index[mask.astype(bool)]
    index = np.asarray(index).ravel()
    if index.size < MIN_PIXELS:
        return np.zeros(0, np.float32)
    hist = np.bincount(index, minlength=BINS).astype(np.float32)
    return hist / max(1.0, float(hist.sum()))


def portrait_composition(bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """The lineup gallery's colour histogram, L1-normalised and layout-free.

    Promoted verbatim from `prototypes/minimap_portrait.composition`
    (2026-10-04), which now re-exports it; every lineup score and margin rests
    on it. It differs from `hsv_composition` in two ways that move scores, so
    the two stay apart: it bins every kept pixel however few, and it returns
    a zero vector of length `BINS`, never an empty one, when nothing is kept.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, sa, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    keep = np.ones(h.shape, bool) if mask is None else mask
    if not keep.any():
        return np.zeros(BINS, np.float32)
    hi = (h[keep].astype(int) * H_BINS // 180).clip(0, H_BINS - 1)
    si = (sa[keep].astype(int) * S_BINS // 256).clip(0, S_BINS - 1)
    vi = (v[keep].astype(int) * V_BINS // 256).clip(0, V_BINS - 1)
    out = np.bincount((hi * S_BINS + si) * V_BINS + vi,
                      minlength=BINS).astype(np.float32)
    return out / max(1.0, out.sum())


def detail(bgr: np.ndarray) -> float:
    """Vertical edge energy: how much drawing is in the crop at all.

    A flat plate and a portrait differ here by far more than they differ in
    colour, so this is the cheap guard against describing furniture.
    """
    if bgr is None or bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).mean())


def agrees(a, b) -> float:
    """Histogram intersection of two compositions; 0.0 when either is empty."""
    a = np.asarray(a, np.float32).ravel()
    b = np.asarray(b, np.float32).ravel()
    if a.size != b.size or a.size == 0:
        return 0.0
    return float(np.minimum(a, b).sum())


# --------------------------------------------------------------------------- art ZNCC
# The killfeed draws each agent's official portrait art at one band height, so
# two drawings of one agent are one picture, and the art itself is the
# fingerprint. `hsv_composition` keeps the palette and drops the layout; Fade
# and Iso, Clove and Reyna, Brimstone and Breach share a palette.
# `prototypes/killfeed_portrait_separability.py` measured the layout-keeping
# alternative below on 21 matches labelled by Riot's records
# (docs/KILLFEED_PORTRAIT_SEPARABILITY.md): with the art's border unweighted it
# picks the side's right agent on
# [metric:portrait_separability/zncc_inner#clean_killer_side5=0.9998] of clean
# killer views, against
# [metric:portrait_separability/current#clean_killer_side5=0.9304] for the
# composition.

#: Rows and columns of the art's border (base px, 1080p) left unweighted. The
#: player's own portrait carries a yellow frame over the art's outer rows
#: [domain:killfeed/self-yellow-frame]; weighted, the frame held those killers'
#: own-agent correlation near 0.5.
ART_INNER_MARGIN = 4


class ArtTiles:
    """Every agent's killfeed art at one tile size, in Lab, with its weights.

    Built once per tile size (`killfeed_art`). The art is shrunk with
    INTER_AREA on alpha-premultiplied colour, so a transparent pixel's colour
    never bleeds into its neighbours; the weight is the shrunk alpha with the
    `margin`-pixel border set to zero. The killfeed draws a victim's portrait
    mirrored, so the terms are kept for the art and for its mirror image.

    The reference terms of the weighted correlation are constants of the art
    and are computed here once: per agent the normalised weight, and the
    weighted art less its weighted mean. Scoring windows is then three matrix
    products (`art_zncc`).
    """

    def __init__(self, agents, lab: np.ndarray, alpha: np.ndarray, margin: int):
        self.agents = tuple(agents)
        self.index = {a: i for i, a in enumerate(self.agents)}
        self.h, self.w = int(lab.shape[1]), int(lab.shape[2])
        self.margin = int(margin)
        #: The shrunk alpha itself, border included: where the plate shows.
        self.alpha = alpha.astype(np.float32)
        weight = alpha.astype(np.float32).copy()
        m = self.margin
        if m > 0:
            weight[:, :m] = 0
            weight[:, self.h - m:] = 0
            weight[:, :, :m] = 0
            weight[:, :, self.w - m:] = 0
        self._lab, self._weight = lab, weight
        self._cut: dict = {}
        self.terms = {False: self._terms(lab, weight),
                      True: self._terms(lab[:, :, ::-1], weight[:, :, ::-1])}

    def cut_terms(self, cut: int, mirrored: bool = False) -> dict:
        """The terms of the art less its `cut` leftmost columns (as drawn,
        after any mirror), for a window the ROI's left edge cuts; `cover` is
        each agent's share of its weight that remains. Cached per cut."""
        key = (int(cut), bool(mirrored))
        if key not in self._cut:
            lab = self._lab[:, :, ::-1] if mirrored else self._lab
            weight = self._weight[:, :, ::-1] if mirrored else self._weight
            t = self._terms(lab[:, :, cut:], weight[:, :, cut:])
            t["cover"] = (weight[:, :, cut:].sum((1, 2))
                          / np.maximum(weight.sum((1, 2)), 1e-9)).astype(np.float32)
            self._cut[key] = t
        return self._cut[key]

    def _terms(self, lab: np.ndarray, weight: np.ndarray) -> dict:
        A, P = len(self.agents), lab.shape[1] * lab.shape[2]
        w = weight.reshape(A, P)
        wn = w / np.maximum(w.sum(1, keepdims=True), 1e-9)
        ref = np.ascontiguousarray(lab).reshape(A, P, 3).astype(np.float32)
        mean = np.einsum("ap,apc->ac", wn, ref)
        rc = ref - mean[:, None, :]
        var = np.einsum("ap,apc->a", wn, rc * rc)
        # (P*3, A): a window's pixels, channel last, times this is the numerator
        rcw = np.ascontiguousarray((rc * wn[:, :, None]).reshape(A, P * 3).T, np.float32)
        return {"wn": np.ascontiguousarray(wn.T, np.float32), "rcw": rcw,
                "var": var.astype(np.float32)}


_ART_CACHE: dict = {}


def to_lab(bgr_u8: np.ndarray) -> np.ndarray:
    """CIE Lab (float32, L 0-100) of a BGR uint8 image, as the art is held."""
    return cv2.cvtColor(bgr_u8.astype(np.float32) * np.float32(1.0 / 255.0), cv2.COLOR_BGR2Lab)


def killfeed_art(art_dir, h: int, w: int, margin: int = ART_INNER_MARGIN) -> ArtTiles | None:
    """Every `<Agent>_killfeed_portrait.png` under `art_dir`, shrunk to h x w
    (INTER_AREA on alpha-premultiplied colour), as `ArtTiles`; None when the
    directory holds no art. Cached per directory, size and margin."""
    from pathlib import Path
    key = (str(art_dir), int(h), int(w), int(margin))
    if key in _ART_CACHE:
        return _ART_CACHE[key]
    agents, labs, alphas = [], [], []
    for p in sorted(Path(art_dir).glob("*_killfeed_portrait.png")):
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            continue
        im = im.astype(np.float32) / 255.0
        a = im[:, :, 3:4]
        pm = cv2.resize(im[:, :, :3] * a, (int(w), int(h)), interpolation=cv2.INTER_AREA)
        al = cv2.resize(a[:, :, 0], (int(w), int(h)), interpolation=cv2.INTER_AREA)
        col = np.clip(pm / np.maximum(al, 1e-3)[:, :, None], 0, 1).astype(np.float32)
        labs.append(cv2.cvtColor(col, cv2.COLOR_BGR2Lab))
        alphas.append(al)
        agents.append(p.name[:-len("_killfeed_portrait.png")])
    tiles = ArtTiles(agents, np.stack(labs), np.stack(alphas), margin) if agents else None
    _ART_CACHE[key] = tiles
    return tiles


def art_zncc(region_lab: np.ndarray, art: ArtTiles, candidates,
             mirrored: bool = False, cut: int = 0) -> np.ndarray:
    """Weighted zero-mean normalised correlation of every art-sized window of
    `region_lab` with each candidate's art: (rows, cols, candidates), -1..1.

    The three Lab channels pool: the numerator and the window's variance sum
    over channels, each centred on its own weighted mean, under the art's
    weight (`ArtTiles`), so the plate and the world behind the art's
    transparent pixels never count. Every window lies wholly inside
    `region_lab`; the caller cuts the region inside the ROI. A flat window
    (variance under a thousandth of the art's) scores 0. Matrix products over
    the windows; nothing loops per pixel.

    With `cut` > 0 the windows are the art less its `cut` leftmost columns,
    `art.w - cut` wide, for a window the ROI's left edge cuts: the correlation
    runs over the columns inside. Every candidate is scored on the same
    columns; the caller decides how few columns are too few
    (`killfeed.ART_MIN_VISIBLE`), one width for every candidate, since a
    per-candidate share of weight scored some agents 0 where others scored.
    """
    t = art.cut_terms(cut, mirrored) if cut > 0 else art.terms[bool(mirrored)]
    idx = [art.index[c] for c in candidates]
    H, W = region_lab.shape[:2]
    aw = art.w - int(cut)
    oy, ox = H - art.h + 1, W - aw + 1
    if oy <= 0 or ox <= 0 or not idx or aw <= 0:
        return np.zeros((max(oy, 0), max(ox, 0), len(idx)), np.float32)
    win = np.lib.stride_tricks.sliding_window_view(region_lab, (art.h, aw), axis=(0, 1))
    X = np.ascontiguousarray(win.transpose(0, 1, 3, 4, 2)).reshape(oy * ox, art.h * aw, 3)
    wn, rcw, var = t["wn"][:, idx], t["rcw"][:, idx], t["var"][idx]
    mx = np.stack([X[:, :, c] @ wn for c in range(3)], -1)              # O, A, 3
    vx = (X * X).sum(-1) @ wn - (mx * mx).sum(-1)                        # O, A
    num = X.reshape(len(X), -1) @ rcw                                    # O, A
    z = num / np.sqrt(np.maximum(vx, 1e-6) * np.maximum(var, 1e-6)[None])
    z = np.where(vx > 1e-3 * var[None], np.clip(z, -1.0, 1.0), 0.0)
    return z.reshape(oy, ox, len(idx)).astype(np.float32)
