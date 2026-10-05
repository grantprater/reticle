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
- the rotation policy (`glyph-rotation-policy-0.1.2`): per key, upright (0
  deg) or every 15 deg, each row citing what decided it.
- the null table (`glyph-null-table-0.2.2`, `basis` map_scale): per key, the
  cut that at most 5% of the dev no-ability discs exceed at the key's policy
  search size (`cut`) and at every rotation (`audit_cut`, the audit's search
  size), and the bank cuts of the full set (every key, policy rotations) and
  of the audit (every key, every rotation), all measured at the full
  transform.

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

The scale: one transform. Every px x scale length (mask, shift, canvas, the
portrait radii) reads `geometry.MapScale.scale`, widget x map zoom
[domain:minimap/icons-follow-map-zoom], the basis the null table was
measured on (`glyph-null-table-0.2.0`); `GlyphData.load` refuses a table on
another basis. Up to 0.3.0 the matcher read the widget scale alone, a
measured exception whose falsifier fired (stage 2's F4: at zoom 0.892 the
best key changed on 19.5% of 200 rows); the table's remeasure ended it. A
frame with no MapScale is unread (`no_map_scale`), and so is a crop whose
width is not the key's widget (`geometry_size_mismatch`).

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

The map-shown gate (`map_shown`, MAP_SHOWN). A drawn ability icon is an
opaque dark disc: it hides the map art under it. Static structure the
proposer reads as a disc shows that art. Over the disc's body (the matcher
disc united with the proposer's disc of radius r, so an icon's dark rim
enters) on the baked footprint (`geometry.footprint`, by (map, profile)),
the crop's 10th-percentile luma over the baked static's is the disc's
`map_shown`; at or above MAP_SHOWN the disc is the map's (reason
`map_shown`), neither scored nor scheduled. It answers the void-corner disc
at (21, 91) on 4f207c0c4e39, where the void behind the variant widget reads
as a dark disc beside a building corner and the radar ring: its void half
shows the world, which no baked value predicts, so its static correlation
stays under MAP_CORR, but its footprint half shows the building as baked.
A real glyph drawn half over the void hides the footprint part it covers,
and a disc with under MAP_SHOWN_MIN_FP of its body on the footprint is not
judged. The rule family (judge the footprint part, never gate on footprint
share) and MAP_SHOWN_MIN_FP were chosen knowing the corner's footprint
share (about 0.2) and the 0.3.0 docstring's held-out count (9 of 226
held-out marks under half on the footprint); only the cut and the
percentile are dev-only (MAP_SHOWN's comment). At 0.4.0 the score read
the matcher disc alone, which excludes the dark rim, and refused four
opaque icons on 4f207c0c4e39 whose footprint part fell on the white glyph;
0.5.0 reads the body. A translucent icon (a grey disc the map shows
through) still breaks the premise. Its effect on the corner and on the
held-out marks is in `docs/MINIMAP_GLYPH_CHANNEL.md` (stage 3
prerequisites).

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
  and the rotation policy hide. Its rows read the null measured at that
  search size: `best_cut` is the key's `audit_cut`, `bank_cut` the audit
  bank's cut (null with `no_null_at_full_rotation` where the table holds
  none).
- the surprise: a window whose best context key never clears that key's
  null cut is rescored against every kit, policy rotations, when it
  closes; its rows carry the full bank's cut as `bank_cut`. Never an audit
  sample.

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
#: A version stamps a table's rows; the file's bytes and provenance are pinned
#: by the bank's sha256 pairing, which `GlyphData.load` checks. The policy
#: file in 20261005c (generator glyph-tables-0.2.0) holds the rows of the
#: 20261005b file (glyph-tables-0.1.1) under the same stamp, with other bytes.
#: 20261005d (glyph-tables-0.2.1) reads the player's 2026-10-05 rotation
#: answers: Skye:X, Cypher:Q and Cypher:C rotate; only Cypher:Q's search and
#: cut change, and the glyphs equal 0.3.0's. 20261005e (glyph-tables-0.2.2)
#: stores every cut rounded up to 4 decimals, so the stored cut keeps the
#: count gate 3 states: 0.2.1's full bank cut, 0.8219, sat under its 0.821934
#: order statistic and named 4 of the 63 dev no-ability discs.
GLYPH_DATA = {"bank": ("analysis/glyph-bank-20261005e", "glyph-bank-0.3.2"),
              "policy": ("analysis/glyph-tables-20261005e", "glyph-rotation-policy-0.1.2"),
              "null": ("analysis/glyph-tables-20261005e", "glyph-null-table-0.2.2")}
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
#: The map-shown gate (module docstring): a drawn icon is an opaque dark disc
#: that hides the map art under it. Over the disc's body on the baked
#: footprint, the crop's MAP_SHOWN_Q-th percentile luma over the baked
#: static's; a disc at or above MAP_SHOWN shows the map and is the map's.
#: The cut and the percentile were chosen on dev only: MAP_SHOWN is the
#: midpoint of the dev glyph items' maximum and the static dev discs'
#: minimum, rounded (the frozen-rule rows `glyph-prereqs-20261005` and
#: `glyph-prereqs-fix-20261005`; the ranges, with metric tokens, in
#: `docs/MINIMAP_GLYPH_CHANNEL.md`, stage 3 prerequisites). Under
#: MAP_SHOWN_MIN_FP of the body on the footprint the gate does not judge (a
#: glyph over the void hides nothing the bake predicts); that value was set
#: under the 4f207c0c4e39 corner's footprint share, not on dev, where any
#: value up to the static discs' share fits.
MAP_SHOWN = 0.73
MAP_SHOWN_Q = 10
MAP_SHOWN_MIN_FP = 0.1
SETS = ("context", "audit", "surprise")


def _agent_key(agent: str | None) -> str:
    """An agent name compared across stores: `KAY_O` and `KAY/O` are one."""
    return "".join(ch for ch in (agent or "").lower() if ch.isalnum())


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class GlyphData:
    """The reference bank, the rotation policy and the null table, loaded and
    checked against each other."""

    def __init__(self, keys, sources, rotating, cuts, provenance, files=None, audit_cuts=None,
                 bank_cuts=None):
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
        #: key -> its null cut at every rotation (the audit's search size).
        self.audit_cuts: dict[str, float] = audit_cuts or {}
        #: bank -> its bank cut: "full" (every key, policy rotations: the
        #: surprise's search) and "audit" (every key, every rotation).
        self.bank_cuts: dict[str, float] = bank_cuts or {}

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
        audit_cuts = {k: float(v["audit_cut"]) for k, v in nul["keys"].items() if v.get("audit_cut") is not None}
        bank_cuts = {b: float(nul["banks"][b]["bank_cut"]["cut"]) for b in ("full", "audit")
                     if (nul.get("banks") or {}).get(b, {}).get("bank_cut", {}).get("cut") is not None}
        if nul.get("basis") != "map_scale":
            raise ValueError(f"{nul_p}: basis {nul.get('basis')!r}, expected 'map_scale' (widget x zoom)")
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
                     "rate": nul.get("rate"), "basis": nul.get("basis"),
                     "cut": "per key, overall (`keys.<key>.cut`); audit rows `keys.<key>.audit_cut`",
                     "bank_cuts": bank_cuts,
                     "tie_margin": (nul.get("tie_margin") or {}).get("value")}}
        return cls(keys, sources, rotating, cuts, provenance, files, audit_cuts, bank_cuts)

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


def map_shown(y: np.ndarray, static_y: np.ndarray, footprint: np.ndarray, xy, r, scale: float
              ) -> tuple[np.ndarray, np.ndarray]:
    """Per disc at `xy` (n x 2): (map_shown score, footprint share of its body).
    `y`, `static_y` and `footprint` are the crop's luma, the baked static's
    luma and the baked footprint, all crop-sized. A disc's body is the union
    of the matcher disc (MASK_R_BASE x scale) and the proposer's disc of
    radius `r` (crop px; NaN or None for none), about the matcher's integer
    centre, so an icon's dark rim, outside the matcher disc, enters. The
    score is the crop's MAP_SHOWN_Q-th percentile luma over the static's
    (floored at 1) on the body's footprint pixels, NaN where under
    MAP_SHOWN_MIN_FP of the body lies on the footprint; a pixel off the crop
    counts as off the footprint. An opaque icon reads far under 1; map art
    reads near 1."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    n = len(xy)
    if n == 0:
        return np.zeros(0), np.zeros(0)
    rr = np.full(n, np.nan) if r is None else np.asarray(r, float).reshape(-1)
    rad = np.fmax(MASK_R_BASE * scale, rr)
    h = int(np.ceil(rad.max()))
    w = 2 * h + 1
    pad = ((h, h), (h, h))
    yp = np.pad(np.asarray(y, np.float32), pad)
    sp = np.pad(np.asarray(static_y, np.float32), pad)
    fpp = np.pad((np.asarray(footprint) > 0).astype(np.float32), pad)
    c = xy + h
    cw, _ = disc_windows(yp, c, w, 0)
    sw, _ = disc_windows(sp, c, w, 0)
    fw, _ = disc_windows(fpp, c, w, 0)
    g = np.arange(w) - h
    body = np.hypot(g[None, :], g[:, None])[None] <= rad[:, None, None]
    on = body & (fw > 0)
    share = on.sum((1, 2)) / body.sum((1, 2))
    ok = share >= MAP_SHOWN_MIN_FP
    out = np.full(n, np.nan)
    if ok.any():
        a = np.where(on[ok], cw[ok], np.nan).reshape(int(ok.sum()), -1)
        b = np.where(on[ok], sw[ok], np.nan).reshape(int(ok.sum()), -1)
        qa = np.nanpercentile(a, MAP_SHOWN_Q, axis=1)
        qb = np.nanpercentile(b, MAP_SHOWN_Q, axis=1)
        out[ok] = qa / np.maximum(qb, 1.0)
    return out, share


def disc_gates(y: np.ndarray, xy, r, scale: float, static_y: np.ndarray | None = None,
               footprint: np.ndarray | None = None, portraits=None) -> dict:
    """The reader's per-disc gate decision, the one rule its callers ask
    (`AbilityGlyphReader` per frame; `prototypes/glyph_tables.py`
    `unlabelled_negatives`, for "a disc the reader's gates keep"). For the
    discs at `xy` (n x 2, crop px) with proposer radii `r` (or None) on the
    crop luma `y`, at MapScale.scale `scale`:

    - `ok`: the matcher's window (W plus the shift each side) lies on the crop;
    - `static_corr`: masked Pearson of the crop's luma with the baked static's
      inside the matcher disc, NaN where the static is flat or missing;
    - `map_shown`, `fp_share`: `map_shown` over the disc's body;
    - `cover`: `portrait_covers` over `portraits`, (roles, xy) of the frame's
      stored portraits, or None where no portrait input is given;
    - `why`: the gate reason or None, in this order: off_crop, static_like
      (static_corr at or above MAP_CORR), map_shown (at or above MAP_SHOWN),
      then the cover's reason;
    - `static_mismatch`, `footprint_mismatch`: the input was given at another
      size than the crop, so that gate is unknown."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    n = len(xy)
    w, sh, mask = window_geometry(scale)
    _, ok = disc_windows(y, xy, w, sh)
    corr = np.full(n, np.nan)
    shown = np.full(n, np.nan)
    share = np.full(n, np.nan)
    s_mis = static_y is not None and static_y.shape != y.shape
    f_mis = footprint is not None and footprint.shape[:2] != y.shape
    if static_y is not None and not s_mis and n:
        cw, cok = disc_windows(y, xy, w, 0)
        sw, sok = disc_windows(static_y, xy, w, 0)
        both = ok & cok & sok
        if both.any():
            a = cw[both][:, mask]
            b = sw[both][:, mask]
            c = (zrows(a) * zrows(b)).sum(1)
            c[b.std(1) < FLAT_STD] = np.nan
            corr[both] = c
            if footprint is not None and not f_mis:
                rb = None if r is None else np.asarray(r, float).reshape(-1)[both]
                shown[both], share[both] = map_shown(y, static_y, footprint, xy[both], rb, scale)
    cover: list = [None] * n
    if portraits is not None and n:
        cover = portrait_covers(xy, portraits[0], portraits[1], scale)
    why = np.asarray(cover, object)
    why[np.nan_to_num(shown, nan=-2.0) >= MAP_SHOWN] = "map_shown"
    why[np.nan_to_num(corr, nan=-2.0) >= MAP_CORR] = "static_like"
    why[~ok] = "off_crop"
    return {"ok": ok, "static_corr": corr, "map_shown": shown, "fp_share": share, "cover": cover,
            "why": why.tolist(), "static_mismatch": bool(s_mis), "footprint_mismatch": bool(f_mis)}


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
                 portraits=None, portraits_reason: str | None = "no ally_icon rows given",
                 footprint=None, footprint_reason: str | None = "no footprint given"):
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
        #: The baked footprint (map art), crop-sized, for the map-shown gate.
        self.footprint = None if footprint is None else (np.asarray(footprint) > 0).astype(np.float32)
        self.footprint_reason = None if footprint is not None else footprint_reason
        #: Read frames whose footprint was given at another size (the gate unknown).
        self.footprint_mismatch = 0
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
        top = float(best[o[0]])
        # Each set reads the cuts measured at its own search size: context and
        # surprise the per-key cut at the policy's rotations, audit the per-key
        # cut at every rotation. The bank cut fits only a search the table
        # measured as a bank: surprise (every key, policy) and audit (every key,
        # every rotation); the context set (both sides' kits) is no table bank.
        cut = (self.data.audit_cuts if which == "audit" else self.data.cuts).get(b)
        out.update(best_cut=cut, above_cut=None if cut is None else bool(top > cut),
                   cut_reason=None if cut is not None else
                   ("no_null_at_full_rotation" if which == "audit" else "no_cut_for_key"))
        bank = {"audit": "audit", "surprise": "full"}.get(which)
        bc = None if bank is None else self.data.bank_cuts.get(bank)
        out.update(bank_cut=bc, above_bank_cut=None if bc is None else bool(top > bc))
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

    def _gates(self, y, xy, r, frame_idx, scale):
        """Per disc: (static_corr, map_shown, portrait cover reason or None,
        gate reason or None), from the module's `disc_gates`; `portrait` is
        "no_vision_row" where the stored stream has no row for the frame. Counts
        the frames whose static or footprint was given at another size."""
        n = len(xy)
        got, unread = None, False
        if self.portraits is not None and n:
            got = self.portraits.at(frame_idx)
            if got is None:
                unread = True
                self.no_vision_row += 1
        g = disc_gates(y, xy, r, scale, static_y=self.static_y, footprint=self.footprint, portraits=got)
        if n and g["static_mismatch"]:
            self.static_mismatch += 1
        if n and g["footprint_mismatch"] and not g["static_mismatch"]:
            self.footprint_mismatch += 1
        return (g["static_corr"], g["map_shown"], ("no_vision_row" if unread else g["cover"]), g["why"])

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
        elif self.ms is None:
            reason = "no_map_scale"
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        if reason is None and abs(widget_scale(crop.shape[1]) - self.ms.widget_scale) > 1e-3:
            reason = "geometry_size_mismatch"
        if reason is not None:
            self.rows.append({**row, "reason": reason, "discs": None, "births": None, "rests_on": []})
            self._end_all(reason)
            return
        # One transform: base px x widget scale x map zoom (`geometry.MapScale`).
        scale = self.ms.scale
        cands = ir.get("candidates") or []
        with usage_step("luma"):
            y = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)
        tm = self.templates("context", scale)
        xy = np.array([[c["cx"], c["cy"]] for c in cands], float).reshape(-1, 2)
        wins, _ = disc_windows(y, xy, tm.w, tm.sh)
        rad = np.array([c.get("r", np.nan) for c in cands], float).reshape(-1)
        with usage_step("gates"):
            corr, shown, cover, gate = self._gates(y, xy, rad, smp.frame_idx, scale)
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
                    "map_shown": None if np.isnan(shown[i]) else round(float(shown[i]), 4),
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
                            "scale": "geometry.MapScale.scale (widget x map zoom), the null table's "
                                     "basis (glyph-null-table-0.2.0 `basis` map_scale)",
                            "scales": scales, "scorer": self.scorer},
                "gates": {"static": {"rule": "masked Pearson of the crop's luma with the baked static's "
                                             "(geometry by (map, profile)) inside the matcher's disc; "
                                             "static_like at or above map_corr",
                                     "map_corr": MAP_CORR,
                                     "from": "prototypes/minimap_glyph_eval.py MAP_CORR (stage 1's follow)",
                                     "unknown": self.static_reason,
                                     "size_mismatch_frames": self.static_mismatch},
                          "map_shown": {"rule": "the crop's q-th percentile luma over the baked static's "
                                                "(floored at 1) on the footprint pixels of the disc's body "
                                                "(the matcher disc united with the proposer's disc of radius "
                                                "r); map_shown at or above the cut; not judged under min_fp "
                                                "of the body on the footprint",
                                        "cut": MAP_SHOWN, "q": MAP_SHOWN_Q, "min_fp": MAP_SHOWN_MIN_FP,
                                        "from": "glyph-prereqs-fix-20261005 (cut on dev only; min_fp informed "
                                                "by the 4f207c0c4e39 corner: amendment row in the store's "
                                                "notes/predictions.jsonl)",
                                        "footprint": "geometry.footprint by (map, profile)",
                                        "unknown": self.footprint_reason or self.static_reason,
                                        "size_mismatch_frames": self.footprint_mismatch},
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
                          "cut": "per key at every rotation (best_cut, the table's audit_cut) and the "
                                 "audit bank cut (bank_cut: every key, every rotation)"},
                "surprise": {"keys": "every bank key", "rotate": "policy",
                             "cut": "per key at the policy (best_cut) and the full bank cut (bank_cut)",
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
    fp, fp_why = None, static_why
    if static is not None:
        fp = geometry.footprint(ctx.session_id, ctx.store.root, shape=static.shape[:2])
        fp_why = None if fp is not None else "geometry.footprint is None: this map's art is not fetched"
    return AbilityGlyphReader(data or GlyphData.load(ctx.store.root), box, ctx.session_id,
                              candidates, candidates_from, icons, hz=hz, spans=spans,
                              ms=geometry.map_scale_of(ctx.session_id, ctx.store.root),
                              static=static, static_reason=static_why,
                              portraits=portraits, portraits_reason=portraits_why,
                              footprint=fp, footprint_reason=fp_why)
