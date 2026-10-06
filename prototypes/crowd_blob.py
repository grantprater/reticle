r"""Crowds as team-colour blobs: track the blob, not its members; fire the
expensive work only when it splits.

    .\.venv\Scripts\python.exe prototypes\crowd_blob.py calibrate bdfdcf009dba [--record]
    .\.venv\Scripts\python.exe prototypes\crowd_blob.py replay 9acf02f98283 [--record]
    .\.venv\Scripts\python.exe prototypes\crowd_blob.py riot 3694746e4e54 a06f04a0059f bdfdcf009dba [--record]
    .\.venv\Scripts\python.exe prototypes\crowd_blob.py price bdfdcf009dba --blob-us <us> [--record]

Add `--events-from <copy of store/events>` before the command to read a
frozen copy of the stored streams.

Successor to `prototypes/crowd_region.py` (crowd-region-0.2.0), whose region
was the anchors' hull plus two icon radii, opened only when a track vanished.
The player's design (2026-10-04), which governs: "you have a blob, and the
edges of the blob might distort a bit and the entities in it might move
together while still being overlapping. You want a very cheap way of
detecting when the separation actually happens."

Blobs (`FrameBlobs`)
--------------------
The team colour is the ally-icon reader's per-frame teal key
(`minimap.ally_mask` on the floor), which the reader computes on every drawn
frame; this module restates none of it. The key is blurred with a Gaussian
of `SIGMA_R` icon outer radii (`stack_fit.Shape.r_out` at the session's map
scale) and cut once, at `LEVEL` times one model icon's blurred ring density
(`model_density`). The blur joins the pale ring's fragments; a blob that
never touches the opaque slab is the world behind the widget and is dropped,
as `minimap.icons`'s `support` rule drops it. Connected components
(`cv2.connectedComponentsWithStats`) are the blobs; a blob's mass is its keyed
pixels (`np.bincount`). One isolated teammate's mass is measured per session
(`isolated_mass`) from blobs holding exactly one stored ring fit with no other
icon within four radii. A blob holds `max(ring fits in it, round(mass /
isolated))` teammates, the mass counting from `max(MULTI_K, isolated p95 /
median)`, plus the self icon where the stored self fit touches it. The
stacked-icon owner's continuous key (`stack_fit.frame_maps`, `source="soft"`)
is the alternative; it costs more than the whole blob step, where the
reader's key is already paid for; in `calibrate` it joined an isolated
icon's fragments more often but parted icons 2.2-3 radii apart far less
often.

Crowds (`track_crowds`)
-----------------------
A crowd is a tracked blob holding two or more icons, with at least one ring
fit or the self fit in it (the top icon of a stack is drawn whole; teal mass
alone is a barrier, an ability or the widget's transition), or a blob that
carries a track that vanished while the roster licenses it. Each frame its
blob is associated with last frame's by pixel overlap of the label images
(one `np.bincount` over the joint labels; a centroid within one outer radius
otherwise), so it survives edge distortion and joint motion. Its state is
cheap: bounding box, area, mass, centroid and second moments of the
hole-filled blob. It resolves after `CLOSE_HOLD` frames holding one icon and
nothing hidden.

* **Members.** Ring-fit tracks (the stored `round_entity` entities) seen
  inside the blob are visible members. A track that vanishes for `VANISH_MS`
  hides in the blob that carries it (its last blob followed through each
  frame's heaviest successor); its position is the region (the blob outline),
  set-valued, `rests_on` its last observation. The hidden count is
  `max(icons - visible, entered)`, and all crowds' hidden counts together
  never exceed the roster's shortfall (`round_lifetimes.ally_capacity` over
  `roster_window`, less the frame's ring fits); the guard counts the crowd
  frames where mass alone would exceed it (an ally ability drawn in team
  colour inflates a blob). An unread capacity (0.3.0) is unknown: the
  round's last read carries forward, `rests_on` its time, licensing entries
  but never evicting; only a frame whose capacity was read evicts
  (`count_restored`). Hidden members with no entry track stay unnamed,
  reason `no_entry_track`, unless the lineup (the four most-observed names
  of the stored entity verdicts) less the dead, the visible and the entered
  leaves exactly as many names as unnamed members in one crowd: then
  elimination names them, a claim that `depends_on` every entity whose
  verdict it excluded.
* **No search inside a crowd.** No pose, facing or stacked-icon fit is made
  inside it; an ability drawn over it is present in the crowd, at the
  crowd's resolution (the player, 2026-10-04: "Knowing a skye dog is in a
  group of people and missed or didn't result in a kill is enough"). The
  spike and enemy readers are untouched.
* **Split detectors**, each on the crowd's own blob: `cc` its successors are
  two or more pieces each of at least `SPLIT_PIECE` isolated icons; `erode`
  the hole-filled blob eroded by `ERODE_R` outer radii holds two or more
  pieces (it fires as the neck thins); `elong` the hole-filled blob's
  second-moment elongation exceeds two outer-radius discs `ELONG_D_R` radii
  apart. Each fires when its condition holds `HOLD` frames, timed at the
  run's first frame, and is also reported at one frame (`@1`). The self fit
  leaving the blob, held `SELF_HOLD` frames, is a split under every
  detector. A held `cc` split ends the crowd: each piece holding two icons
  becomes a crowd, the heaviest inherits the hidden members, and the pieces'
  ring fits within `EMERGE_WINDOW_MS` are assigned jointly to the hidden
  members (crowd-region-0.2.0's `assign_emergers`) and named by the
  `adjudication.identity` arbiter over the stored verdict and the crowd's
  claim, which `depends_on` the member's entry track. An audit every
  `AUDIT_EVERY` crowd frames is stored apart and is never a trigger.
* **Merges and ends.** Two crowds whose blobs meet merge; a single icon or
  blob joining a crowd's blob is a `join`. A crowd whose blob has no
  successor ends (`vanished`: death, leaving the widget, round end), its
  hidden members with it; a stored death verdict naming a hidden member ends
  that member.

Scoring (truth is evaluation only; the tracker reads pixels and stored rows)
---------------------------------------------------------------------------
`replay`: true separations on replay truth (`prototypes/replay_truth.py`
through MapFrame) against each detector's split events; containment of
hidden members' true positions in the outline; identity at emergence; cost.
`riot`: at Riot kill instants on the fixed handful, the stacked living
allies the ring fits miss (crowd-region-0.2.0's count), against tracked
crowds built with the stored stack-fit members removed, their member names,
and the stored stack fit, with a shifted-position chance baseline (the
ally moved `CHANCE_R` radii four ways). Split recall is quoted only as its
excess over the same events shifted +-3 s and +-6 s (`split_chance`); cap
evictions are scored against the replay (`score_evictions`). `price`:
stack_fit's stored time against the blob step's cost, on the session's
stored ally-icon usage. Both `replay` and `riot` persist the crowds in
event form (`write_rows`, `crowds_<sid>.jsonl` in the analysis output).
bdfdcf009dba is both the calibration session and one of the three Riot
sessions, so its Riot scores are not independent of the cuts.

Outcome (2026-10-04, crowd-blob-0.3.0)
--------------------------------------
Inputs: the stored streams copied by crowd-region-0.2.0 (`--events-from`).
On 9acf02f98283 `round_entity` rests on ally-icon-0.9.3 while `ally_icon` is
0.12.0: positions, entities and names come from `round_entity`; the
`ally_icon` frame rows serve only as the clock. The handful's streams are
consistent (ally-icon-0.11.0).

*Riot kill instants* (the fixed handful; bdfdcf009dba also calibrated the
cuts). Of [metric:crowd_blob/riot_pool@fixed3#ring_missed=87] stacked
living allies the ring fits miss, the pre-registered measure (0.1.0's P1,
strictly inside a crowd's outline, predicted 40) holds
[metric:crowd_blob/riot_pool@fixed3#crowd_contains=10]; those crowds list
the ally's name for [metric:crowd_blob/riot_pool@fixed3#crowd_name_listed=6];
[metric:crowd_blob/riot_pool@fixed3#neither=67] lie in neither a crowd nor
stack_fit (crowd-region-0.2.0: [metric:crowd_region/riot_pool@fixed3#neither=47]).
P1 failed. Post hoc, not pre-registered: within one icon radius of the
outline the crowds hold [metric:crowd_blob/riot_pool@fixed3#crowd_r_contains=54]
and name [metric:crowd_blob/riot_pool@fixed3#crowd_r_name_listed=29]
(neither: [metric:crowd_blob/riot_pool@fixed3#crowd_r_neither=31]); the
same allies moved three radii four ways score
[metric:crowd_blob/riot_pool_chance@fixed3#chance_r_contains=20.25] by chance
(strictly inside: [metric:crowd_blob/riot_pool_chance@fixed3#chance_contains=6.25]).

*Split detection* (9acf02f98283, the only capture with a replay;
[metric:crowd_blob/replay@9acf02f98283#true_separations=167] true
separations). Shifting every split event +-3 s keeps its place and loses
its timing, yet still "detects" a share; only the excess is detection.
`elong` at one frame detects
[metric:crowd_blob/replay@9acf02f98283#elong_at1_detected_share=0.7485],
[metric:crowd_blob/replay@9acf02f98283#elong_at1_shift3s_share=0.3712] when
shifted 3 s, an excess of
[metric:crowd_blob/replay@9acf02f98283#elong_at1_excess_over_shift3s=0.3773]
(over 6 s [metric:crowd_blob/replay@9acf02f98283#elong_at1_excess_over_shift6s=0.5689]),
the largest, at
[metric:crowd_blob/replay@9acf02f98283#elong_at1_false_per_crowd_minute=44.42]
unmatched splits per crowd-minute. Held two frames: `cc`
[metric:crowd_blob/replay@9acf02f98283#cc_excess_over_shift3s=0.1677],
`erode` [metric:crowd_blob/replay@9acf02f98283#erode_excess_over_shift3s=0.2036],
`elong` [metric:crowd_blob/replay@9acf02f98283#elong_excess_over_shift3s=0.2454]
over the 3 s shift. The 6 s shift scores lower than the 3 s shift
(`cc` [metric:crowd_blob/replay@9acf02f98283#cc_shift6s_share=0.0808]
against [metric:crowd_blob/replay@9acf02f98283#cc_shift3s_share=0.2036]):
separations cluster in time, so the 3 s shift is the stricter baseline.

*Capacity.* The roster capacity was unread on
[metric:crowd_blob/replay@9acf02f98283#capacity_unread_share=0.3196] of
[metric:crowd_blob/replay@9acf02f98283#crowd_frames=8368] crowd frames; the
round's last read carried
[metric:crowd_blob/replay@9acf02f98283#capacity_carried_frames=2634] of them
and [metric:crowd_blob/replay@9acf02f98283#capacity_unknown_frames=40] stayed
unknown. Carrying it licensed more entries, and the read frames then
evicted more: [metric:crowd_blob/replay@9acf02f98283#evictions=237] cap
evictions, of which the replay shows
[metric:crowd_blob/replay@9acf02f98283#evictions_wrong_still_in=181] wrong
(the member within one radius of the outline) and
[metric:crowd_blob/replay@9acf02f98283#evictions_right=48] right (outside or
dead). The cap, as the shortfall less the frame's ring fits, evicts wrongly;
it should flag the excess as a surprise, not evict.

*Containment.* A hidden member's true position lies inside the outline on
[metric:crowd_blob/replay@9acf02f98283#containment_entered=0.331] of
member-frames and within one radius on
[metric:crowd_blob/replay@9acf02f98283#containment_entered_within_r=0.8505].

*Cost.* Blobs, association, membership, split tests, outlines
([metric:crowd_blob/replay@9acf02f98283#cost_outlines_us=29.4] us) and
emergence ([metric:crowd_blob/replay@9acf02f98283#cost_emergence_us=19.4] us)
cost [metric:crowd_blob/replay@9acf02f98283#cost_us_per_frame=1533.3] us a
frame single-threaded on 9acf02f98283's cached frames (0.2.0 measured 1988.3
under other load). On bdfdcf009dba's stored usage stack_fit is
[metric:crowd_blob/price@bdfdcf009dba#stack_fit_share=0.5813] of the reader;
replacing it with crowds at 1533.3 us saves
[metric:crowd_blob/price@bdfdcf009dba#saved_share=0.5613]
([metric:crowd_blob/price@bdfdcf009dba#saved_ms_per_frame=43.04] ms a frame;
at 1988.3 us the same arithmetic gives 0.5554 and 42.59 ms), and
[metric:crowd_blob/price@bdfdcf009dba#saved_share_vectorised=0.3992] with
master's vectorised stack_fit (29.9 / 55.8 of its old time, as ally-vectorise
measured). The prior-first reader (`ally_prior.py`) supersedes this design.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crowd_region as v1  # noqa: E402  (stored-row Session, truth contexts, assignment)

#: 0.1.0 (2026-10-04): the design fixed in the store's `notes/predictions.jsonl`
#: (task crowd-blobsplit-20261004) before any truth was read.
#: 0.2.0: the self fit's parting is held `SELF_HOLD` frames like every other
#: split condition; found on 9acf02f98283, so its split scores there are
#: development scores (the Riot handful scores no split).
#: 0.3.0: an unread roster capacity carries the round's last read forward
#: (`rests_on` its time) and never evicts; region rows carry members in event
#: form and are persisted (`write_rows`); the cost counts outlines and
#: emergence; the crop cache is read on one decoder thread.
#: 0.4.0 (2026-10-06): the stream joins the crop cache by nearest time
#: (`frame_join`), not exact time; c817691bcd15's two grids differ in phase,
#: and the exact join had dropped 43% of its frames.
CROWD_BLOB_VERSION = "crowd-blob-0.4.0"
STORE = v1.STORE
ANALYSIS = STORE / "analysis" / "crowd-blobsplit-20261004"

#: The team colour read: the reader's per-frame key ("mask") or the
#: stacked-icon owner's continuous key ("soft"); see `FrameBlobs`.
SOURCE = "mask"
#: Blur of the coverage, in icon outer radii (`stack_fit.Shape.r_out`), and
#: the cut, as a share of one model icon's blurred ring density. Chosen with
#: the source on bdfdcf009dba's pixels against the reader's own ring fits,
#: no truth read (`calibrate`): an isolated ring fit meets one blob on
#: [metric:crowd_blob/calibrate@bdfdcf009dba#iso_one_share=0.9278] of 457.
SIGMA_R = 0.45
LEVEL = 0.35
#: A blob lighter than this share of one isolated icon is noise.
MIN_MASS = 0.3
#: A blob holds two or more icons by mass from at least this ratio (the
#: session's isolated 95th percentile raises it; cut once, here).
MULTI_K = 1.5
#: A parted piece weighs at least this share of one isolated icon (a lighter
#: piece is a fragment of the pale ring).
SPLIT_PIECE = 0.4
#: A detector's condition holds this many consecutive frames to fire.
HOLD = 2
#: The self fit's parting from a blob is held as long (0.2.0: 0.1.0 fired it
#: on one frame, and on 9acf02f98283 those were most of the unmatched cc
#: splits, a development finding on the scored session).
SELF_HOLD = HOLD
#: A crowd whose blob holds fewer than two icons and no hidden member this
#: many consecutive frames is resolved.
CLOSE_HOLD = 3
#: The erosion split detector's radius, in outer radii.
ERODE_R = 0.5
#: The elongation split detector's level: two model discs this far apart,
#: in outer radii.
ELONG_D_R = 1.8
#: An entity unseen this long has vanished (crowd-region-0.2.0's value).
VANISH_MS = 200.0
#: Emergers of one split this close in time are assigned jointly.
EMERGE_WINDOW_MS = 1000.0
#: The fixed-in-advance audit: every this many crowd frames, stored apart.
AUDIT_EVERY = 15
DETECTORS = ("cc", "erode", "elong")


def _below_normal() -> None:
    v1._below_normal()
    cv2.setNumThreads(1)
    single_thread_cache_reads()


class _OneThreadCv2:
    """`cv2` as `reticle.roi_cache` sees it, with every `VideoCapture` asked
    for one decoder thread. FFmpeg's FFV1 decoder otherwise takes a thread
    per core: 900 crops of bdfdcf009dba cost 3.7 s of CPU in 0.7 s of wall
    time, and 3.4 s in 3.5 s with `CAP_PROP_N_THREADS` 1;
    `OPENCV_FFMPEG_CAPTURE_OPTIONS` "threads;1" changed nothing."""

    def __getattr__(self, name):
        return getattr(cv2, name)

    @staticmethod
    def VideoCapture(path, *a):
        if a:
            return cv2.VideoCapture(path, *a)
        return cv2.VideoCapture(path, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])


def single_thread_cache_reads() -> None:
    """Read the crop cache on one decoder thread (this process only)."""
    from reticle import roi_cache
    if not isinstance(roi_cache.cv2, _OneThreadCv2):
        roi_cache.cv2 = _OneThreadCv2()


# ----------------------------------------------------------------- pixels

def model_density(shape, sigma: float, binary: bool = False) -> float:
    """One model teammate's blurred ring density at gain 1: the median of
    the blurred teal layer along the ring's centre line (`binary`: of the
    layer keyed at one half, as the reader's key sees it)."""
    k = shape.reach + int(math.ceil(3 * sigma)) + 2
    g = np.arange(-k, k + 1, dtype=np.float32)
    ky, kx = np.meshgrid(g, g, indexing="ij")
    t, _ = shape.layers(kx, ky, 0.0)
    if binary:
        t = (t > 0.5).astype(np.float32)
    D = cv2.GaussianBlur(t, (0, 0), sigma)
    rho = np.hypot(kx, ky)
    ring = np.abs(rho - (shape.r_in + shape.r_out) / 2) < 0.5
    ring &= kx < 0                                       # away from the lobe
    return float(np.median(D[ring]))


def elongation(mu20, mu02, mu11):
    """sqrt(l1 / l2) of second central moments, vectorised."""
    tr = mu20 + mu02
    d = np.sqrt(np.maximum((mu20 - mu02) ** 2 + 4 * mu11 ** 2, 0.0))
    l1, l2 = (tr + d) / 2, (tr - d) / 2
    return np.sqrt(l1 / np.maximum(l2, 1e-6))


def elongation_level(shape) -> float:
    """Two filled model discs of the outer radius, `ELONG_D_R` radii apart."""
    R = shape.r_out
    k = int(math.ceil(R * (1 + ELONG_D_R))) + 2
    g = np.arange(-k, k + 1, dtype=np.float32)
    ky, kx = np.meshgrid(g, g, indexing="ij")
    h = ELONG_D_R * R / 2
    m = ((np.hypot(kx - h, ky) <= R) | (np.hypot(kx + h, ky) <= R)).astype(np.uint8)
    mo = cv2.moments(m, binaryImage=True)
    return float(elongation(mo["mu20"], mo["mu02"], mo["mu11"]))


class Pixels:
    """One session's baked geometry, the minimap crop cache and the
    stacked-icon owner's maps (`stack_fit.Fitter`, at the map scale)."""

    def __init__(self, sid: str):
        from reticle import geometry, team_vision
        from reticle.profiles import get_profile
        from reticle.roi_cache import RoiCache
        from reticle.stack_fit import Fitter
        from reticle.store import Store

        st = Store(STORE)
        man = st.read_manifest(sid)
        prof = get_profile(man["source_profile"])
        inp, why = team_vision.load_inputs(st.root, sid, prof, int(man["source"]["width"]),
                                           int(man["source"]["height"]))
        if inp is None:
            raise SystemExit(f"{sid}: no geometry ({why})")
        self.floor, self.slab, self.static, self.box = inp.floor, inp.slab, inp.static, inp.box
        self.cache, why = RoiCache.load(st.root, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        k = geometry.key_of(sid, st.root)
        ms = geometry.map_scale(k, st.root)
        if ms is None:
            raise SystemExit(f"{sid}: no map scale")
        self.fitter = Fitter(ms.scale, self.static, self.floor, self.slab)
        self.shape = self.fitter.shape
        self.sigma = SIGMA_R * self.shape.r_out
        self.source = SOURCE
        self.level = {"soft": LEVEL * model_density(self.shape, self.sigma),
                      "mask": LEVEL * model_density(self.shape, self.sigma, binary=True)}
        self.elong_level = elongation_level(self.shape)
        r = max(1, int(round(ERODE_R * self.shape.r_out)))
        self.erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, float))

    def crops(self, times):
        """(t, crop) for each asked time `frame_join.grid_join` joins to a
        cache frame, in order: `t` is the time asked, the crop the cache's
        nearest frame. The two grids need not share a phase."""
        from reticle.frame_join import grid_join

        x0, y0, x1, y1 = self.box
        times = np.asarray(list(times), float)
        if not times.size:
            return
        j = grid_join(times, self.cache_t, self.cache.record["hz"], min_rate=0.0)
        if j.index is None:
            return
        asked = defaultdict(list)
        for t, k in zip(times[j.joined], j.index[j.joined]):
            asked[float(self.cache_t[k])].append(float(t))
        for smp in self.cache.samples(list(asked), rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            for t in asked[float(smp.t_ms)]:
                yield t, crop


class FrameBlobs:
    """One frame's blobs: label image and per-blob stats (index 0 unused).

    `source` "mask" reads the ally-icon reader's per-frame teal key
    (`minimap.ally_mask` on the floor, which the reader computes on every
    drawn frame); "soft" reads the stacked-icon owner's continuous key
    (`stack_fit.frame_maps`, `max(T - B, 0) * W`), which the reader computes
    only where its stack gate opens. Either is blurred (`cv2.GaussianBlur`,
    sigma `SIGMA_R` outer radii) and cut once at the level."""

    __slots__ = ("lbl", "n", "box", "area", "mass", "cx", "cy", "C")

    def __init__(self, px: Pixels, crop: np.ndarray, source: str | None = None):
        source = source or px.source
        if source == "soft":
            from reticle.stack_fit import frame_maps
            T, B, W = frame_maps(crop, px.fitter.static_key, px.floor)
            C = np.maximum(T - B, 0.0) * W
        else:
            from reticle.minimap import ally_mask
            C = (ally_mask(crop) & px.floor).astype(np.float32)
        D = cv2.GaussianBlur(C, (0, 0), px.sigma)
        M = (D > px.level[source]).astype(np.uint8)
        n, lbl, st, cen = cv2.connectedComponentsWithStats(M, connectivity=8)
        self.C, self.lbl, self.n = C, lbl, n
        self.box = st[:, :4]
        self.area = st[:, 4]
        on = C > 0
        self.mass = np.bincount(lbl[on], weights=C[on], minlength=n)
        # a blob that never touches the opaque slab is the world behind the
        # see-through widget, as `minimap.icons`'s `support` rules
        self.mass[np.bincount(lbl[px.slab], minlength=n) == 0] = 0.0
        self.cx, self.cy = cen[:, 0], cen[:, 1]


def filled(lbl_roi: np.ndarray, i: int) -> np.ndarray:
    """Blob `i` of a label window with its holes filled (the portrait inside
    a ring), as uint8: the region a crowd reports."""
    m = (lbl_roi == i).astype(np.uint8)
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m
    flood = pad.copy()
    mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 1)
    holes = flood[1:-1, 1:-1] == 0
    return (m | holes).astype(np.uint8)


def split_tests(px: Pixels, F: FrameBlobs, i: int) -> dict:
    """The erosion and elongation tests on blob `i`'s own window."""
    x, y, w, h = (int(v) for v in F.box[i])
    pad = int(math.ceil(px.shape.r_out))
    H, W = F.lbl.shape
    a, b, c, d = max(0, y - pad), min(H, y + h + pad), max(0, x - pad), min(W, x + w + pad)
    m = filled(F.lbl[a:b, c:d], i)
    er = cv2.erode(m, px.erode_k)
    ne, _l, est, _c = cv2.connectedComponentsWithStats(er, connectivity=8)
    min_px = max(2, int(0.25 * math.pi * (ERODE_R * px.shape.r_out) ** 2))
    pieces = int((est[1:, 4] >= min_px).sum()) if ne > 1 else 0
    mo = cv2.moments(m, binaryImage=True)
    el = float(elongation(mo["mu20"], mo["mu02"], mo["mu11"])) if mo["m00"] > 0 else 1.0
    return {"erode_pieces": pieces, "elong": el, "filled_px": int(mo["m00"]),
            "win": (a, c), "mask": m}


# ----------------------------------------------------------------- stored rows

def frame_clock(S: v1.Session, px: Pixels) -> np.ndarray:
    """Indices into `S.fr_*` of the drawn frames inside the cache's spans that
    join a cache frame by nearest time (`frame_join.grid_join`, the cache a
    grid stream at its recorded rate). Raises `JoinRefused` below the join floor: the stream and
    the cache then sample different clocks. The join's stamp lands on
    `px.frame_join`."""
    from reticle import roi_cache
    from reticle.frame_join import grid_join

    spans = px.cache.record.get("spans")
    inside = S.fr_drawn & (roi_cache.spans_mask(S.fr_t, spans) if spans
                           else np.ones(S.fr_t.shape, bool))
    cand = np.flatnonzero(inside)
    j = grid_join(S.fr_t[cand], px.cache_t, px.cache.record["hz"]).require()
    px.frame_join = j.stamp()
    return cand[j.joined]


def disc_offsets(r: float):
    """Pixel offsets within `r`, nearest first."""
    k = int(math.ceil(r))
    g = np.arange(-k, k + 1)
    dy, dx = np.meshgrid(g, g, indexing="ij")
    d = np.hypot(dx, dy)
    keep = d <= r
    o = np.argsort(d[keep], kind="stable")
    return dx[keep][o], dy[keep][o]


def blob_of(lbl: np.ndarray, x, y, off) -> np.ndarray:
    """The label nearest each point within the offsets' disc (0 where none),
    vectorised over points and offsets."""
    x = np.asarray(x, float)
    if not x.size:
        return np.zeros(0, np.int64)
    H, W = lbl.shape
    xs = np.clip(np.round(x).astype(int)[:, None] + off[0][None], 0, W - 1)
    ys = np.clip(np.round(np.asarray(y, float)).astype(int)[:, None] + off[1][None], 0, H - 1)
    L = lbl[ys, xs]
    hit = L > 0
    first = np.argmax(hit, axis=1)
    return np.where(hit.any(axis=1), L[np.arange(L.shape[0]), first], 0).astype(np.int64)


def isolated_mass(S: v1.Session, px: Pixels, idx: np.ndarray, n: int = 300) -> dict:
    """One isolated teammate's soft blob mass: the median over blobs holding
    exactly one stored ally ring fit with no other icon (self included)
    within four radii, on up to `n` frames spread over the clock."""
    off = disc_offsets(px.shape.r_out)
    a = np.searchsorted(S.ob_f, S.fr_f[idx], side="left")
    b = np.searchsorted(S.ob_f, S.fr_f[idx], side="right")

    def iso_of(i, j):
        x, y = S.ob_x[i:j], S.ob_y[i:j]
        D = np.hypot(x[:, None] - x[None], y[:, None] - y[None])
        np.fill_diagonal(D, np.inf)
        return (~S.ob_self[i:j]) & (D.min(axis=1) > 4 * S.r)

    cand = np.asarray([k for k, (i, j) in enumerate(zip(a, b)) if j > i and iso_of(i, j).any()])
    if not cand.size:
        return {"mass": None, "n": 0}
    pick = cand[np.unique(np.linspace(0, cand.size - 1, min(n, cand.size)).astype(int))]
    t_of = {round(float(S.fr_t[idx[k]]), 3): k for k in pick}
    masses, areas = [], []
    for t, crop in px.crops([S.fr_t[idx[k]] for k in pick]):
        k = t_of[round(t, 3)]
        F = FrameBlobs(px, crop)
        i, j = a[k], b[k]
        iso = iso_of(i, j)
        lab = blob_of(F.lbl, S.ob_x[i:j], S.ob_y[i:j], off)
        cnt = np.bincount(lab, minlength=F.n)
        for q in np.flatnonzero(iso):
            if lab[q] > 0 and cnt[lab[q]] == 1:
                masses.append(F.mass[lab[q]])
                areas.append(F.area[lab[q]])
    m = np.asarray(masses)
    return {"mass": float(np.median(m)) if m.size else None, "n": int(m.size),
            "p10": float(np.percentile(m, 10)) if m.size else None,
            "p90": float(np.percentile(m, 90)) if m.size else None,
            "p95": float(np.percentile(m, 95)) if m.size else None,
            "p05": float(np.percentile(m, 5)) if m.size else None,
            "area_px_median": float(np.median(areas)) if areas else None}


def lineup_names(S: v1.Session) -> tuple[list, str | None]:
    """The four teammates' names as the stored entity verdicts give them
    (the four most-observed names among ally entities, the self's excluded),
    and the self's name. It rests on `adjudication.identity`'s verdicts, so
    an elimination claim declares `depends_on` the entities it used."""
    cnt_self, cnt = Counter(), Counter()
    vals, counts = np.unique(S.ob_e, return_counts=True)
    is_self = np.zeros(len(S.ent_ids), bool)
    is_self[S.ob_e[S.ob_self]] = True
    for e, c in zip(vals, counts):
        a = S.agent[e]
        if a is not None:
            (cnt_self if is_self[e] else cnt)[a] += int(c)
    me = cnt_self.most_common(1)[0][0] if cnt_self else None
    return [a for a, _ in cnt.most_common() if a != me][:4], me


def calibrate(S: v1.Session, px: Pixels, n: int = 200) -> dict:
    """Blob integrity against the reader's own ring fits (no truth): for each
    source, blur and level, on `n` frames spread over the clock, the share of
    isolated ring fits whose outer-radius disc meets exactly one blob, and of
    same-frame ring-fit pairs whether they share a blob: pairs within one
    outer radius should (`overlap_joined`), pairs 2.2-3 outer radii apart
    should not (`apart_parted`)."""
    idx = frame_clock(S, px)
    pick = idx[np.unique(np.linspace(0, idx.size - 1, n).astype(int))]
    a = np.searchsorted(S.ob_f, S.fr_f[pick], side="left")
    b = np.searchsorted(S.ob_f, S.fr_f[pick], side="right")
    t_of = {round(float(S.fr_t[k]), 3): q for q, k in enumerate(pick)}
    off = disc_offsets(px.shape.r_out)
    R = px.shape.r_out
    combos = [(s, sg, lv) for s in ("mask", "soft") for sg in (0.2, 0.3, 0.45)
              for lv in (0.25, 0.35, 0.5)]
    tally = {c: Counter() for c in combos}
    from reticle.minimap import ally_mask
    from reticle.stack_fit import frame_maps
    for t, crop in px.crops(S.fr_t[pick]):
        q = t_of[round(t, 3)]
        i, j = a[q], b[q]
        x, y, sf = S.ob_x[i:j], S.ob_y[i:j], S.ob_self[i:j]
        x, y = x[~sf], y[~sf]
        if not x.size:
            continue
        D = np.hypot(x[:, None] - x[None], y[:, None] - y[None])
        np.fill_diagonal(D, np.inf)
        iso = D.min(axis=1) > 4 * S.r
        iu = np.triu_indices(x.size, 1)
        dd = D[iu]
        T, B, W = frame_maps(crop, px.fitter.static_key, px.floor)
        keys = {"soft": np.maximum(T - B, 0.0) * W,
                "mask": (ally_mask(crop) & px.floor).astype(np.float32)}
        for (s, sg, lv) in combos:
            sig = sg * R
            Dn = cv2.GaussianBlur(keys[s], (0, 0), sig)
            level = lv * model_density(px.shape, sig, binary=s == "mask")
            nn, lbl = cv2.connectedComponents((Dn > level).astype(np.uint8), connectivity=8)
            dx, dy = off
            H, Wd = lbl.shape
            xs = np.clip(np.round(x).astype(int)[:, None] + dx[None], 0, Wd - 1)
            ys = np.clip(np.round(y).astype(int)[:, None] + dy[None], 0, H - 1)
            L = lbl[ys, xs]
            nb = np.asarray([np.unique(r_[r_ > 0]).size for r_ in L])
            c = tally[(s, sg, lv)]
            c["iso"] += int(iso.sum())
            c["iso_one"] += int((iso & (nb == 1)).sum())
            c["iso_none"] += int((iso & (nb == 0)).sum())
            c["iso_many"] += int((iso & (nb > 1)).sum())
            lab = blob_of(lbl, x, y, off)
            same = (lab[iu[0]] == lab[iu[1]]) & (lab[iu[0]] > 0)
            ov, ap = dd < R, (dd > 2.2 * R) & (dd < 3 * R)
            c["overlap_pairs"] += int(ov.sum())
            c["overlap_joined"] += int((ov & same).sum())
            c["apart_pairs"] += int(ap.sum())
            c["apart_parted"] += int((ap & ~same).sum())
    out = {}
    for (s, sg, lv), c in tally.items():
        out[f"{s}/sigma{sg}/level{lv}"] = {
            **dict(c), "iso_one_share": round(c["iso_one"] / max(1, c["iso"]), 4),
            "overlap_joined_share": round(c["overlap_joined"] / max(1, c["overlap_pairs"]), 4),
            "apart_parted_share": round(c["apart_parted"] / max(1, c["apart_pairs"]), 4)}
    return out


# ----------------------------------------------------------------- tracker

def _run(c: dict, name: str, cond: bool, t: float, ev: dict, events: list) -> None:
    """Advance one detector's run on crowd `c`: it fires `name@1` on the
    run's first frame and `name` when the run reaches `HOLD` frames, each
    timed at the run's first frame (`fired_t` says when it was known)."""
    if not cond:
        c[name] = (0, None)
        return
    n, t0 = c.get(name, (0, None))
    n, t0 = n + 1, (t if n == 0 else t0)
    c[name] = (n, t0)
    if n == 1:
        events.append({**ev, "kind": "split", "detector": f"{name}@1", "t": t0, "fired_t": t})
    if n == HOLD:
        events.append({**ev, "kind": "split", "detector": name, "t": t0, "fired_t": t})


def track_crowds(S: v1.Session, px: Pixels, iso: float, *, timing: bool = False,
                 rounds=None) -> dict:
    """Crowds over one session: blobs from the crop cache, members from the
    stored rows. Returns region rows, events (split per detector, merge,
    join, opened, vanished), member episodes, emergences, audits (stored
    apart) and the count guard."""
    from reticle.adjudication.identity import AgentIdentityArbiter, identity_claim
    from reticle.round_lifetimes import ally_capacity, roster_window

    r_out = px.shape.r_out
    off = disc_offsets(r_out)
    iso_d = iso
    iso = iso_d["mass"]
    # a blob holds two icons by mass from the larger of MULTI_K and the 95th
    # percentile of one isolated icon's mass, measured on this session
    multi_k = max(MULTI_K, iso_d["p95"] / iso)
    min_mass, piece_mass = MIN_MASS * iso, SPLIT_PIECE * iso
    idx = frame_clock(S, px)
    fpos = np.searchsorted(S.ob_f, S.fr_f, side="left")
    fend = np.searchsorted(S.ob_f, S.fr_f, side="right")
    lineup, _me = lineup_names(S)
    deaths = sorted((d for d in S.deaths if d.get("side") == "ally"), key=lambda d: d["t_ms"])
    d_t = np.asarray([d["t_ms"] for d in deaths], float)
    regions, events, episodes, emergences, audits = [], [], [], [], []
    guard = Counter()
    cost = defaultdict(float)
    crowd_frames = 0
    for rd in (rounds or S.rounds):
        t0r, t1r = rd["t_start_ms"], rd["t_end_ms"]
        ks = idx[(S.fr_t[idx] >= t0r) & (S.fr_t[idx] <= t1r)]
        if not ks.size:
            continue
        crowds: dict[str, dict] = {}
        cap_last = None                      # (capacity, t of the read it rests on)
        carrier: dict[int, int] = {}         # entity -> blob carrying it this frame
        last: dict[int, tuple] = {}          # entity -> (t, x, y, observation key)
        seen: set = set()
        hidden_in: dict[int, str] = {}
        pending: list[dict] = []             # open emergence windows after a split
        prevF, prev_t = None, None
        nid = [0]

        def new_crowd(t, comps, how, parent=None):
            cid = f"{S.sid}:R{rd['round_no']}:B{nid[0]:03d}"
            nid[0] += 1
            crowds[cid] = {"id": cid, "onset": t, "comps": list(comps), "how": how,
                           "parent": parent, "hidden": {}, "frames": 0, "self_prev": False,
                           "merged_from": []}
            return crowds[cid]

        def end_member(c, e, t, how, extra=None):
            mb = c["hidden"].pop(e)
            hidden_in.pop(e, None)
            episodes.append({**mb, "crowd": c["id"], "end_t": t, "end": how,
                             "unresolved_ms": t - mb["onset"], **(extra or {})})

        crop_iter = px.crops(S.fr_t[ks])
        for k in ks:
            _tc, crop = next(crop_iter)
            t = float(S.fr_t[k])
            fidx = int(S.fr_f[k])
            tc0 = time.perf_counter()
            F = FrameBlobs(px, crop)
            tc1 = time.perf_counter()
            keep = F.mass >= min_mass
            keep[0] = False
            # this frame's stored ring fits and self fit, placed in blobs
            a, b = fpos[k], fend[k]
            ids, xs, ys, sf = S.ob_e[a:b], S.ob_x[a:b], S.ob_y[a:b], S.ob_self[a:b]
            keys = S.ob_key[a:b]
            lab = blob_of(F.lbl, xs, ys, off)
            lab = np.where(keep[lab], lab, 0)
            ring = np.bincount(lab[~sf], minlength=F.n)
            self_comp = int(lab[sf][0]) if sf.any() else 0
            ratio = F.mass / iso
            is_self = ((np.arange(F.n) == self_comp) & (self_comp > 0)).astype(int)
            n_area = np.where(ratio >= multi_k, np.maximum(2, np.rint(ratio)), 1).astype(int)
            n_icons = np.maximum(n_area, ring) + is_self
            n_ally = int((~sf).sum())
            cap = ally_capacity(roster_window(S.roster_t, S.roster_a, t), bool(sf.any()))
            # 0.3.0: an unread capacity is unknown, not absent; the last read
            # in the round carries forward (`rests_on` its time) and licenses
            # entries, but only a frame whose capacity was read may evict
            cap_read = cap is not None
            if cap_read:
                cap_last = (cap, t)
            elif cap_last is not None:
                cap = cap_last[0]
            short = None if cap is None else max(0, cap - n_ally)
            # association: pixel overlap of last frame's blobs with this frame's
            succ, pred = defaultdict(list), defaultdict(list)
            if prevF is not None:
                both = (prevF.lbl > 0) & (F.lbl > 0)
                O = np.bincount(prevF.lbl[both].astype(np.int64) * F.n + F.lbl[both],
                                minlength=prevF.n * F.n).reshape(prevF.n, F.n)
                O[:, ~keep] = 0
                for p_, c_ in zip(*(v.tolist() for v in np.nonzero(O))):
                    succ[p_].append(c_)
                    pred[c_].append(p_)
                if F.n > 1:                          # no overlap: centroid within r_out
                    for c in crowds.values():
                        for p_ in c["comps"]:
                            if succ.get(p_):
                                continue
                            d = np.hypot(F.cx - prevF.cx[p_], F.cy - prevF.cy[p_])
                            d[~keep] = np.inf
                            j = int(np.argmin(d))
                            if d[j] <= r_out:
                                succ[p_].append(j)
                                pred[j].append(p_)
            tc2 = time.perf_counter()
            # a carried entity follows its blob's heaviest successor
            new_carrier = {}
            for e, p_ in carrier.items():
                s_ = succ.get(p_)
                if s_:
                    new_carrier[e] = max(s_, key=lambda j: F.mass[j])
            for e, l_ in zip(ids.tolist(), lab.tolist()):
                if l_:
                    new_carrier[e] = l_
            carrier = new_carrier
            # crowds: continue, split (cc held), vanish, merge
            held: dict[int, str] = {}
            split_now = []
            for cid in sorted(crowds, key=lambda c_: crowds[c_]["onset"]):
                c = crowds[cid]
                p0 = c["comps"][0]
                s_ = sorted({j for p_ in c["comps"] for j in succ.get(p_, [])},
                            key=lambda j: -F.mass[j])
                ev = {"crowd": cid, "fidx": fidx, "x": float(prevF.cx[p0]),
                      "y": float(prevF.cy[p0])}
                if not s_:
                    events.append({**ev, "kind": "vanished", "t": t})
                    for e in list(c["hidden"]):
                        end_member(c, e, t, "vanished")
                    del crowds[cid]
                    continue
                qual = [j for j in s_ if F.mass[j] >= piece_mass]
                _run(c, "cc", len(qual) >= 2, t, ev, events)
                if c["cc"][0] >= HOLD:
                    split_now.append((c, s_))
                    continue
                mine = [j for j in s_ if j not in held]
                other = {held[j] for j in s_ if j in held}
                if other:                                   # two crowds meet: merge
                    kc = crowds[sorted(other)[0]]
                    kc["comps"] += [j for j in mine if j not in kc["comps"]]
                    for j in mine:
                        held[j] = kc["id"]
                    kc["hidden"].update(c["hidden"])
                    for e in c["hidden"]:
                        hidden_in[e] = kc["id"]
                    kc["merged_from"].append(cid)
                    del crowds[cid]
                    events.append({"kind": "merge", "crowd": kc["id"], "from": cid, "t": t,
                                   "fidx": fidx, "x": float(F.cx[s_[0]]), "y": float(F.cy[s_[0]])})
                    continue
                c["comps"] = s_
                for j in s_:
                    held[j] = cid
                # a blob or a single icon joining the crowd's blob
                if any(p_ not in c["comps_prev"] for j in s_ for p_ in pred.get(j, [])) \
                        if "comps_prev" in c else False:
                    events.append({"kind": "join", "crowd": cid, "t": t, "fidx": fidx,
                                   "x": float(F.cx[s_[0]]), "y": float(F.cy[s_[0]])})
            # a held split: each piece holding two icons is a crowd, the heaviest
            # (or, failing one, the heaviest piece) inherits the unresolved
            # members; every piece's ring fits are the emergers (the expensive work)
            for c, s_ in split_now:
                del crowds[c["id"]]
                pieces = [j for j in s_ if j not in held]
                heir = None
                for j in pieces:
                    if n_icons[j] >= 2:
                        cc = new_crowd(t, [j], "split", parent=c["id"])
                        held[j] = cc["id"]
                        heir = heir or cc
                if heir is None and c["hidden"] and pieces:
                    heir = new_crowd(t, [pieces[0]], "split", parent=c["id"])
                    held[pieces[0]] = heir["id"]
                members = dict(c["hidden"])
                if heir is not None:
                    heir["hidden"].update(c["hidden"])
                    for e in c["hidden"]:
                        hidden_in[e] = heir["id"]
                pending.append({"crowd": c["id"], "t": t, "fidx": fidx,
                                "members": {mb["e"]: mb for mb in members.values()},
                                "prior_seen": set(seen), "emergers": [],
                                "pieces": set(pieces)})
            # a multi-icon blob no crowd holds opens one; a blob read as
            # several icons by its mass alone must be icon-shaped (a spawn
            # barrier is a long teal bar)
            for j in np.flatnonzero(keep & (n_icons >= 2)).tolist():
                if j in held:
                    continue
                if ring[j] + is_self[j] == 0:
                    # the top icon of a stack is drawn whole, so a crowd holds a
                    # ring fit or the self fit; teal mass alone is a barrier, an
                    # ability or the widget's transition
                    guard["mass_only_unanchored"] += 1
                    continue
                cc = new_crowd(t, [j], "opened")
                held[j] = cc["id"]
                events.append({"kind": "opened", "crowd": cc["id"], "t": t, "fidx": fidx,
                               "x": float(F.cx[j]), "y": float(F.cy[j]),
                               "n_icons": int(n_icons[j])})
            # tracks: seen again ends a hidden member; vanished hides in its carrier
            vis = set(ids.tolist())
            for q, e in enumerate(ids.tolist()):
                last[e] = (t, float(xs[q]), float(ys[q]), keys[q])
                seen.add(e)
                cid = hidden_in.get(e)
                if cid is not None and cid in crowds and e in crowds[cid]["hidden"]:
                    end_member(crowds[cid], e, t, "reobserved")
            for e, (tl, x, y, key) in list(last.items()):
                if e in vis or e in hidden_in or tl < 0 or t - tl < VANISH_MS:
                    continue
                last[e] = (-1.0, x, y, key)                 # vanished once
                j = carrier.get(e, 0)
                if not j:
                    continue
                if short is None:
                    guard["entry_capacity_never_read"] += 1
                    continue
                if not short:
                    continue
                cid = held.get(j)
                if cid is None:
                    cc = new_crowd(t, [j], "entered")
                    cid = held[j] = cc["id"]
                    events.append({"kind": "opened", "crowd": cid, "t": t, "fidx": fidx,
                                   "x": float(F.cx[j]), "y": float(F.cy[j]),
                                   "n_icons": int(n_icons[j]), "by_entry": True})
                crowds[cid]["hidden"][e] = {
                    "entity": S.ent_ids[e], "agent": S.agent[e], "onset": tl, "e": e,
                    "entry_xy": [round(x, 2), round(y, 2)], "rests_on": key}
                hidden_in[e] = cid
            # a death the killfeed names ends the hidden member of that name
            if d_t.size:
                lo, hi = np.searchsorted(d_t, [prev_t if prev_t is not None else t0r, t],
                                         side="right")
                for d in deaths[lo:hi]:
                    for c in crowds.values():
                        for e, mb in list(c["hidden"].items()):
                            if mb["agent"] is not None and mb["agent"] == d.get("victim"):
                                end_member(c, e, t, "death_named", {"death_t_ms": d["t_ms"]})
            # the count: all crowds hide no more than the roster's shortfall
            area_want = {cid: max(0, int(sum(n_icons[j] - ring[j] - is_self[j]
                                             for j in c["comps"])))
                         for cid, c in crowds.items()}
            want = {cid: max(area_want[cid], len(c["hidden"])) for cid, c in crowds.items()}
            if crowds:
                guard["crowd_frames"] += 1
                guard["crowd_frames_capacity_unread"] += int(not cap_read)
                guard["crowd_frames_capacity_carried"] += int(not cap_read and short is not None)
                guard["crowd_frames_capacity_unknown"] += int(short is None)
            if short is not None and crowds:
                guard["area_exceeds_shortfall"] += int(sum(area_want.values()) > short)
                if sum(want.values()) > short:
                    guard["capped" if cap_read else "over_carried_capacity_kept"] += 1
                    hid = sorted((mb["onset"], cid, e) for cid, c in crowds.items()
                                 for e, mb in c["hidden"].items())
                    for _on, cid, e in (hid[:max(0, len(hid) - short)] if cap_read else []):
                        end_member(crowds[cid], e, t, "count_restored",
                                   {"end_fidx": fidx, "capacity": cap, "capacity_t": t})
                    room = short - sum(len(c["hidden"]) for c in crowds.values())
                    for cid in sorted(want, key=lambda c_: crowds[c_]["onset"]):
                        extra = min(max(0, want[cid] - len(crowds[cid]["hidden"])), max(0, room))
                        want[cid] = len(crowds[cid]["hidden"]) + extra
                        room -= extra
            # resolved: the blob holds one icon and nothing is hidden in it
            for cid in list(crowds):
                c = crowds[cid]
                single = sum(n_icons[j] for j in c["comps"]) < 2 and not c["hidden"]
                c["single_run"] = c.get("single_run", 0) + 1 if single else 0
                if c["single_run"] >= CLOSE_HOLD and c.get("cc", (0, None))[0] == 0:
                    j = c["comps"][0]
                    events.append({"kind": "resolved", "crowd": cid, "t": t, "fidx": fidx,
                                   "x": float(F.cx[j]), "y": float(F.cy[j])})
                    del crowds[cid]
                    want.pop(cid)
            # elimination: the lineup less the dead, the visible and the entered
            dead ={d.get("victim") for d in deaths if t0r <= d["t_ms"] <= t}
            vis_names = {S.agent[e] for e in vis if S.agent[e] is not None}
            hid_names = {mb["agent"] for c in crowds.values() for mb in c["hidden"].values()
                         if mb["agent"] is not None}
            free = [nm for nm in lineup if nm not in dead | vis_names | hid_names]
            unnamed = {cid: max(0, want[cid] - sum(1 for mb in c["hidden"].values()
                                                   if mb["agent"] is not None))
                       for cid, c in crowds.items()}
            elim = {}
            if sum(unnamed.values()) and len(free) == sum(unnamed.values()) and \
                    sum(1 for v in unnamed.values() if v) == 1:
                cid = next(c_ for c_, v in unnamed.items() if v)
                elim[cid] = {"names": free, "depends_on": sorted(S.ent_ids[e] for e in vis
                                                                 if S.agent[e] is not None)}
            tc3 = time.perf_counter()
            # the split detectors, each on the crowd's own blob
            tests = {}
            for cid, c in crowds.items():
                j = c["comps"][0]
                tst = split_tests(px, F, j)
                parted = sum(1 for j2 in c["comps"] if F.mass[j2] >= piece_mass) >= 2
                ev = {"crowd": cid, "fidx": fidx, "x": float(F.cx[j]), "y": float(F.cy[j])}
                if c["frames"]:
                    _run(c, "erode", parted or tst["erode_pieces"] >= 2, t, ev, events)
                    _run(c, "elong", parted or tst["elong"] > px.elong_level, t, ev, events)
                else:   # a crowd's first frame sets its state; a rise is needed to fire
                    c["erode"] = (0 if not (parted or tst["erode_pieces"] >= 2) else HOLD + 1, t)
                    c["elong"] = (0 if not (parted or tst["elong"] > px.elong_level)
                                  else HOLD + 1, t)
                # the self fit leaving the blob: a split under every detector,
                # held as they are (0.2.0; 0.1.0 fired on one frame)
                st_ = bool(self_comp and self_comp in c["comps"])
                if st_:
                    c["self_prev"], c["self_off"] = True, (0, None)
                elif c["self_prev"] and sf.any():
                    n_, t0s = c.get("self_off", (0, None))
                    n_, t0s = n_ + 1, (t if n_ == 0 else t0s)
                    c["self_off"] = (n_, t0s)
                    for det in DETECTORS:
                        nm = f"{det}@1" if n_ == 1 else det if n_ == SELF_HOLD else None
                        if nm is not None:
                            events.append({**ev, "kind": "split", "detector": nm, "t": t0s,
                                           "fired_t": t, "self_parted": True})
                    if n_ >= SELF_HOLD:
                        c["self_prev"] = False
                c["frames"] += 1
                tests[cid] = tst
            tc4 = time.perf_counter()
            if timing:
                cost["blobs"] += tc1 - tc0
                cost["associate"] += tc2 - tc1
                cost["members"] += tc3 - tc2
                cost["split_tests"] += tc4 - tc3
                cost["frames"] += 1
            tc5 = time.perf_counter()
            # emergence: ring fits in a split's pieces within the window
            for pnd in list(pending):
                if t - pnd["t"] > EMERGE_WINDOW_MS:
                    _resolve_emergers(S, pnd, emergences, AgentIdentityArbiter, identity_claim)
                    pending.remove(pnd)
                    continue
                got = {m["e"] for m in pnd["emergers"]}
                for q, (e, l_) in enumerate(zip(ids.tolist(), lab.tolist())):
                    if l_ and e not in got and (e not in pnd["prior_seen"] or e in pnd["members"]):
                        pnd["emergers"].append({"e": e, "t": t, "fidx": fidx,
                                                "xy": (float(xs[q]), float(ys[q])),
                                                "continued": e in pnd["members"]})
            tc6 = time.perf_counter()
            # region rows (the blob outline, set-valued) and the audit, stored apart
            if crowds:
                crowd_frames += 1
                if crowd_frames % AUDIT_EVERY == 0:
                    for cid, c in crowds.items():
                        audits.append({"crowd": cid, "t": t, "fidx": fidx,
                                       "n_icons": int(sum(n_icons[j] for j in c["comps"])),
                                       "ring": int(sum(ring[j] for j in c["comps"])),
                                       "hidden": want[cid]})
            for cid, c in crowds.items():
                polys = []
                for q, j in enumerate(c["comps"]):
                    tst = tests[cid] if q == 0 else split_tests(px, F, j)
                    cs, _h = cv2.findContours(tst["mask"], cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_SIMPLE)
                    if cs:
                        polys.append((max(cs, key=cv2.contourArea).reshape(-1, 2)
                                      + np.array([tst["win"][1], tst["win"][0]])
                                      ).astype(np.float32))
                comps = c["comps"]
                visible = [S.agent[e] for e, l_ in zip(ids.tolist(), lab.tolist()) if l_ in comps]
                j = comps[0]
                regions.append({
                    "crowd": cid, "fidx": fidx, "t": t, "polys": polys,
                    "box": [int(v) for v in F.box[j]], "area_px": tests[cid]["filled_px"],
                    "pieces": len(comps),
                    "mass_ratio": round(float(sum(ratio[j2] for j2 in comps)), 3),
                    "n_icons": int(sum(n_icons[j2] for j2 in comps)),
                    "ring": int(sum(ring[j2] for j2 in comps)),
                    "self": bool(self_comp and self_comp in comps), "hidden": want.get(cid, 0),
                    "hidden_entered": [mb["e"] for mb in c["hidden"].values()],
                    "members": [{"entity": mb["entity"], "agent": mb["agent"],
                                 "status": "hidden", "position": {"region": cid},
                                 "rests_on": mb["rests_on"], "since_ms": mb["onset"]}
                                for mb in c["hidden"].values()]
                    + [{"entity": S.ent_ids[e], "agent": S.agent[e], "status": "visible",
                        "observation_key": keys[q]}
                       for q, (e, l_) in enumerate(zip(ids.tolist(), lab.tolist()))
                       if l_ in comps and not sf[q]],
                    "elimination": ({"names": elim[cid]["names"],
                                     "depends_on": elim[cid]["depends_on"],
                                     "unnamed": unnamed.get(cid, 0)}
                                    if cid in elim else None),
                    "capacity": None if short is None else {
                        "shortfall": short, "read": cap_read,
                        "rests_on_t_ms": None if cap_last is None else cap_last[1]},
                    "names": sorted({nm for nm in [mb["agent"] for mb in c["hidden"].values()]
                                     + visible if nm is not None}
                                    | set(elim.get(cid, {}).get("names", []))),
                    "elim_names": elim.get(cid, {}).get("names", []),
                    "unnamed": unnamed.get(cid, 0),
                    "unnamed_reason": None if not unnamed.get(cid) else (
                        "elimination" if cid in elim else "no_entry_track"),
                    "cx": float(F.cx[j]), "cy": float(F.cy[j]),
                    "elong": round(tests[cid]["elong"], 3)})
                c["comps_prev"] = list(comps)
            if timing:
                cost["emergence"] += tc6 - tc5
                cost["outlines"] += time.perf_counter() - tc6
            prevF, prev_t = F, t
        for cid in list(crowds):
            for e in list(crowds[cid]["hidden"]):
                end_member(crowds[cid], e, t1r, "round_end")
        for pnd in pending:
            _resolve_emergers(S, pnd, emergences, AgentIdentityArbiter, identity_claim)
    return {"regions": regions, "events": events, "episodes": episodes,
            "emergences": emergences, "audits": audits, "guard": dict(guard),
            "crowd_frames": crowd_frames, "frames": int(idx.size), "cost_s": dict(cost),
            "iso_mass": iso, "multi_k": multi_k, "r_out": r_out, "elong_level": px.elong_level,
            "level": px.level[px.source], "sigma": px.sigma, "source": px.source}


def _resolve_emergers(S, pnd, emergences, Arbiter, identity_claim):
    """A split's emergers assigned jointly to the crowd's hidden members
    (crowd-region-0.2.0's `assign_emergers`) and named by the arbiter over
    the stored verdict and the crowd's claim, which depends on the member's
    entry track."""
    for m in pnd["emergers"]:
        if m["continued"]:
            emergences.append({"crowd": pnd["crowd"], "t": m["t"], "x": m["xy"][0],
                               "y": m["xy"][1], "entity": S.ent_ids[m["e"]],
                               "stored_agent": S.agent[m["e"]], "agent": S.agent[m["e"]],
                               "how": "continuity", "split_t": pnd["t"]})
    taken = {m["e"] for m in pnd["emergers"]}
    members = [mb for e, mb in pnd["members"].items() if e not in taken]
    fresh = [m for m in pnd["emergers"] if not m["continued"]]
    if not fresh:
        return
    asg = v1.assign_emergers([S.agent[m["e"]] for m in fresh], members)
    for m, g in zip(fresh, asg):
        mb = members[g["member"]] if g["member"] is not None else None
        ent = S.ent_ids[m["e"]]
        ar = Arbiter()
        ar.add(identity_claim(ent, S.agent[m["e"]], channel="round_entity_verdict",
                              observed_at_ms=m["t"],
                              reason=None if S.agent[m["e"]] else "entity_unnamed"))
        ag = mb["agent"] if mb else None
        ar.add(identity_claim(ent, ag, channel="crowd_membership", observed_at_ms=m["t"],
                              reason=None if ag else (g["how"] if mb is None else "member_unnamed"),
                              source_version=CROWD_BLOB_VERSION,
                              depends_on=[mb["entity"]] if mb else None,
                              evidence={"crowd": pnd["crowd"], "how": g["how"],
                                        "alternatives": g["alternatives"],
                                        "rests_on": mb["rests_on"] if mb else None}))
        v = ar.verdict()[0]
        emergences.append({"crowd": pnd["crowd"], "t": m["t"], "x": m["xy"][0], "y": m["xy"][1],
                           "entity": ent, "stored_agent": S.agent[m["e"]], "crowd_agent": ag,
                           "agent": v["agent"], "status": v["status"], "how": g["how"],
                           "split_t": pnd["t"]})


# ----------------------------------------------------------------- scoring helpers

#: Truth separation (fixed in advance): a pair within one icon diameter for
#: this many frames, then past it for as many.
TRUTH_HOLD = 5
#: A split event explains a true separation within this many seconds and
#: this many icon radii of the pair's midpoint.
MATCH_S = 0.5
MATCH_R = 3.0
#: An event with no true separation within this window and distance is false.
FALSE_S = 1.0


def inside_any(polys, x: float, y: float, tol: float) -> bool:
    """Whether (x, y) lies within `tol` px of any outline in `polys`."""
    for p in polys:
        if len(p) >= 3 and cv2.pointPolygonTest(p.reshape(-1, 1, 2), (float(x), float(y)),
                                                True) >= -tol:
            return True
    return False


def truth_separations(t: np.ndarray, X: np.ndarray, Y: np.ndarray, r_icon: float,
                      rnd: np.ndarray) -> list[dict]:
    """True separation instants: a pair of living teammates within 2r for
    `TRUTH_HOLD` frames, then past 2r for `TRUTH_HOLD` frames, in one round."""
    out = []
    k = X.shape[1]
    for i in range(k):
        for j in range(i + 1, k):
            d = np.hypot(X[:, i] - X[:, j], Y[:, i] - Y[:, j])
            ok = np.isfinite(d)
            near = ok & (d < 2 * r_icon)
            far = ok & (d >= 2 * r_icon)
            run_near = 0
            q = 0
            n = d.size
            while q < n:
                if near[q]:
                    run_near += 1
                    q += 1
                    continue
                if far[q] and run_near >= TRUTH_HOLD and q + TRUTH_HOLD <= n and \
                        far[q:q + TRUTH_HOLD].all() and (rnd[q:q + TRUTH_HOLD] == rnd[q - 1]).all():
                    out.append({"t": float(t[q]), "pair": (i, j), "q": q,
                                "x": float((X[q - 1, i] + X[q - 1, j]) / 2),
                                "y": float((Y[q - 1, i] + Y[q - 1, j]) / 2)})
                run_near = 0
                q += 1
    return out


def score_splits(seps: list[dict], events: list[dict], r_icon: float, crowd_min: float,
                 regions_by_f=None, fr_of_q=None, X=None, Y=None) -> dict:
    """Each detector's split events against the true separations."""
    out = {}
    names = sorted({e["detector"] for e in events if e["kind"] == "split"})
    st = np.asarray([s["t"] for s in seps]) if seps else np.zeros(0)
    sx = np.asarray([s["x"] for s in seps]) if seps else np.zeros(0)
    sy = np.asarray([s["y"] for s in seps]) if seps else np.zeros(0)
    # a separation whose pair stood inside a tracked crowd just before it
    in_crowd = np.zeros(len(seps), bool)
    if regions_by_f is not None:
        for q, s in enumerate(seps):
            g = regions_by_f.get(fr_of_q[s["q"] - 1], [])
            i, j = s["pair"]
            for reg in g:
                if inside_any(reg["polys"], X[s["q"] - 1, i], Y[s["q"] - 1, i], r_icon) and \
                        inside_any(reg["polys"], X[s["q"] - 1, j], Y[s["q"] - 1, j], r_icon):
                    in_crowd[q] = True
                    break
    for nm in names:
        ev = [e for e in events if e["kind"] == "split" and e["detector"] == nm]
        et = np.asarray([e["t"] for e in ev])
        ex = np.asarray([e["x"] for e in ev])
        ey = np.asarray([e["y"] for e in ev])
        lat = np.full(len(seps), np.nan)
        if ev and seps:
            dt = (et[None, :] - st[:, None]) / 1000.0
            dd = np.hypot(ex[None, :] - sx[:, None], ey[None, :] - sy[:, None])
            ok = (np.abs(dt) <= MATCH_S) & (dd <= MATCH_R * r_icon)
            best = np.where(ok, np.abs(dt), np.inf).argmin(axis=1)
            hit = ok.any(axis=1)
            lat[hit] = dt[np.flatnonzero(hit), best[hit]]
            near = (np.abs(dt) <= FALSE_S) & (dd <= MATCH_R * r_icon)
            false = int((~near.any(axis=0)).sum())
        else:
            hit = np.zeros(len(seps), bool)
            false = len(ev)
        out[nm] = {"events": len(ev), "true_separations": len(seps),
                   "detected": int(hit.sum()),
                   "detected_share": round(float(hit.mean()), 4) if seps else None,
                   "in_crowd_separations": int(in_crowd.sum()),
                   "detected_share_in_crowd": round(float(hit[in_crowd].mean()), 4)
                   if in_crowd.any() else None,
                   "latency_s": v1._stats(lat[hit], 3),
                   "false_events": false,
                   "false_per_crowd_minute": round(false / max(crowd_min, 1e-9), 3)}
    return out


def _setup(sid: str, n_iso: int = 300, drop_stack: bool = False):
    S = v1.Session(sid, drop_stack=drop_stack)
    px = Pixels(sid)
    idx = frame_clock(S, px)
    iso = isolated_mass(S, px, idx, n=n_iso)
    return S, px, idx, iso


# ----------------------------------------------------------------- truth: replay

def score_replay(sid: str) -> dict:
    """Split detection, containment, identity at emergence and cost on one
    capture with replay truth (evaluation only)."""
    import riot_ground_truth as rg
    t0 = time.time()
    S, px, idx, iso = _setup(sid)
    R = track_crowds(S, px, iso, timing=True)
    ctx = v1.replay_context(sid)
    mf = ctx["mf"]
    r_icon = float(mf.icon_px)
    m_per_px = 1.0 / (mf.px_per_unit * 100.0)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "crowd_blob_version": CROWD_BLOB_VERSION, "events_from": str(v1.EVENTS),
           "ally_icon_version": S.ally_icon_version, "round_entity_inputs": S.round_entity_inputs,
           "ally_icon_stale": S.ally_icon_stale,
           "versions_used": "frame clock from ally_icon frame rows; positions, entities and "
                            "names from round_entity (and the ally_icon it rests on); blobs "
                            "from the minimap crop cache",
           "params": {"source": px.source, "sigma_r": SIGMA_R, "level": LEVEL,
                      "multi_k": R["multi_k"], "split_piece": SPLIT_PIECE, "hold": HOLD,
                      "erode_r": ERODE_R, "elong_d_r": ELONG_D_R,
                      "elong_level": round(px.elong_level, 3)},
           "iso": iso, "r_out_px": round(px.shape.r_out, 3), "r_icon_px": r_icon,
           "m_per_px": round(m_per_px, 4), "frames": R["frames"],
           "crowd_frames": R["crowd_frames"], "region_rows": len(R["regions"]),
           "guard": R["guard"]}
    # truth on the clock, in rounds
    t = S.fr_t[idx]
    rnd = np.full(t.size, -1)
    for rd in S.rounds:
        rnd[(t >= rd["t_start_ms"]) & (t <= rd["t_end_ms"])] = rd["round_no"]
    inr = rnd >= 0
    t, fq, rnd = t[inr], S.fr_f[idx][inr], rnd[inr]
    X, Y = v1.truth_px(ctx, t)
    seps = truth_separations(t, X, Y, r_icon, rnd)
    regions_by_f = defaultdict(list)
    for g in R["regions"]:
        regions_by_f[g["fidx"]].append(g)
    crowd_min = len(R["regions"]) / 15.0 / 60.0
    out["crowd_minutes"] = round(crowd_min, 2)
    out["splits"] = score_splits(seps, R["events"], r_icon, crowd_min, regions_by_f, fq, X, Y)
    out["split_excess"] = split_chance(seps, R["events"], r_icon, crowd_min, out["splits"])
    # containment: hidden members' true positions in the outline
    ent_truth, ob_truth = v1.entity_truth(S, ctx)
    rows = [(g, e) for g in R["regions"] for e in g["hidden_entered"]]
    if rows:
        tt = np.asarray([g["t"] for g, _e in rows])
        Xh, Yh = v1.truth_px(ctx, tt)
        c = Counter()
        for q, (g, e) in enumerate(rows):
            j = ent_truth[e]
            if j < 0 or not np.isfinite(Xh[q, j]):
                c["no_truth"] += 1
                continue
            c["scored"] += 1
            c["inside"] += inside_any(g["polys"], Xh[q, j], Yh[q, j], 0.0)
            c["inside_r"] += inside_any(g["polys"], Xh[q, j], Yh[q, j], r_icon)
        out["containment_entered"] = {**dict(c),
                                      "share": round(c["inside"] / max(1, c["scored"]), 4),
                                      "share_within_r": round(c["inside_r"] / max(1, c["scored"]), 4)}
    # truly hidden allies (no ring or self fit assigned within the gate) at crowd frames
    k = X.shape[1]
    seen = np.zeros((fq.size, k), bool)
    pos = {int(f): q for q, f in enumerate(fq)}
    ok = ob_truth >= 0
    for f, j in zip(S.ob_f[ok], ob_truth[ok]):
        q = pos.get(int(f))
        if q is not None:
            seen[q, j] = True
    c = Counter()
    D = np.hypot(X[:, :, None] - X[:, None, :], Y[:, :, None] - Y[:, None, :])
    D[:, np.arange(k), np.arange(k)] = np.inf
    stacked = np.nanmin(np.where(np.isfinite(D), D, np.inf), axis=2) < 2 * r_icon
    for q in range(fq.size):
        live = np.isfinite(X[q])
        hid = live & ~seen[q] & stacked[q]
        if not hid.any():
            continue
        g = regions_by_f.get(int(fq[q]), [])
        for j in np.flatnonzero(hid):
            c["stacked_hidden"] += 1
            c["in_crowd"] += any(inside_any(reg["polys"], X[q, j], Y[q, j], 0.0) for reg in g)
            c["in_crowd_r"] += any(inside_any(reg["polys"], X[q, j], Y[q, j], r_icon) for reg in g)
    out["containment_stacked_hidden"] = {
        **dict(c), "share": round(c["in_crowd"] / max(1, c["stacked_hidden"]), 4),
        "share_within_r": round(c["in_crowd_r"] / max(1, c["stacked_hidden"]), 4)}
    # region size
    ar = np.asarray([g["area_px"] for g in R["regions"]], float) * m_per_px ** 2
    out["region_m2"] = v1._stats(ar, 1)
    # identity at emergence, against the replay's agent at the emerger's place
    E = R["emergences"]
    if E:
        gate = rg.GATE_M * 100.0 * mf.px_per_unit
        et = np.asarray([x["t"] for x in E])
        Xe, Ye = v1.truth_px(ctx, et)
        Dm = np.hypot(Xe - np.asarray([x["x"] for x in E])[:, None],
                      Ye - np.asarray([x["y"] for x in E])[:, None])
        Dm = np.where(np.isfinite(Dm), Dm, np.inf)
        jj = Dm.argmin(axis=1)
        dd = Dm[np.arange(et.size), jj]
        tru = [ctx["agents"][j] if d_ <= gate else None for j, d_ in zip(jj, dd)]

        def outcome(names):
            return Counter("no_truth" if tr is None else "refused" if n is None else
                           "right" if rg.canon(n) == rg.canon(tr) else "wrong"
                           for n, tr in zip(names, tru))
        out["emergence"] = {"emergers": len(E), "by_how": dict(Counter(x["how"] for x in E)),
                            "arbiter": dict(outcome([x["agent"] for x in E])),
                            "stored_verdict_only": dict(outcome([x["stored_agent"] for x in E]))}
    P = R["episodes"]
    if P:
        un = np.asarray([p["unresolved_ms"] for p in P]) / 1000.0
        out["hidden_episodes"] = {"n": len(P), "by_end": dict(Counter(p["end"] for p in P)),
                                  "unresolved_s": v1._stats(un)}
        out["evictions"] = score_evictions(P, regions_by_f, ent_truth, ctx, r_icon)
    out["events"] = dict(Counter(e["kind"] for e in R["events"]))
    out["audits"] = len(R["audits"])
    c = R["cost_s"]
    nf = max(1, c.get("frames", 0))
    out["cost_us_per_frame"] = {kk: round(v / nf * 1e6, 1) for kk, v in c.items() if kk != "frames"}
    out["cost_us_per_frame"]["total"] = round(sum(v for kk, v in c.items() if kk != "frames")
                                              / nf * 1e6, 1)
    out["seconds"] = round(time.time() - t0, 1)
    write_rows(sid, R, S)
    return out


#: Shifts, in seconds, of the chance baseline for split detection: every
#: split event moved this far keeps its place and loses its timing.
CHANCE_SHIFTS_S = (3.0, 6.0)


def split_chance(seps, events, r_icon, crowd_min, scored) -> dict:
    """Each detector's recall less its shifted-event baseline: the share a
    detector 'detects' with every split event moved by +-3 s and +-6 s
    (place kept), which a crowd's frequent firing at a pair's place earns
    without timing. Only the excess is detection."""
    sp = [e for e in events if e["kind"] == "split"]
    base = defaultdict(dict)
    for sh in CHANCE_SHIFTS_S:
        for sign in (-1, 1):
            moved = [{**e, "t": e["t"] + sign * sh * 1000.0} for e in sp]
            for nm, v in score_splits(seps, moved, r_icon, crowd_min).items():
                base[nm].setdefault(sh, []).append(v["detected_share"] or 0.0)
    out = {}
    for nm, v in scored.items():
        d = {"detected_share": v["detected_share"]}
        for sh in CHANCE_SHIFTS_S:
            b = float(np.mean(base[nm].get(sh, [0.0])))
            d[f"shift{sh:g}s_share"] = round(b, 4)
            d[f"excess_over_shift{sh:g}s"] = round((v["detected_share"] or 0.0) - b, 4)
        out[nm] = d
    return out


def score_evictions(episodes, regions_by_f, ent_truth, ctx, r_icon) -> dict:
    """Each cap eviction (`count_restored`) against replay truth: right when
    the evicted member stood outside its crowd's outline by more than one
    icon radius (or was dead), wrong when inside or within it."""
    ev = [p for p in episodes if p["end"] == "count_restored"]
    c = Counter()
    if not ev:
        return dict(c)
    Xe, Ye = v1.truth_px(ctx, np.asarray([p["end_t"] for p in ev], float))
    for q, p in enumerate(ev):
        j = ent_truth[p["e"]]
        if j < 0:
            c["no_truth"] += 1
            continue
        if not np.isfinite(Xe[q, j]):
            c["right_dead"] += 1
            continue
        reg = [g for g in regions_by_f.get(p.get("end_fidx"), []) if g["crowd"] == p["crowd"]]
        if not reg:
            c["no_region"] += 1
            continue
        inside = inside_any(reg[0]["polys"], Xe[q, j], Ye[q, j], r_icon)
        c["wrong_still_in" if inside else "right_outside"] += 1
    c["evictions"] = len(ev)
    return dict(c)


def write_rows(sid: str, R: dict, S) -> Path:
    """The crowds in event form, one JSON row each, in the analysis output:
    `crowd_region` (the outline and its members, each hidden member's
    position the region and `rests_on` its entry observation; an
    elimination's names with `depends_on`), `crowd_member` (a hidden
    member's episode), `crowd_event` (opened, split, merge, join, resolved,
    vanished) and `crowd_emergence` (an emerger's name from the arbiter).
    Audits stay apart in `crowd_audit` rows."""
    path = ANALYSIS / f"crowds_{sid}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        def put(kind, row, drop=()):
            r = {"kind": kind, "session_id": sid, "crowd_blob_version": CROWD_BLOB_VERSION,
                 **{k: v for k, v in row.items() if k not in drop}}
            f.write(json.dumps(r, default=_default, separators=(",", ":")) + "\n")
        for g in R["regions"]:
            put("crowd_region", {**g, "t_ms": g["t"], "frame_idx": g["fidx"],
                                 "outline": [np.round(p, 1) for p in g["polys"]]},
                drop=("polys", "hidden_entered", "t", "fidx"))
        for p in R["episodes"]:
            put("crowd_member", {**p, "position": {"region": p["crowd"]}}, drop=("e",))
        for e in R["events"]:
            put("crowd_event", e)
        for m in R["emergences"]:
            put("crowd_emergence", m)
        for a in R["audits"]:
            put("crowd_audit", a)
    return path


# ----------------------------------------------------------------- truth: Riot

#: The shifted-position chance baseline moves a ring-missed ally this many
#: icon radii (four ways) and asks the same containment question.
CHANCE_R = 3.0


def score_riot(sid: str) -> dict:
    """At Riot kill instants: the stacked living allies the ring fits miss
    (crowd-region-0.2.0's count), against tracked crowds (built with the
    stored stack-fit members removed, as if that search never ran), their
    member names, and the stored stack fit."""
    import riot_ground_truth as rg
    t0 = time.time()
    S_all = v1.Session(sid)
    S, px, idx, iso = _setup(sid, drop_stack=True)
    R = track_crowds(S, px, iso)
    ctx = v1.riot_context(sid)
    mf = ctx["mf"]
    gate = rg.GATE_M * 100.0 * mf.px_per_unit
    r_icon = float(mf.icon_px)
    out = {"session": sid, "capture": S.manifest["source"]["path"],
           "crowd_blob_version": CROWD_BLOB_VERSION, "events_from": str(v1.EVENTS),
           "ally_icon_version": S.ally_icon_version, "stack_fit_version": S.stack_fit_version,
           "ally_icon_stale": S.ally_icon_stale, "iso": iso, "multi_k": R["multi_k"],
           "crowd_frames": R["crowd_frames"], "frames": R["frames"], "guard": R["guard"]}
    want = np.asarray([ctx["a"] + k["gameTime"] + rg.MINIMAP_LAG_MS for k in ctx["kills"]])
    fi = np.clip(np.searchsorted(S.fr_t, want), 1, S.fr_t.size - 1)
    fi = np.where(np.abs(S.fr_t[fi - 1] - want) <= np.abs(S.fr_t[fi] - want), fi - 1, fi)
    ok_f = (np.abs(S.fr_t[fi] - want) <= rg.FRAME_TOL_MS) & S.fr_drawn[fi]
    clock = set(S.fr_f[idx].tolist())
    regions_by_f = defaultdict(list)
    for g in R["regions"]:
        regions_by_f[g["fidx"]].append(g)
    dying_at = defaultdict(list)
    for k in ctx["kills"]:
        dying_at[(k["round"], k["gameTime"])].append(k)
    c = Counter()
    rows = []
    for k, f_i, okk in zip(ctx["kills"], fi, ok_f):
        if not okk:
            c["kill_no_frame"] += 1
            continue
        fidx = int(S.fr_f[f_i])
        locs = rg.truth_locations(k, dying_at)
        allies = [s for s in locs if ctx["who"][s]["teamId"] == ctx["team"]
                  and not locs[s].get("victim_added")]
        if not allies:
            continue
        T = np.asarray([mf.to_px(locs[s]["location"]["x"], locs[s]["location"]["y"])
                        for s in allies])
        DD = np.hypot(T[:, None, 0] - T[None, :, 0], T[:, None, 1] - T[None, :, 1])
        np.fill_diagonal(DD, np.inf)
        stacked = DD.min(axis=1) < 2 * mf.icon_px
        a_, b_ = np.searchsorted(S_all.ob_f, [fidx, fidx + 1])
        ox, oy, ost = S_all.ob_x[a_:b_], S_all.ob_y[a_:b_], S_all.ob_stack[a_:b_]
        ring = [(x, y) for x, y, s_ in zip(ox, oy, ost) if not s_]
        ring_hit = {i for i, _j, _d in rg.greedy_pairs([tuple(p) for p in T], ring, gate)}
        stk_idx = np.flatnonzero(ost)
        free = [i for i in range(len(allies)) if i not in ring_hit]
        sp = rg.greedy_pairs([tuple(T[i]) for i in free], [(ox[j], oy[j]) for j in stk_idx], gate)
        stk_hit = {free[i] for i, _j, _d in sp}
        regs = regions_by_f.get(fidx, [])
        for i, s in enumerate(allies):
            if not stacked[i]:
                continue
            if i not in ring_hit:
                # chance: the same ally moved CHANCE_R icon radii four ways
                for dx_, dy_ in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xs_ = T[i, 0] + dx_ * CHANCE_R * r_icon
                    ys_ = T[i, 1] + dy_ * CHANCE_R * r_icon
                    c["chance_r_contains_x4"] += any(inside_any(g["polys"], xs_, ys_, r_icon)
                                                     for g in regs)
                    c["chance_contains_x4"] += any(inside_any(g["polys"], xs_, ys_, 0.0)
                                                   for g in regs)
            c["stacked_allies"] += 1
            if i in ring_hit:
                c["ring_matched"] += 1
                continue
            c["ring_missed"] += 1
            truth_agent = ctx["agent_of"].get(s)
            in_stack = i in stk_hit
            c["stack_matched"] += in_stack
            if fidx not in clock:
                c["frame_not_on_clock"] += 1
            reg = next((g for g in regs if inside_any(g["polys"], T[i, 0], T[i, 1], 0.0)), None)
            reg_r = reg or next((g for g in regs if inside_any(g["polys"], T[i, 0], T[i, 1],
                                                                r_icon)), None)
            if reg_r is not None and reg is None:
                c["crowd_within_r_only"] += 1
            if reg_r is not None:
                c["crowd_r_contains"] += 1
                right_r = any(rg.canon(n) == rg.canon(truth_agent) for n in reg_r["names"])
                c["crowd_r_name_listed"] += int(right_r)
            else:
                c["crowd_r_neither" if not in_stack else "crowd_r_stack_only"] += 1
            if reg is None:
                c["crowd_missed"] += 1
                c["neither" if not in_stack else "stack_only"] += 1
                rows.append({"fidx": fidx, "agent": truth_agent, "in": False, "stack": in_stack})
                continue
            c["crowd_contains"] += 1
            c["both"] += in_stack
            names = reg["names"]
            right = any(rg.canon(n) == rg.canon(truth_agent) for n in names)
            c["crowd_name_" + ("listed" if right else "unknown" if reg["unnamed"] and not right
                               else "absent")] += 1
            c["crowd_name_by_elimination"] += int(right and truth_agent in reg["elim_names"])
            rows.append({"fidx": fidx, "agent": truth_agent, "in": True, "names": names,
                         "stack": in_stack, "hidden": reg["hidden"], "n_icons": reg["n_icons"]})
    c["chance_r_contains"] = round(c.pop("chance_r_contains_x4", 0) / 4.0, 2)
    c["chance_contains"] = round(c.pop("chance_contains_x4", 0) / 4.0, 2)
    out["kill_instants"] = dict(c)
    out["rows"] = rows
    write_rows(sid, R, S)
    # what skipping stack_fit inside crowds would save, on this session's frames
    in_crowd = np.isin(S_all.fr_f, list({g["fidx"] for g in R["regions"]}))
    out["stack_ran"] = int(S_all.fr_ran.sum())
    out["stack_ran_in_crowd"] = int((S_all.fr_ran & in_crowd).sum())
    out["seconds"] = round(time.time() - t0, 1)
    return out


#: stack_fit's time after ally-vectorise-20261004 (on master since a0383d5)
#: relative to before: 29.9 / 55.8 ms a frame on nine cached 300-frame
#: windows of the handful, three of them stack-heavy, as that commit
#: measured; the stored usage predates it.
VECTORISED_STACK_FIT = 29.9 / 55.8


def price(sid: str, blob_us: float) -> dict:
    """What replacing stack_fit with crowds saves, on the session's stored
    ally-icon usage (`reticle usage`), not a profile mean: stack_fit's whole
    stored time against the blob step's measured cost on every fed frame."""
    from reticle import usage
    rows = [r for r in usage.load(STORE, sid) if r.get("kind") != "command"
            and (r.get("readers") or {}).get("ally_icon")]
    if not rows:
        return {"session": sid, "reason": "no_stored_usage"}
    r = rows[-1]
    a = r["readers"]["ally_icon"]
    feed_s = a["feed"]["total_ns"] / 1e9
    n = a["feed"]["count"]
    st = (a.get("steps") or {}).get("stack_fit")
    pose = (a.get("steps") or {}).get("pose")
    if st is None:
        return {"session": sid, "reason": "no_stack_fit_step"}
    stack_s = st["total_ns"] / 1e9
    blob_s = blob_us * 1e-6 * n
    vec_stack = stack_s * VECTORISED_STACK_FIT
    vec_feed = feed_s - stack_s + vec_stack
    return {"session": sid, "usage_run": r.get("run_id"), "recorded_at": r.get("recorded_at"),
            "frames_fed": n, "feed_s": round(feed_s, 1), "stack_fit_s": round(stack_s, 1),
            "stack_fit_share": round(stack_s / feed_s, 4),
            "pose_s": round(pose["total_ns"] / 1e9, 1) if pose else None,
            "blob_us_per_frame": blob_us, "blob_s": round(blob_s, 1),
            "saved_share": round((stack_s - blob_s) / feed_s, 4),
            "saved_ms_per_frame": round((stack_s - blob_s) / n * 1e3, 2),
            "vectorised_stack_fit_s": round(vec_stack, 1),
            "saved_share_vectorised": round((vec_stack - blob_s) / vec_feed, 4)}


def _default(o):
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events-from", type=Path, default=None,
                    help="read the stored streams from this copy of <store>/events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("calibrate")
    p.add_argument("session")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("replay")
    p.add_argument("session")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("riot")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("price")
    p.add_argument("session")
    p.add_argument("--blob-us", type=float, required=True,
                   help="the blob step's measured cost per frame (the replay run's total)")
    p.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    if args.cmd == "price":
        s = price(args.session, args.blob_us)
        print(json.dumps(s, indent=1))
        if args.record and "reason" not in s:
            from reticle import metrics
            v = {k: s[k] for k in ("stack_fit_share", "saved_share", "saved_ms_per_frame",
                                   "saved_share_vectorised")}
            metrics.record("crowd_blob", part="price", session=args.session, values=v,
                           deps={"crowd_blob": CROWD_BLOB_VERSION},
                           context={"usage_run": s["usage_run"], "blob_us": args.blob_us,
                                    "vectorised_factor": VECTORISED_STACK_FIT})
            print(" ".join(f"[metric:crowd_blob/price@{args.session}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    cv2.setNumThreads(1)
    if args.events_from:
        v1.EVENTS = args.events_from
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    deps = {"crowd_blob": CROWD_BLOB_VERSION}
    if args.cmd == "calibrate":
        S = v1.Session(args.session)
        out = calibrate(S, Pixels(args.session), n=args.n)
        (ANALYSIS / f"calibrate_{args.session}.json").write_text(json.dumps(out, indent=1),
                                                                encoding="utf-8")
        print(json.dumps(out, indent=1))
        if args.record:
            from reticle import metrics
            ch = out[f"{SOURCE}/sigma{SIGMA_R}/level{LEVEL}"]
            v = {k: ch[k] for k in ("iso", "iso_one_share", "overlap_joined_share",
                                    "apart_parted_share")}
            metrics.record("crowd_blob", part="calibrate", session=args.session, values=v,
                           deps=deps, context={"chosen": f"{SOURCE}/sigma{SIGMA_R}/level{LEVEL}"})
            print(" ".join(f"[metric:crowd_blob/calibrate@{args.session}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    if args.cmd == "replay":
        s = score_replay(args.session)
        (ANALYSIS / f"replay_{args.session}.json").write_text(
            json.dumps(s, indent=1, default=_default), encoding="utf-8")
        print(json.dumps(s, indent=1, default=_default))
        if args.record:
            from reticle import metrics
            v = {"containment_entered": s.get("containment_entered", {}).get("share"),
                 "containment_stacked_hidden": s["containment_stacked_hidden"]["share"],
                 "cost_us_per_frame": s["cost_us_per_frame"]["total"],
                 "true_separations": s["splits"].get("cc", {}).get("true_separations")}
            for nm in ("cc", "erode", "elong", "cc@1", "erode@1", "elong@1"):
                sp = s["splits"].get(nm) or {}
                key = nm.replace("@1", "_at1")
                v[f"{key}_detected_share"] = sp.get("detected_share")
                v[f"{key}_detected_share_in_crowd"] = sp.get("detected_share_in_crowd")
                v[f"{key}_latency_median_s"] = (sp.get("latency_s") or {}).get("median")
                v[f"{key}_false_per_crowd_minute"] = sp.get("false_per_crowd_minute")
            v["in_crowd_separations"] = (s["splits"].get("cc") or {}).get("in_crowd_separations")
            v["containment_entered_within_r"] = s.get("containment_entered", {}).get(
                "share_within_r")
            v["containment_stacked_hidden_within_r"] = s["containment_stacked_hidden"][
                "share_within_r"]
            g = s["guard"]
            v["area_exceeds_shortfall_share"] = round(
                g.get("area_exceeds_shortfall", 0) / max(1, g.get("crowd_frames", 0)), 4)
            v["crowd_minutes"] = s["crowd_minutes"]
            em = s.get("emergence") or {}
            v["emergence_right"] = (em.get("arbiter") or {}).get("right")
            v["emergence_wrong"] = (em.get("arbiter") or {}).get("wrong")
            v["emergence_same_as_stored"] = int(em.get("arbiter") == em.get("stored_verdict_only"))
            metrics.record("crowd_blob", part="replay", session=args.session, values=v,
                           deps={**deps, "ally_icon": s["ally_icon_version"]})
            print(" ".join(f"[metric:crowd_blob/replay@{args.session}#{k}={x}]"
                           for k, x in v.items()))
        return 0
    if args.cmd == "riot":
        pool = Counter()
        for sid in args.sessions:
            s = score_riot(sid)
            (ANALYSIS / f"riot_{sid}.json").write_text(json.dumps(s, indent=1, default=_default),
                                                       encoding="utf-8")
            print(json.dumps({k: v for k, v in s.items() if k != "rows"}, indent=1,
                             default=_default))
            if args.record:
                from reticle import metrics
                ki = s["kill_instants"]
                v = {kk: ki.get(kk, 0) for kk in ("ring_missed", "crowd_contains",
                                                  "crowd_name_listed", "stack_matched",
                                                  "neither", "crowd_r_contains",
                                                  "crowd_r_name_listed", "crowd_r_neither",
                                                  "crowd_r_stack_only")}
                g = s["guard"]
                v["area_exceeds_shortfall"] = g.get("area_exceeds_shortfall", 0)
                v["crowd_frames"] = g.get("crowd_frames", 0)
                metrics.record("crowd_blob", part="riot", session=sid, values=v,
                               deps={**deps, "ally_icon": s["ally_icon_version"],
                                     "stack_fit": s["stack_fit_version"]})
                print(" ".join(f"[metric:crowd_blob/riot@{sid}#{k}={x}]" for k, x in v.items()))
                pool.update(v)
        if args.record and len(args.sessions) > 1:
            from reticle import metrics
            metrics.record("crowd_blob", part="riot_pool", session=f"fixed{len(args.sessions)}",
                           values=dict(pool), deps=deps, context={"sessions": args.sessions})
            print(" ".join(f"[metric:crowd_blob/riot_pool@fixed{len(args.sessions)}#{k}={x}]"
                           for k, x in pool.items()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
