r"""Minimap ability glyphs: each proposed disc's score against the game's minimap textures.

    .\.venv\Scripts\python.exe -m reticle scan <session> --only ability
    .\.venv\Scripts\python.exe -m reticle trial <session> --reader ability_glyph --from cache

Owns [owns:ability-glyph]. Stage 2 of `docs/MINIMAP_GLYPH_CHANNEL.md`
(section 2, "The glyph reader"): a `passes.Reader` that rides the ability
pass at 2 Hz on live samples and stores, per proposed disc and frame, how
well each candidate kit's game textures score there. It names nothing: the
tracks, the verdict and the identity claims are stage 3's
(`ability-disc-track`, `ability-glyph-name`, `agent-identity`).

Why. A thrown or placed ability draws a dark disc with a white glyph on the
minimap [domain:abilities/minimap-thrown-ability-icon]; the glyph is the
ability's own game texture, so the game files name it. The proposer
(`ability_icons`, which owns `ability-icon`) finds the discs; this reader reads
the proposer's candidates for the same frame and never reruns it.

Inputs, as versioned data from the store, never from `prototypes/`:

- the reference bank (`glyph-bank-0.1.0`, written by
  `prototypes/glyph_tables.py bank`): each catalogue key's 128 px glyphs,
  the ability's DisplayIcon and the exported minimap textures the stage 1
  tables were built on (the state inventory's minimap brushes and the
  player's texture answers, [domain:abilities/minimap-textures-deadlock]
  and its siblings). Game files, never mined captures.
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
The scale is the crop's width against `minimap.REF_WIDGET_W`, the widget
scale the stage 1 tables were measured at; the canvas search spans the map
zoom. All discs of a frame score in one matrix product, on the GPU when
cupy and a CUDA device are present (`RETICLE_GLYPH=cpu` forces numpy).

Candidate sets. Continue the prior: the context set is the match lineup's
kits, both sides, as `lineup.glyph_candidates` admits them (named slots,
each refused slot's best guess as a rival), scored under the policy
rotations on every disc. The full set, every agent's kit, runs on two paths
only, each row marked by `set`:

- the audit: the first birth and every AUDIT_EVERY-th after it (a cadence
  fixed in advance, a design choice), scored against every kit, every key
  rotated, on each frame of its window. It measures what the lineup prior
  and the rotation policy hide.
- the surprise: a window whose best context key never clears that key's
  null cut is rescored against every kit, policy rotations, when it
  closes. Never an audit sample.

Windows. A birth is a disc no open window continues: the Hungarian
assignment (`scipy.optimize.linear_sum_assignment`) of this frame's discs
to the open windows' last fixes within the prototype follow's reach (4 px +
2 per missed frame, at most 24, x scale). A window schedules the audit and
the surprise for WINDOW_MS after its birth; each fix `rests_on` the fix
before. A window is an execution schedule, not a track: `adjudication.ability`
joins discs into tracks from the stored rows. An unread frame ends every
window, as the proposer's verify restarts there.

Not done here (stage 3 or later): the follow at the cache's cadence (stage
1's S4 measured the 2 Hz arm equal on dev, 0 points apart), per-view texture
gating from the state inventory (the verdict's gate), the Deadlock:Q wall
normals, naming, and claims.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np

from .minimap import REF_WIDGET_W
from .usage import step as usage_step
from .version import ABILITY_GLYPH_VERSION, ABILITY_ICON_VERSION

#: The store files the reader reads: (directory under the store, version).
GLYPH_DATA = {"bank": ("analysis/glyph-bank-20261005", "glyph-bank-0.1.0"),
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
REACH_BASE = (4.0, 2.0, 24.0)
AUDIT_EVERY = 10
SETS = ("context", "audit", "surprise")


def _agent_key(agent: str | None) -> str:
    """An agent name compared across stores: `KAY_O` and `KAY/O` are one."""
    return "".join(ch for ch in (agent or "").lower() if ch.isalnum())


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class GlyphData:
    """The reference bank, the rotation policy and the null table, loaded and
    checked against each other."""

    def __init__(self, keys, sources, rotating, cuts, provenance):
        #: Catalogue keys ("Agent:Slot"), sorted.
        self.keys: list[str] = keys
        #: key -> [(provenance, 128 px glyph)], the DisplayIcon first.
        self.sources: dict[str, list[tuple[str, np.ndarray]]] = sources
        #: Keys the policy searches at every rotation.
        self.rotating: set[str] = rotating
        #: key -> its per-key null cut (overall).
        self.cuts: dict[str, float] = cuts
        self.provenance: dict = provenance

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
        sources: dict = {}
        for g, k, p in zip(glyphs, owner, prov):
            sources.setdefault(k, []).append((p, g))
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
        return cls(keys, sources, rotating, cuts, provenance)

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


# ------------------------------------------------------------------ the reader


class _Window:
    __slots__ = ("id", "birth_t", "x", "y", "last", "missed", "audit", "cleared", "open", "pending")

    def __init__(self, wid, t, x, y, disc, audit):
        self.id, self.birth_t, self.x, self.y, self.last = wid, t, x, y, disc
        self.missed, self.audit, self.cleared, self.open = 0, audit, False, True
        self.pending: list = []


class AbilityGlyphReader:
    """`passes.Reader` writing the `ability_glyph` stream (module docstring)."""

    cache_resample = True
    records_clip = True

    def __init__(self, data: GlyphData, box, session_id: str, candidates: dict | None,
                 candidates_from: str | None, icons, hz: float = 2.0, spans=None, ms=None,
                 name: str = "ability_glyph", audit_every: int = AUDIT_EVERY):
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
        self.xp, self.scorer = _backend()
        self._tm: dict = {}
        self._windows: list[_Window] = []
        self.births = 0
        self.n_windows = {"audit": 0, "surprise": 0}
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
        cut = self.data.cuts.get(b)
        return {**base, "set": which, "scores": scores, "best": b, "second": sec,
                "margin": round(margin, 4), "best_cut": cut,
                "above_cut": None if cut is None else bool(float(best[o[0]]) > cut)}

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
        for w in self._windows:
            self._close(w, why)
        self._windows = []

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
            self.rows.append({**row, "reason": reason, "discs": None, "births": None})
            self._end_all(reason)
            return
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        scale = crop.shape[1] / REF_WIDGET_W
        cands = ir.get("candidates") or []
        with usage_step("luma"):
            y = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)
        tm = self.templates("context", scale)
        xy = np.array([[c["cx"], c["cy"]] for c in cands], float).reshape(-1, 2)
        wins, ok = disc_windows(y, xy, tm.w, tm.sh)
        # Windows whose schedule ran out close before this frame links.
        for w in self._windows:
            if w.open and t - w.birth_t > WINDOW_MS:
                self._close(w, "window_end")
        with usage_step("link"):
            link = self._link(xy, scale)
        births = 0
        bases = []
        for i, c in enumerate(cands):
            win = link.get(i)
            disc = self._disc_id(t, i)
            if win is None:
                self.births += 1
                births += 1
                audit = (self.births - 1) % self.audit_every == 0
                win = _Window(f"{self.sid}:aglyph:{round(t, 3)}:{i}", t, c["cx"], c["cy"], disc, audit)
                if audit:
                    self.n_windows["audit"] += 1
                self._windows.append(win)
                rests = []
            else:
                rests = [win.last]
                win.x, win.y, win.last, win.missed = c["cx"], c["cy"], disc, 0
            bases.append(({"kind": "disc", "t_ms": t, "frame_idx": int(smp.frame_idx), "disc": disc,
                           "i": i, "cx": c["cx"], "cy": c["cy"], "r": c["r"], "scale": round(scale, 5),
                           "window": win.id, "birth": not rests, "rests_on": rests}, win))
        with usage_step("context"):
            best, targ, sarg = score_windows(wins[ok], tm)
        jj = np.cumsum(ok) - 1
        audit_i = []
        for i, (base, win) in enumerate(bases):
            if not ok[i]:
                self.rows.append({**base, "set": "context", "reason": "off_crop", "scores": None})
                continue
            j = int(jj[i])
            r = self._row({**base, "reason": None}, "context", tm, best[j], targ[j], sarg[j])
            self.rows.append(r)
            if win.open:
                if r["above_cut"]:
                    win.cleared, win.pending = True, []
                elif not win.cleared:
                    win.pending.append(({**base, "reason": None}, scale, wins[i]))
                if win.audit:
                    audit_i.append(i)
        if audit_i:
            ta = self.templates("audit", scale)
            with usage_step("audit"):
                ba, ta_arg, sa_arg = score_windows(wins[audit_i], ta)
            for j, i in enumerate(audit_i):
                self.rows.append(self._row({**bases[i][0], "reason": None}, "audit", ta,
                                           ba[j], ta_arg[j], sa_arg[j]))
        # A window no disc continued: its reach widens while its schedule runs;
        # after it, the window ends.
        seen = {id(w) for _, w in bases}
        keep = []
        for w in self._windows:
            if id(w) in seen:
                keep.append(w)
            elif w.open:
                w.missed += 1
                keep.append(w)
        self._windows = keep
        self.rows.append({**row, "reason": None, "discs": len(cands), "births": births})

    def _link(self, xy: np.ndarray, scale: float) -> dict[int, _Window]:
        """{disc index: the window it continues}: the Hungarian assignment of
        this frame's discs to the windows' last fixes within reach."""
        from scipy.optimize import linear_sum_assignment
        ws = self._windows
        if not ws or not len(xy):
            return {}
        last = np.array([[w.x, w.y] for w in ws], float)
        reach = np.minimum(REACH_BASE[0] + REACH_BASE[1] * np.array([w.missed for w in ws]),
                           REACH_BASE[2]) * scale
        d = np.hypot(last[:, None, 0] - xy[None, :, 0], last[:, None, 1] - xy[None, :, 1])
        ok = d <= reach[:, None]
        if not ok.any():
            return {}
        r, c = linear_sum_assignment(np.where(ok, d, 1e9))
        return {int(j): ws[int(i)] for i, j in zip(r, c) if ok[i, j]}

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
                "ability_icon_version": getattr(self.icons, "version", None),
                "ability_icon_source": getattr(self.icons, "source", None),
                "glyph_bank": GLYPH_BANK_STAMP, "glyph_data": self.data.provenance,
                "matcher": {"score": "masked Pearson of luma (YCrCb Y), never binarised",
                            "canvas_base": [float(c) for c in CANVAS_BASE], "mask_r_base": MASK_R_BASE,
                            "shift_base": SHIFT_BASE, "rotations": list(ROTATIONS),
                            "flat_std": FLAT_STD,
                            "resample": "INTER_AREA to shrink each 128 px glyph to its canvas; "
                                        "INTER_LINEAR to turn it",
                            "scale": f"crop width / {REF_WIDGET_W:g} (the stage 1 tables' basis)",
                            "scales": scales, "scorer": self.scorer},
                "candidates": self.candidates, "candidates_from": self.candidates_from,
                "context": {"keys": self.context_keys, "rotate": "policy",
                            "why": "the match lineup's kits, both sides (lineup.glyph_candidates: named "
                                   "slots, refused slots' best guesses as rivals): continue the prior",
                            "agents_without_keys": self.agents_without_keys},
                "audit": {"every": self.audit_every, "keys": "every bank key", "rotate": "all",
                          "rule": "the first birth and every audit_every-th after it, through its window; "
                                  "a cadence fixed in advance"},
                "surprise": {"keys": "every bank key", "rotate": "policy",
                             "rule": "a window whose best context key never exceeds that key's per-key "
                                     "null cut is rescored when it closes; never an audit sample"},
                "window": {"ms": WINDOW_MS, "reach_base": list(REACH_BASE),
                           "rule": "Hungarian assignment of each frame's discs to open windows' last "
                                   "fixes within reach x scale; a schedule, not a track"},
                "textures": {k: [p for p, _ in self.data.sources[k]] for k in self.data.keys},
                "map_scale": None if self.ms is None else self.ms.provenance()}
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            head["spans_clip"] = clip
        order = {s: i for i, s in enumerate(SETS)}
        body = sorted(self.rows, key=lambda r: (r["t_ms"], r["kind"] != "frame",
                                                order.get(r.get("set"), 0), r.get("i", -1)))
        return [head] + [{**common, **r} for r in body]


def glyph_reader(ctx, spans, icons, candidates, candidates_from, hz: float = 2.0,
                 data: GlyphData | None = None) -> AbilityGlyphReader:
    """The `AbilityGlyphReader` `scan` and `trial` build for a session, over
    the profile's minimap ROI, with the candidate set the caller took from
    the lineup's owner (`lineup.glyph_candidates`)."""
    from . import geometry
    from .minimap import minimap_roi_px
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    return AbilityGlyphReader(data or GlyphData.load(ctx.store.root), box, ctx.session_id,
                              candidates, candidates_from, icons, hz=hz, spans=spans,
                              ms=geometry.map_scale_of(ctx.session_id, ctx.store.root))
