r"""Minimap ability glyphs: each proposed disc's score against the game's minimap textures.

    .\.venv\Scripts\python.exe -m reticle scan <session> --only ability
    .\.venv\Scripts\python.exe -m reticle trial <session> --reader ability_glyph --from cache

Owns [owns:ability-glyph]. Stage 2 of `docs/MINIMAP_GLYPH_CHANNEL.md`
(section 2, "The glyph reader"): a `passes.Reader` that rides the ability
pass at 2 Hz on live samples and stores, per proposed disc and frame, how
well each candidate kit's game textures score there. It names nothing: the
tracks, the verdict and the identity claims are stage 3's
(`ability-disc-track`, `ability-glyph-name`, `agent-identity`). A score's
label ("Agent:Slot") and a row's `best` and `second` keys are observations
of which texture fits, never a name; only `ability-glyph-name`, through the
aggregator, names an agent.

Why. A thrown or placed ability draws a dark disc with a white glyph on the
minimap [domain:abilities/minimap-thrown-ability-icon]; the glyph is the
ability's own game texture, so the game files name it. The proposer
(`ability_icons`, which owns `ability-icon`) finds the discs; this reader reads
the proposer's candidates for the same frame and never reruns it.

Inputs, as versioned data from the store, never from `prototypes/`:

- the reference bank (`GLYPH_DATA["bank"]`, written by
  `prototypes/glyph_tables.py bank`): each catalogue key's 128 px glyphs,
  the ability's DisplayIcon and the exported minimap textures the stage 1
  tables were built on (the state inventory's minimap brushes and the
  player's texture answers, [domain:abilities/minimap-textures-deadlock]
  and its siblings), each with its game file's path and sha256. Game files,
  never mined captures.
- the rotation policy (`glyph-rotation-policy-0.1.1`): per key, upright (0
  deg) or every 15 deg, each row citing what decided it.
- the null table (`glyph-null-table-0.1.1`): per key, the cut that at most
  5% of the dev no-ability discs exceed at the key's policy search size.

`GlyphData.load` checks each file's version and the bank's pairing with the
tables (their sha256 as the bank recorded them), and the stream's head
records all three.

The matcher (`minimap-glyph-eval-0.3.0`'s, vectorised). Luma (YCrCb Y)
inside an r = 8.5 px x scale disc, masked Pearson over every template and
every centre within +-3 px (round(3 x scale) below scale 1), never
binarised [domain:capture/capture-resolution]. Each glyph shrinks to a
canvas of 11-22 px x scale with `INTER_AREA` and turns with `INTER_LINEAR`.
All discs of a frame score in one matrix product, on the GPU when cupy and
a CUDA device are present (`RETICLE_GLYPH=cpu` forces numpy).

The scale, a measured exception to the one transform. The matcher's scale
is `minimap.widget_scale` alone, not `geometry.MapScale.scale` (widget x
map zoom) as [domain:minimap/icons-follow-map-zoom] would have it: the null
table's cuts were measured on that basis (dev sessions at zoom 0.887 and
1.0), and a cut holds only at the matcher it was measured with. The canvas
search (11-22 px) spans the zoom's change in drawn size; the mask radius
and the shift do not follow it. The falsifier fired: rescored at the full
transform on 4f207c0c4e39 (zoom 0.892), the best key changed on 19.5% of
200 scored rows and the above-cut decision on 11.5%, over its 5% bound
(`glyph_reader/trial_020`, F4); at zoom 1.0 both agreed on every row. The
exception stands for now only because the trial sessions sit at the null
table's dev zooms (0.892 against 0.887, and 1.0), so the cuts are read at
the basis they were measured on. A session at another zoom has no valid
cut. A null remeasured at the full transform under a new table version
ends the exception; `docs/MINIMAP_GLYPH_CHANNEL.md` makes it a stage 3
prerequisite.

Gates from other channels, before any scheduling (stage 1's follow gates,
`prototypes/minimap_glyph_eval.py` `map_like` and `portrait_cover`): each
disc row stores `static_corr`, the masked Pearson of the crop's luma with
the baked static's (`ctx.map_reference()`, keyed by (map, profile), never a
session median [domain:capture/session-pixels-are-not-the-map]) inside the
matcher's disc, and `portrait`, stage 1's cover reason from the frame's
stored portraits (`StoredPortraits`: the `ally_icon` fits and self icon,
`ally-candidates`; stage 1 read `team_vision`, which is stale on the
variant session). `portrait_cover` lives here and the prototype calls it: the self icon covers within OCC_R; an ally covers
in the ring SAME_R..OCC_R, never within SAME_R, where the ally reader's fit
is the followed icon itself (a dark disc with a white glyph and a teal rim
fits as a portrait); two allies within SAME_R are a stack. A disc whose
`static_corr` reaches MAP_CORR is the map's (`static_like`); a covered one
keeps the cover's reason (`self_portrait`, `ally_portrait`, `ally_stack`).
Neither is scored, opens a window, or enters the audit or surprise paths;
the row keeps its reason and its measurements. Where a gate's input is
missing (no stored stream, a size mismatch, no stored row for the frame:
`portrait` "no_vision_row") the disc is scored and the head says why the
gate is unknown.

Not gated: the static disc at (21, 91) on 4f207c0c4e39, the variant
widget's top-left corner, where the void behind the widget reads as a dark
disc beside the radar ring. The baked static is placed right there; the
disc lies 80% off the map art's footprint (`geometry.footprint`), yet so do
real glyphs drawn over the void: 9 of the 226 labelled held-out glyph marks
sit less than half on the footprint, so a footprint gate would drop them.
Stage 3's tracks and the null table must answer it (`docs/MINIMAP_GLYPH_CHANNEL.md`).

Candidate sets. Continue the prior: the context set is the match lineup's
kits, both sides, as `lineup.glyph_candidates` admits them (named slots,
each refused slot's best guess as a rival), scored under the policy
rotations on every ungated disc. Each context row and read frame row
declares `rests_on` the lineup stamp, so the verdict never counts the
lineup again. The full set, every agent's kit, runs on two paths only, each
row marked by `set`:

- the audit: the first birth and every AUDIT_EVERY-th after it (a cadence
  fixed in advance, a design choice), scored against every kit, every key
  rotated, on each frame of its window. It measures what the lineup prior
  and the rotation policy hide. No null exists at that search size, so its
  rows store `best_cut` and `above_cut` null (`no_null_at_full_rotation`).
- the surprise: a window whose best context key never clears that key's
  null cut is rescored against every kit, policy rotations, when it
  closes. Never an audit sample.

The plan's per-view gate (each kit's textures as its view allows, from
`ability-states-gamedata-0.2.0`) is not built: both sides' full kits are
scored (`docs/MINIMAP_GLYPH_CHANNEL.md`, stage 2's revisions).

Windows. Continuation is the proposer's: a disc continues the previous
sample's disc whose stored verify binds to it
(`ability_icons.verified_continuations`), and its row `rests_on` that disc.
A birth is an ungated disc that continues no windowed disc. A window
schedules the audit and the surprise for WINDOW_MS after its birth; when
its schedule ends it still absorbs its disc for as long as the verify keeps
it, so a disc that persists past WINDOW_MS is never born again. The
verify's loss, a gated disc, or an unread frame ends a window. A window is
an execution schedule, not a track: `adjudication.ability` joins discs into
tracks from the stored rows.

Not done here (stage 3 or later): the follow at the cache's cadence (stage
1's S4 measured the 2 Hz arm equal on dev, 0 points apart), per-view texture
gating from the state inventory, the Deadlock:Q wall normals, naming, and
claims.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np

from .ability_icons import verified_continuations
from .minimap import widget_scale
from .usage import step as usage_step
from .version import ABILITY_GLYPH_VERSION, ABILITY_ICON_VERSION

#: The store files the reader reads: (directory under the store, version).
GLYPH_DATA = {"bank": ("analysis/glyph-bank-20261005b", "glyph-bank-0.2.0"),
              "policy": ("analysis/glyph-tables-20261005b", "glyph-rotation-policy-0.1.1"),
              "null": ("analysis/glyph-tables-20261005b", "glyph-null-table-0.1.1")}
#: The bank and tables' stamp, which `plan` compares (`ability_glyph`'s `glyph_bank`).
GLYPH_BANK_STAMP = "+".join(GLYPH_DATA[k][1] for k in ("bank", "policy", "null"))

#: The matcher's base values (px at the 465 px reference widget).
CANVAS_BASE = np.arange(11, 23, 1.0)
MASK_R_BASE = 8.5
SHIFT_BASE = 3
ROTATIONS = tuple(range(0, 360, 15))
#: A template whose masked pixels vary less than this is skipped (blank at that canvas).
FLAT_STD = 1e-3
#: Window rules (design choices, docs/MINIMAP_GLYPH_CHANNEL.md section 2).
WINDOW_MS = 3000.0
AUDIT_EVERY = 10
#: A disc whose luma correlates this well with the baked static's is the
#: map's (stage 1's follow gate, `prototypes/minimap_glyph_eval.py` MAP_CORR).
MAP_CORR = 0.7
SETS = ("context", "audit", "surprise")


def _agent_key(agent: str | None) -> str:
    """An agent name compared across stores: `KAY_O` and `KAY/O` are one."""
    return "".join(ch for ch in (agent or "").lower() if ch.isalnum())


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class GlyphData:
    """The reference bank, the rotation policy and the null table, loaded and
    checked against each other."""

    def __init__(self, keys, sources, rotating, cuts, provenance, files=None):
        #: Catalogue keys ("Agent:Slot"), sorted.
        self.keys: list[str] = keys
        #: key -> [(provenance, 128 px glyph)], the DisplayIcon first.
        self.sources: dict[str, list[tuple[str, np.ndarray]]] = sources
        #: Keys the policy searches at every rotation.
        self.rotating: set[str] = rotating
        #: key -> its per-key null cut (overall).
        self.cuts: dict[str, float] = cuts
        self.provenance: dict = provenance
        #: key -> [(game file under the export, sha256)], one per source.
        self.files: dict[str, list[tuple[str, str]]] = files or {}

    @classmethod
    def load(cls, store_root) -> "GlyphData":
        root = Path(store_root)
        bdir, bver = GLYPH_DATA["bank"]
        pdir, pver = GLYPH_DATA["policy"]
        ndir, nver = GLYPH_DATA["null"]
        bmeta_p = root / bdir / f"{bver}.json"
        bnpz_p = root / bdir / f"{bver}.npz"
        pol_p = root / pdir / f"{pver}.json"
        nul_p = root / ndir / f"{nver}.json"
        for p in (bmeta_p, bnpz_p, pol_p, nul_p):
            if not p.is_file():
                raise FileNotFoundError(f"glyph data missing: {p}")
        bmeta = json.loads(bmeta_p.read_text(encoding="utf-8"))
        pol = json.loads(pol_p.read_text(encoding="utf-8"))
        nul = json.loads(nul_p.read_text(encoding="utf-8"))
        for got, want, p in ((bmeta.get("version"), bver, bmeta_p), (pol.get("version"), pver, pol_p),
                             (nul.get("version"), nver, nul_p), (nul.get("policy_version"), pver, nul_p)):
            if got != want:
                raise ValueError(f"{p}: version {got!r}, expected {want!r}")
        shas = {"bank_npz": _sha256(bnpz_p), "policy": _sha256(pol_p), "null": _sha256(nul_p)}
        if shas["bank_npz"] != bmeta["npz_sha256"]:
            raise ValueError(f"{bnpz_p}: sha256 differs from {bmeta_p.name}")
        if (shas["policy"], shas["null"]) != (bmeta["tables"]["policy_sha256"],
                                              bmeta["tables"]["null_sha256"]):
            raise ValueError(f"{bmeta_p.name} was built on other tables than {pdir}")
        with np.load(bnpz_p) as z:
            glyphs = z["glyphs"].astype(np.float32)
            owner = [str(k) for k in z["keys"]]
            prov = [str(p) for p in z["provenance"]]
            fls = [str(f) for f in z["files"]]
            fsha = [str(h) for h in z["file_sha256"]]
        sources: dict = {}
        files: dict = {}
        for g, k, p, f, h in zip(glyphs, owner, prov, fls, fsha):
            sources.setdefault(k, []).append((p, g))
            files.setdefault(k, []).append((f, h))
        keys = sorted(sources)
        rows = {r["key"]: r for r in pol["rows"]}
        if set(rows) != set(keys):
            raise ValueError("the policy table and the bank hold different keys")
        rotating = {k for k, r in rows.items() if r["policy"] == "rotates"}
        cuts = {k: float(v["cut"]) for k, v in nul["keys"].items() if v.get("cut") is not None}
        provenance = {
            "stamp": GLYPH_BANK_STAMP,
            "bank": {"version": bver, "file": f"{bdir}/{bver}.npz", "sha256": shas["bank_npz"],
                     "glyphs_sha256": bmeta["glyphs_sha256"], "generator": bmeta["generator"],
                     "eval": bmeta["eval"], "build": bmeta["build"],
                     "answers_sha256": bmeta["references"]["answers_sha256"],
                     "state_inventory_sha256": bmeta["references"]["state_inventory_sha256"]},
            "policy": {"version": pver, "file": f"{pdir}/{pver}.json", "sha256": shas["policy"],
                       "decided_by": pol.get("decided_by"), "rotating": sorted(rotating)},
            "null": {"version": nver, "file": f"{ndir}/{nver}.json", "sha256": shas["null"],
                     "rate": nul.get("rate"), "cut": "per key, overall (`keys.<key>.cut`)",
                     "tie_margin": (nul.get("tie_margin") or {}).get("value")}}
        return cls(keys, sources, rotating, cuts, provenance, files)

    def keys_of(self, agents) -> list[str]:
        """The bank's keys of these agents' kits."""
        want = {_agent_key(a) for a in agents}
        return [k for k in self.keys if _agent_key(k.split(":", 1)[0]) in want]


# ------------------------------------------------------------------ the matcher


def window_geometry(scale: float) -> tuple[int, int, np.ndarray]:
    """(W, shift, disc mask) of the scoring window at a widget scale."""
    mr = MASK_R_BASE * scale
    w = int(np.ceil(mr)) * 2 + 1
    sh = int(round(SHIFT_BASE * scale)) if scale < 1 else SHIFT_BASE
    yy, xx = np.mgrid[-(w // 2):w // 2 + 1, -(w // 2):w // 2 + 1]
    return w, sh, np.hypot(xx, yy) <= mr


def _template(glyph: np.ndarray, canvas: float, rot: int, shrunk: np.ndarray | None = None
              ) -> np.ndarray:
    """The glyph shrunk to its canvas (`INTER_AREA`; `shrunk` when the
    caller holds it already), then turned (`INTER_LINEAR`)."""
    n = int(round(canvas))
    t = cv2.resize(glyph, (n, n), interpolation=cv2.INTER_AREA) if shrunk is None else shrunk
    if rot:
        m = cv2.getRotationMatrix2D(((n - 1) / 2, (n - 1) / 2), rot, 1.0)
        t = cv2.warpAffine(t, m, (n, n), flags=cv2.INTER_LINEAR, borderValue=0)
    return t


def _place_in_window(t: np.ndarray, w: int) -> np.ndarray:
    n = t.shape[0]
    if n > w:
        o = (n - w) // 2
        return t[o:o + w, o:o + w].astype(np.float32)
    out = np.zeros((w, w), np.float32)
    o = (w - n) // 2
    out[o:o + n, o:o + n] = t
    return out


def zrows(a: np.ndarray) -> np.ndarray:
    a = a - a.mean(-1, keepdims=True)
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def _backend():
    """(cupy or None, name): `RETICLE_GLYPH` = auto (default), gpu or cpu."""
    want = os.environ.get("RETICLE_GLYPH", "auto").strip().lower()
    if want == "cpu":
        return None, "cpu:numpy (RETICLE_GLYPH=cpu)"
    try:
        import cupy
        if cupy.cuda.runtime.getDeviceCount() > 0:
            return cupy, "gpu:cupy"
        why = "no CUDA device"
    except Exception as exc:  # noqa: BLE001 - any import or driver failure falls back
        why = f"{type(exc).__name__}"
    if want == "gpu":
        raise RuntimeError(f"RETICLE_GLYPH=gpu: {why}")
    return None, f"cpu:numpy ({why})"


class Templates:
    """Every (key, source, canvas, rotation) template of a key list at one
    scale, z-scored over the disc mask, grouped by key in `keys` order."""

    def __init__(self, data: GlyphData, keys: list[str], scale: float, rotate: str, xp=None):
        w, sh, mask = window_geometry(scale)
        self.w, self.sh, self.mask = w, sh, mask
        rows, meta, owner = [], [], []
        canv = CANVAS_BASE * scale
        keep = []
        for ki, k in enumerate(keys):
            rots = ROTATIONS if (rotate == "all" or (rotate == "policy" and k in data.rotating)) \
                else (0,)
            n0 = len(rows)
            for si, (_, g) in enumerate(data.sources[k]):
                for c in canv:
                    cf = float(round(c))
                    n = int(round(cf))
                    small = cv2.resize(g, (n, n), interpolation=cv2.INTER_AREA)
                    for rot in rots:
                        t = _place_in_window(_template(g, cf, rot, small), w)[mask]
                        if t.std() < FLAT_STD:
                            continue
                        rows.append(t)
                        meta.append((si, cf, rot))
                        owner.append(len(keep))
            if len(rows) > n0:
                keep.append(k)
        #: Keys with at least one template; a key with none is not scored.
        self.keys = keep
        self.dropped = [k for k in keys if k not in keep]
        self.meta = meta
        self.owner = np.asarray(owner, np.int64)
        self.starts = np.searchsorted(self.owner, np.arange(len(keep)))
        tz = zrows(np.asarray(rows, np.float32)) if rows else np.zeros((0, int(mask.sum())), np.float32)
        self.tz = tz if xp is None else xp.asarray(tz)
        self.xp = xp
        self.rotate = rotate

    def __len__(self) -> int:
        return len(self.meta)


def disc_windows(y: np.ndarray, centres: np.ndarray, w: int, sh: int) -> tuple[np.ndarray, np.ndarray]:
    """(windows, ok): the (2 sh + W) square luma window around each integer
    centre, gathered in one indexing step; `ok` False where it leaves the crop."""
    h = w // 2
    side = w + 2 * sh
    c = np.asarray(centres, float).reshape(-1, 2)
    ix, iy = np.rint(c[:, 0]).astype(np.int64), np.rint(c[:, 1]).astype(np.int64)
    x0, y0 = ix - h - sh, iy - h - sh
    ok = (x0 >= 0) & (y0 >= 0) & (x0 + side <= y.shape[1]) & (y0 + side <= y.shape[0])
    ar = np.arange(side)
    x0c, y0c = np.where(ok, x0, 0), np.where(ok, y0, 0)
    idx = (y0c[:, None, None] + ar[None, :, None]) * y.shape[1] + (x0c[:, None, None] + ar[None, None, :])
    return y.ravel()[idx].astype(np.float32), ok


def score_windows(wins: np.ndarray, tm: Templates) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per window and key: (best score, its template index, its shift index),
    each (n, len(tm.keys)): the max over every template of the key and every
    shift, one matrix product for all windows."""
    n, k = len(wins), len(tm.keys)
    if n == 0 or k == 0:
        return (np.zeros((n, k), np.float32), np.zeros((n, k), np.int64), np.zeros((n, k), np.int64))
    w = tm.w
    p = np.lib.stride_tricks.sliding_window_view(wins, (w, w), axis=(1, 2))
    p = p.reshape(n, -1, w, w)[..., tm.mask]                       # n x shifts x px, dy-major
    pz = zrows(p.astype(np.float32))
    ns = pz.shape[1]
    if tm.xp is None:
        s = (pz.reshape(n * ns, -1) @ tm.tz.T).reshape(n, ns, -1)
        m, a = s.max(1), s.argmax(1)
    else:
        xp = tm.xp
        s = (xp.asarray(pz.reshape(n * ns, -1)) @ tm.tz.T).reshape(n, ns, -1)
        m, a = s.max(1).get(), s.argmax(1).get()
    best = np.maximum.reduceat(m, tm.starts, axis=1)
    hit = m == best[:, tm.owner]
    idx = np.where(hit, np.arange(m.shape[1])[None, :], m.shape[1])
    targ = np.minimum.reduceat(idx, tm.starts, axis=1)
    sarg = np.take_along_axis(a, targ, 1)
    return best, targ, sarg


# ------------------------------------------------------------------ the proposer's rows for a frame


class LiveIcons:
    """The proposer's rows from the `AbilityIconReader` of the same pass,
    fed before this reader on each sample."""

    def __init__(self, reader):
        self.reader = reader
        self.version = ABILITY_ICON_VERSION
        self.source = "live"

    def at(self, smp) -> dict | None:
        rows = self.reader.rows
        r = rows[-1] if rows else None
        return r if r is not None and float(r["t_ms"]) == float(smp.t_ms) else None


class StoredIcons:
    """The stored `ability_icon` rows, where the proposer is current and
    does not rerun in this pass."""

    def __init__(self, rows: list[dict]):
        head = next((r for r in rows if r.get("kind") == "coverage"), {})
        self.version = head.get("ability_icon_version")
        self.by_t = {float(r["t_ms"]): r for r in rows if r.get("kind") == "frame"}
        self.source = "stored"

    def at(self, smp) -> dict | None:
        return self.by_t.get(float(smp.t_ms))


#: Stage 1's portrait cover (`prototypes/minimap_glyph_eval.py` follow,
#: minimap-glyph-follow-0.2.0), px x the matcher's scale. A portrait centre
#: within OCC_R touches the r = 8.5 scoring disc (a portrait's r is about
#: 8.5); an ally detection within SAME_R is the followed icon itself, which
#: the ally reader fits as a moving disc, so it does not cover it.
OCC_R = 17.0
SAME_R = 2.5


def portrait_covers(xy, roles, ixy, scale: float) -> list:
    """Per disc at `xy` (n x 2): why a stored portrait covers it, or None.
    `roles` and `ixy` (m x 2) are one frame's stored portraits, in
    their stored order. The self icon always covers within OCC_R; an ally
    covers in the ring SAME_R..OCC_R; two allies within SAME_R are a stack
    (one of them is the icon itself). The first covering icon in stored
    order names the reason, as stage 1's loop does."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    ixy = np.asarray(ixy, float).reshape(-1, 2)
    n = len(xy)
    if n == 0 or len(ixy) == 0:
        return [None] * n
    is_self = np.asarray([r == "self" for r in roles], bool)
    d = np.hypot(xy[:, None, 0] - ixy[None, :, 0], xy[:, None, 1] - ixy[None, :, 1])
    near = d <= OCC_R * scale
    cover = near & (is_self[None, :] | (d > SAME_R * scale))
    first = cover.argmax(1)
    same = (near & ~is_self[None, :] & (d <= SAME_R * scale)).sum(1)
    out = np.where(cover.any(1), np.where(is_self[first], "self_portrait", "ally_portrait"),
                   np.where(same > 1, "ally_stack", None))
    return [None if v is None else str(v) for v in out.tolist()]


def portrait_cover(p, icons, scale) -> str | None:
    """Why a stored portrait covers the icon at p, or None: `icons` is
    [(role, x, y)], one frame's stored portraits (stage 1's call, on `team_vision`)."""
    icons = list(icons)
    return portrait_covers([p], [i[0] for i in icons], [(i[1], i[2]) for i in icons], scale)[0]


class StoredPortraits:
    """Each frame's stored portraits as roles and positions, the input
    stage 1's `portrait_cover` reads: the `ally_icon` stream's teammate fits
    (role `ally`; a `barrier` row is furniture and is left out, as
    `team_vision.StoredAllyPoses` leaves it) and the frame row's self icon
    (role `self`), allies first, as `team_vision` lists them. Stage 1 read
    `team_vision`; the reader reads its source, `ally_icon` (`ally-candidates`),
    because the stored `team_vision` predates the variant widget's placement
    on 4f207c0c4e39 (its self icon sits about 15 px from the self portrait the
    0.2.0 rows found there) and lacks the self icon on frames `ally_icon`
    holds. Positions and roles only, never a verdict on who is drawn."""

    def __init__(self, frame_idx, roles, x, y, frames, version):
        f = np.asarray(frame_idx, np.int64).reshape(-1)
        o = np.argsort(f, kind="stable")
        self._f = f[o]
        self._role = np.asarray(roles, object).reshape(-1)[o]
        self._xy = np.stack([np.asarray(x, float).reshape(-1), np.asarray(y, float).reshape(-1)], 1)[o]
        #: The frames the stream holds a row for (a frame with no icons is read).
        self.frames = np.unique(np.asarray(frames, np.int64))
        self.version = version

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "StoredPortraits":
        """From stored `ally_icon` `coverage`, `frame` and `icon` rows, as a test writes them."""
        head = next((r for r in rows if r.get("kind") == "coverage"), {})
        f, role, x, y, frames, selfs = [], [], [], [], [], []
        for r in rows:
            if r.get("kind") == "frame":
                frames.append(r["frame_idx"])
                if r.get("self") and len(r["self"]) >= 2:
                    selfs.append((r["frame_idx"], r["self"][0], r["self"][1]))
            elif r.get("kind") == "icon" and r.get("cx") is not None and r.get("family") != "barrier":
                f.append(r["frame_idx"])
                role.append("ally")
                x.append(r["cx"])
                y.append(r["cy"])
        for fi, sx, sy in selfs:
            f.append(fi)
            role.append("self")
            x.append(sx)
            y.append(sy)
        return cls(f, role, x, y, frames, head.get("ally_icon_version"))

    @classmethod
    def from_store(cls, store, session_id: str):
        """(StoredPortraits, None), or (None, reason) with no stream. Parses
        only the columns it reads (`pyarrow.json`, one thread)."""
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.json as pj
        path = store.events_path("ally_icon", session_id)
        if not path.is_file():
            return None, "no ally_icon stream"
        with open(path, "rb") as fh:
            head = json.loads(fh.readline() or b"{}")
        if head.get("kind") != "coverage":
            return None, "ally_icon stream has no coverage row"
        schema = pa.schema([("kind", pa.string()), ("frame_idx", pa.int64()), ("cx", pa.float64()),
                            ("cy", pa.float64()), ("family", pa.string()),
                            ("self", pa.list_(pa.float64()))])
        t = pj.read_json(path, read_options=pj.ReadOptions(use_threads=False, block_size=1 << 24),
                         parse_options=pj.ParseOptions(explicit_schema=schema,
                                                       unexpected_field_behavior="ignore"))
        kind = t.column("kind")
        fam = t.column("family").fill_null("icon")
        ic = t.filter(pc.and_(pc.and_(pc.equal(kind, "icon"), pc.is_valid(t.column("cx"))),
                              pc.not_equal(fam, "barrier")))
        fr = t.filter(pc.equal(kind, "frame"))
        frames = np.asarray(fr.column("frame_idx").to_numpy(), np.int64)
        fs = fr.filter(pc.is_valid(fr.column("self")))
        selfs = fs.column("self").combine_chunks()
        offs = np.asarray(selfs.offsets.to_numpy(), np.int64)
        vals = np.asarray(selfs.values.to_numpy(zero_copy_only=False), float)
        keep = np.diff(offs) >= 2
        at = offs[:-1][keep]
        n_ic = ic.num_rows
        f = np.concatenate([np.asarray(ic.column("frame_idx").to_numpy(), np.int64),
                            np.asarray(fs.column("frame_idx").to_numpy(), np.int64)[keep]])
        x = np.concatenate([ic.column("cx").to_numpy(), vals[at] if len(vals) else np.zeros(0)])
        y = np.concatenate([ic.column("cy").to_numpy(), vals[at + 1] if len(vals) else np.zeros(0)])
        roles = np.concatenate([np.full(n_ic, "ally", object), np.full(int(keep.sum()), "self", object)])
        return cls(f, roles, x, y, frames, head.get("ally_icon_version")), None

    def at(self, frame_idx: int):
        """(roles, xy) of this frame's stored icons, or None where the stream
        holds no row for the frame."""
        k = int(frame_idx)
        j = np.searchsorted(self.frames, k)
        if j >= len(self.frames) or self.frames[j] != k:
            return None
        lo, hi = np.searchsorted(self._f, [k, k + 1])
        return self._role[lo:hi].tolist(), self._xy[lo:hi]


# ------------------------------------------------------------------ the reader


class _Window:
    __slots__ = ("id", "birth_t", "last", "audit", "cleared", "open", "pending")

    def __init__(self, wid, t, disc, audit):
        self.id, self.birth_t, self.last = wid, t, disc
        self.audit, self.cleared, self.open = audit, False, True
        self.pending: list = []


def _static_luma(img: np.ndarray | None) -> np.ndarray | None:
    """The baked static's luma (YCrCb Y), as the matcher reads the crop's."""
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)


class AbilityGlyphReader:
    """`passes.Reader` writing the `ability_glyph` stream (module docstring)."""

    cache_resample = True
    records_clip = True

    def __init__(self, data: GlyphData, box, session_id: str, candidates: dict | None,
                 candidates_from: str | None, icons, hz: float = 2.0, spans=None, ms=None,
                 name: str = "ability_glyph", audit_every: int = AUDIT_EVERY,
                 static=None, static_reason: str | None = "no baked static given",
                 portraits=None, portraits_reason: str | None = "no ally_icon rows given"):
        self.name, self.hz, self.spans = name, hz, spans
        self.frames_from = "video"
        self.cv_threads = 1
        self.data, self.box, self.sid = data, box, session_id
        self.icons = icons
        self.ms = ms
        self.audit_every = int(audit_every)
        self.candidates, self.candidates_from = candidates, candidates_from
        agents = [a for side in (candidates or {}).values() for a in side["agents"]]
        self.context_keys = data.keys_of(agents)
        self.agents_without_keys = sorted({a for a in agents if not data.keys_of([a])})
        #: The gates' inputs: the baked static's luma (crop-sized) and the
        #: stored portraits; None with a reason where absent.
        self.static_y = _static_luma(static)
        self.static_reason = None if static is not None else static_reason
        self.portraits = portraits
        self.portraits_reason = None if portraits is not None else portraits_reason
        self.static_mismatch = 0
        #: Read frames whose discs the portrait gate could not judge (no stored row).
        self.no_vision_row = 0
        self.xp, self.scorer = _backend()
        self._tm: dict = {}
        #: The last read sample: its time, and each candidate's window and disc id.
        self._prev: dict | None = None
        self._open: list[_Window] = []
        self.births = 0
        self.n_windows = {"audit": 0, "surprise": 0}
        self.continued = {"verified": 0, "lost": 0}
        self.rows: list[dict] = []

    # The template sets, built once per scale.
    def templates(self, which: str, scale: float) -> Templates:
        k = (which, round(scale, 4))
        if k not in self._tm:
            keys, rotate = {"context": (self.context_keys, "policy"),
                            "audit": (self.data.keys, "all"),
                            "surprise": (self.data.keys, "policy")}[which]
            with usage_step(f"templates:{which}"):
                self._tm[k] = Templates(self.data, keys, scale, rotate, self.xp)
        return self._tm[k]

    def _disc_id(self, t: float, i: int) -> str:
        return f"ability_icon:{self.sid}:{round(float(t), 3)}:{i}"

    def _row(self, base: dict, which: str, tm: Templates, best, targ, sarg) -> dict:
        n2 = 2 * tm.sh + 1
        meta = tm.meta
        sarg = np.asarray(sarg)
        scores = {k: [s, *meta[t], dx, dy] for k, s, t, dx, dy in zip(
            tm.keys, [round(v, 4) for v in np.asarray(best).tolist()], np.asarray(targ).tolist(),
            (sarg % n2 - tm.sh).tolist(), (sarg // n2 - tm.sh).tolist())}
        o = np.argsort(-best, kind="stable")
        b = tm.keys[int(o[0])]
        sec = tm.keys[int(o[1])] if len(o) > 1 else None
        margin = float(best[o[0]] - (best[o[1]] if len(o) > 1 else -1.0))
        out = {**base, "set": which, "scores": scores, "best": b, "second": sec,
               "margin": round(margin, 4)}
        if which == "audit":
            # The null table holds no cut for a search at every key rotated.
            out.update(best_cut=None, above_cut=None, cut_reason="no_null_at_full_rotation")
        else:
            cut = self.data.cuts.get(b)
            out.update(best_cut=cut, above_cut=None if cut is None else bool(float(best[o[0]]) > cut),
                       cut_reason=None if cut is not None else "no_cut_for_key")
        return out

    def _close(self, win: _Window, why: str) -> None:
        """End a window's schedule: rescore it against every kit when its
        best context key never cleared its null cut."""
        if not win.open:
            return
        win.open = False
        pend, win.pending = win.pending, []
        if win.cleared or not pend:
            return
        scale = pend[0][1]
        tm = self.templates("surprise", scale)
        with usage_step("surprise"):
            best, targ, sarg = score_windows(np.stack([p[2] for p in pend]), tm)
        self.n_windows["surprise"] += 1
        for j, (base, _, _) in enumerate(pend):
            self.rows.append(self._row({**base, "surprise_reason": f"below_null_through_window:{why}"},
                                       "surprise", tm, best[j], targ[j], sarg[j]))

    def _end_all(self, why: str) -> None:
        for w in self._open:
            self._close(w, why)
        self._open = []
        self._prev = None

    def _gates(self, y, xy, wins, ok, tm, frame_idx, scale):
        """Per disc: (static_corr, portrait cover reason or None, gate reason
        or None), vectorised over the frame's discs; `portrait` is
        "no_vision_row" where the stored stream has no row for the frame."""
        n = len(xy)
        corr = np.full(n, np.nan)
        if self.static_y is not None and n:
            if self.static_y.shape != y.shape:
                self.static_mismatch += 1
            else:
                sw, sok = disc_windows(self.static_y, xy, tm.w, 0)
                both = ok & sok
                if both.any():
                    a = wins[both][:, tm.sh:tm.sh + tm.w, tm.sh:tm.sh + tm.w][:, tm.mask]
                    b = sw[both][:, tm.mask]
                    c = (zrows(a) * zrows(b)).sum(1)
                    c[b.std(1) < FLAT_STD] = np.nan
                    corr[both] = c
        cover: list = [None] * n
        unread = False
        if self.portraits is not None and n:
            got = self.portraits.at(frame_idx)
            if got is None:
                unread = True
                self.no_vision_row += 1
            else:
                cover = portrait_covers(xy, got[0], got[1], scale)
        why = np.asarray(cover, object)
        why[np.nan_to_num(corr, nan=-2.0) >= MAP_CORR] = "static_like"
        why[~ok] = "off_crop"
        return corr, ("no_vision_row" if unread else cover), why.tolist()

    def feed(self, smp) -> None:
        t = float(smp.t_ms)
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": t}
        ir = self.icons.at(smp)
        reason = None
        if self.candidates is None:
            reason = "no_lineup"
        elif not self.context_keys:
            reason = "no_context_keys"
        elif ir is None:
            reason = "no_ability_icon_row"
        elif ir.get("reason"):
            reason = ir["reason"]
        if reason is not None:
            self.rows.append({**row, "reason": reason, "discs": None, "births": None, "rests_on": []})
            self._end_all(reason)
            return
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        scale = widget_scale(crop.shape[1])
        cands = ir.get("candidates") or []
        with usage_step("luma"):
            y = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)
        tm = self.templates("context", scale)
        xy = np.array([[c["cx"], c["cy"]] for c in cands], float).reshape(-1, 2)
        wins, ok = disc_windows(y, xy, tm.w, tm.sh)
        with usage_step("gates"):
            corr, cover, gate = self._gates(y, xy, wins, ok, tm, smp.frame_idx, scale)
        # The proposer's verify decides continuation (`ability-icon`).
        prev = self._prev
        ver = ir.get("verify")
        cont: dict = {}
        if prev is not None and ver is not None and float(ver.get("of_t_ms", -1.0)) == prev["t"]:
            cont = verified_continuations(ver, cands)
        # Windows whose schedule ran out close before this frame's discs join them.
        for w in self._open:
            if t - w.birth_t > WINDOW_MS:
                self._close(w, "window_end")
        births = 0
        bases = []
        now_win: dict = {}
        lineup = [self.candidates_from] if self.candidates_from else []
        for i, c in enumerate(cands):
            pi = cont.get(i) if prev is not None else None
            rests = [] if pi is None else [prev["disc"][pi]]
            base = {"kind": "disc", "t_ms": t, "frame_idx": int(smp.frame_idx),
                    "disc": self._disc_id(t, i), "i": i, "cx": c["cx"], "cy": c["cy"], "r": c["r"],
                    "scale": round(scale, 5),
                    "static_corr": None if np.isnan(corr[i]) else round(float(corr[i]), 4),
                    "portrait": cover if isinstance(cover, str) else cover[i]}
            if gate[i] is not None:
                self.rows.append({**base, "set": "context", "reason": gate[i], "window": None,
                                  "birth": False, "rests_on": rests, "scores": None})
                continue
            win = None if pi is None else prev["win"].get(pi)
            if win is None:
                self.births += 1
                births += 1
                audit = (self.births - 1) % self.audit_every == 0
                win = _Window(f"{self.sid}:aglyph:{round(t, 3)}:{i}", t, base["disc"], audit)
                if audit:
                    self.n_windows["audit"] += 1
                self._open.append(win)
            else:
                self.continued["verified"] += 1
                win.last = base["disc"]
            now_win[i] = win
            base.update(window=win.id, birth=win.birth_t == t, rests_on=rests)
            bases.append((i, base, win))
        alive = {id(w) for w in now_win.values()}
        for w in self._open:
            if id(w) not in alive:
                self.continued["lost"] += 1
                self._close(w, "lost")
        self._open = [w for w in self._open if id(w) in alive]
        idx = np.array([i for i, _, _ in bases], np.int64)
        with usage_step("context"):
            best, targ, sarg = score_windows(wins[idx], tm)
        audit_i = []
        with usage_step("rows"):
            for j, (i, base, win) in enumerate(bases):
                r = self._row({**base, "reason": None, "rests_on": base["rests_on"] + lineup},
                              "context", tm, best[j], targ[j], sarg[j])
                self.rows.append(r)
                if win.open:
                    if r["above_cut"]:
                        win.cleared, win.pending = True, []
                    elif not win.cleared:
                        win.pending.append(({**base, "reason": None}, scale, wins[i]))
                    if win.audit:
                        audit_i.append((i, base))
        if audit_i:
            ta = self.templates("audit", scale)
            with usage_step("audit"):
                ba, ta_arg, sa_arg = score_windows(wins[[i for i, _ in audit_i]], ta)
            for j, (_, base) in enumerate(audit_i):
                self.rows.append(self._row({**base, "reason": None}, "audit", ta,
                                           ba[j], ta_arg[j], sa_arg[j]))
        self._prev = {"t": t, "win": now_win,
                      "disc": {i: self._disc_id(t, i) for i in range(len(cands))}}
        gated: dict = {}
        for g in gate:
            if g is not None:
                gated[g] = gated.get(g, 0) + 1
        self.rows.append({**row, "reason": None, "discs": len(cands), "births": births,
                          "scored": len(bases), "gated": gated, "rests_on": lineup})

    def finish(self) -> None:
        """Close the open windows (idempotent)."""
        self._end_all("pass_end")

    def events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        self.finish()
        common = {"session_id": session_id, "source": "minimap", "geometry_key": geometry_key,
                  "ability_glyph_version": ABILITY_GLYPH_VERSION}
        by: dict = {}
        sets: dict = {}
        for r in self.rows:
            if r["kind"] == "frame":
                k = r["reason"] or "read"
                by[k] = by.get(k, 0) + 1
            else:
                k = r["set"] if r.get("reason") is None else f"{r['set']}:{r['reason']}"
                sets[k] = sets.get(k, 0) + 1
        scales = sorted({r["scale"] for r in self.rows if r["kind"] == "disc"})
        head = {**common, "kind": "coverage", "hz": self.hz,
                "frames": sum(r["kind"] == "frame" for r in self.rows),
                "frames_from": self.frames_from, "by_reason": by, "disc_rows": sets,
                "births": self.births, "windows": dict(self.n_windows),
                "continued": dict(self.continued),
                "ability_icon_version": getattr(self.icons, "version", None),
                "ability_icon_source": getattr(self.icons, "source", None),
                "glyph_bank": GLYPH_BANK_STAMP, "glyph_data": self.data.provenance,
                "matcher": {"score": "masked Pearson of luma (YCrCb Y), never binarised",
                            "canvas_base": [float(c) for c in CANVAS_BASE], "mask_r_base": MASK_R_BASE,
                            "shift_base": SHIFT_BASE, "rotations": list(ROTATIONS),
                            "flat_std": FLAT_STD,
                            "resample": "INTER_AREA to shrink each 128 px glyph to its canvas; "
                                        "INTER_LINEAR to turn it",
                            "scale": "minimap.widget_scale(crop width): the null table's basis, a "
                                     "measured exception to the full transform (map_scale), "
                                     "falsified by glyph_reader/scale",
                            "scales": scales, "scorer": self.scorer},
                "gates": {"static": {"rule": "masked Pearson of the crop's luma with the baked static's "
                                             "(geometry by (map, profile)) inside the matcher's disc; "
                                             "static_like at or above map_corr",
                                     "map_corr": MAP_CORR,
                                     "from": "prototypes/minimap_glyph_eval.py MAP_CORR (stage 1's follow)",
                                     "unknown": self.static_reason,
                                     "size_mismatch_frames": self.static_mismatch},
                          "portrait": {"rule": "stage 1's portrait_cover over the frame's stored "
                                               "ally_icon fits (allies, no barriers) and self icon: the "
                                               "self icon within occ_r, an ally "
                                               "in the ring same_r..occ_r, or two allies within same_r "
                                               "(px x the matcher's scale)",
                                       "occ_r": OCC_R, "same_r": SAME_R,
                                       "from": "prototypes/minimap_glyph_eval.py follow "
                                               "(minimap-glyph-follow-0.2.0), which calls this function",
                                       "ally_icon_version": getattr(self.portraits, "version", None),
                                       "unknown": self.portraits_reason,
                                       "no_vision_row_frames": self.no_vision_row}},
                "candidates": self.candidates, "candidates_from": self.candidates_from,
                "context": {"keys": self.context_keys, "rotate": "policy",
                            "why": "the match lineup's kits, both sides (lineup.glyph_candidates: named "
                                   "slots, refused slots' best guesses as rivals): continue the prior",
                            "rests_on": self.candidates_from,
                            "per_view_gate": "not built: both sides' full kits",
                            "agents_without_keys": self.agents_without_keys},
                "audit": {"every": self.audit_every, "keys": "every bank key", "rotate": "all",
                          "rule": "the first birth and every audit_every-th after it, through its window; "
                                  "a cadence fixed in advance",
                          "cut": "none: no null at full rotation (best_cut and above_cut null)"},
                "surprise": {"keys": "every bank key", "rotate": "policy",
                             "rule": "a window whose best context key never exceeds that key's per-key "
                                     "null cut is rescored when it closes; never an audit sample"},
                "window": {"ms": WINDOW_MS,
                           "rule": "continuation by the proposer's verify (ability_icons."
                                   "verified_continuations); a birth is an ungated disc that continues "
                                   "no windowed disc; after window ms the schedule ends and the window "
                                   "still absorbs its disc; the verify's loss, a gated disc or an unread "
                                   "frame ends it; a schedule, not a track"},
                "textures": {k: [{"provenance": p, "file": f, "sha256": h} for (p, _), (f, h) in
                                 zip(self.data.sources[k], self.data.files.get(k) or
                                     [(None, None)] * len(self.data.sources[k]))]
                             for k in self.data.keys},
                "map_scale": None if self.ms is None else self.ms.provenance()}
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            head["spans_clip"] = clip
        order = {s: i for i, s in enumerate(SETS)}
        body = sorted(self.rows, key=lambda r: (r["t_ms"], r["kind"] != "frame",
                                                order.get(r.get("set"), 0), r.get("i", -1)))
        return [head] + [{**common, **r} for r in body]


def check_pass(icons_live: bool, pipeline: str, workers) -> None:
    """Refuse a staged pass that feeds the glyph reader beside the icon
    reader whose row it reads for the same sample (`LiveIcons`): with
    `workers` other than 0 each reader runs on its own thread."""
    if icons_live and pipeline == "staged" and workers != 0:
        raise SystemExit("the glyph reader reads the icon reader's row for the same sample; a "
                         "staged pass feeds them on separate threads. Run the ability pass with "
                         "--pipeline serial or --workers 0")


def glyph_reader(ctx, spans, icons, candidates, candidates_from, hz: float = 2.0,
                 data: GlyphData | None = None) -> AbilityGlyphReader:
    """The `AbilityGlyphReader` `scan` and `trial` build for a session, over
    the profile's minimap ROI, with the candidate set the caller took from
    the lineup's owner (`lineup.glyph_candidates`), the baked static of the
    session's geometry key and the stored `ally_icon` portraits (the gates)."""
    from . import geometry
    from .minimap import minimap_roi_px
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    try:
        static, static_why = ctx.map_reference(), None
    except (SystemExit, FileNotFoundError, KeyError, ValueError) as exc:
        static, static_why = None, f"no baked static: {exc}"
    portraits, portraits_why = StoredPortraits.from_store(ctx.store, ctx.session_id)
    return AbilityGlyphReader(data or GlyphData.load(ctx.store.root), box, ctx.session_id,
                              candidates, candidates_from, icons, hz=hz, spans=spans,
                              ms=geometry.map_scale_of(ctx.session_id, ctx.store.root),
                              static=static, static_reason=static_why,
                              portraits=portraits, portraits_reason=portraits_why)
