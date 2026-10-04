r"""Can a whitened open-set null replace the IoU floor as the killfeed weapon
scorer's open-set gate? A leave-one-icon-out evaluation on stored rows.

weapon-adjudication-1.4.0 names a registered soft glyph by the whitened
matched filter (`adjudication.weapon._name_white`) only among the names the
IoU floor clears (`_name_icon`): the IoU floor is its open-set gate. This
prototype tests a gate that reads the filter's own geometry instead: the
glyph's Mahalanobis distance to its winning reference row,
`d2 = (g - mu)' S^-1 (g - mu)`, under the residual covariance S that
`weapon.whiten_covariance` fits. A glyph farther than `tau` from every
allowed reference is `new`.

Gates, each over the full gallery at scale 1.0 (every probe and Riot row is
at 1.0):

* IOU: weapon-adjudication-1.3.0's rule (`_name_icon`) alone.
* WIRED: 1.4.0 (`name_frame` with the whitened parameters): IoU-cleared
  names, whitened winner, registration limits, pairwise tie.
* NULL: the whitened winner over all allowed names, `d2 <= tau` in place of
  the IoU floor, then the same registration limits and tie. A row without a
  readable canvas keeps the IoU rule, as in WIRED.

Split: the separability probe's sessions (`weapon.WHITEN_DEV_SESSIONS` dev,
the other ten held). Labels: the probe index (`--probe`, keys only), the
pipeline's resolved weapon verdicts: agreement, not accuracy, and only
entries the IoU rule resolved, so the in-gallery counts favour IOU.

Stages:

* `dev`: tau is the TAU_QUANTILE of d2 of dev crops the whitened argmax
  names right, each session's crops scored under a covariance fit without
  that session (leave-one-session-out). Then leave-one-icon-out (LOIO): per
  name with dev crops, the covariance is refit without that name's
  residuals, its reference rows and IoU exemplars dropped, and its crops
  scored against the rest; a crop any gate names is an unseen icon misnamed.
  Writes `tau` to `<out>/frozen.json`.
* `held`: reads `frozen.json`, never refits tau, and scores held crops in
  gallery and under LOIO.
* `paint`: d2 of 4f207c0c4e39's Paint Shells frames, 1759-1767 s.
* `riot SID...`: deaths per gate from the pinned reader-trial inputs
  (`--inputs`, pickles of `prototypes/killfeed_trial_deaths.py`-merged
  streams) through `cli.death_streams`, written under `<out>/riot/<gate>/`
  for `prototypes/riot_ground_truth.py --deaths-from`.

Reads stored rows and the crop-free `killfeed_weapon` soft glyphs only; no
decode. Run single-threaded at Below Normal priority:

    .\.venv\Scripts\python.exe prototypes\weapon_null_eval.py dev --out DIR
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402
from scipy.linalg import cho_factor, cho_solve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reticle.adjudication import weapon as W  # noqa: E402
from reticle.killfeed import unpack_icon_grid  # noqa: E402
from reticle.store import Store  # noqa: E402

TAU_QUANTILE = 0.999
#: NULLS (chosen on dev after NULL failed there): d2 over the winning name's
#: median right-crop d2, cut at this quantile of the dev LOSO ratios.
SCALED_QUANTILE = 0.995
SCALE_MIN_CROPS = 3
SCALE = 1.0
DEFAULT_PROBE = "analysis/whitened-weapon-null-20261004/probe_index.json"


def below_normal() -> None:
    """Below Normal priority on Windows; a no-op elsewhere."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except (AttributeError, OSError):
        pass


class Base:
    """The dev fit's parts, built once: references, fit rows and the IoU
    gallery."""

    def __init__(self, store: Store):
        self.store = store
        rf = W.whiten_references(store, SCALE, W.WHITEN_DEV_SESSIONS)
        self.names = np.array(rf["names"])
        self.kinds = np.array(rf["kinds"])
        self.R = rf["refs"].astype(np.float64)
        self.game_names = rf["game_names"]
        self.G, lab, sids, _fit = W.whiten_fit_matrix(store, SCALE, W.WHITEN_DEV_SESSIONS,
                                                      self.game_names)
        self.G = self.G.astype(np.float64)
        self.lab = np.array(lab)
        self.fit_sid = np.array(sids)
        gi = {n: i for i, n in enumerate(self.names) if self.kinds[i] == "game"}
        self.res = self.G - self.R[[gi[n] for n in self.lab]]
        self.gallery, why = W.load_gallery(store.root, SCALE)
        if self.gallery is None:
            raise RuntimeError(why)
        full = self.fold()
        self.limits = self._limits(full)

    def fold(self, drop_sessions=(), drop_name=None) -> dict:
        """Parameters fit without `drop_sessions`' residuals and without
        `drop_name`'s residuals and reference rows, in `load_whitening`'s
        shape plus the Cholesky factor (`cho`)."""
        keep_fit = ~np.isin(self.fit_sid, list(drop_sessions))
        keep_ref = np.ones(len(self.names), bool)
        if drop_name is not None:
            keep_fit &= self.lab != drop_name
            keep_ref &= self.names != drop_name
        S = W.whiten_covariance(self.res[keep_fit])
        cho = cho_factor(S, lower=True, check_finite=False)
        R = self.R[keep_ref]
        Wm = cho_solve(cho, R.T, check_finite=False).T
        c = 0.5 * np.einsum("kd,kd->k", Wm, R)
        return {"names": self.names[keep_ref], "kinds": self.kinds[keep_ref],
                "refs": R.astype(np.float32), "W": Wm.astype(np.float32),
                "c": c.astype(np.float32), "cho": cho,
                "provenance": {"limits": getattr(self, "limits", {}), "scale": SCALE,
                               "fit_rows": int(keep_fit.sum())}}

    def _limits(self, p: dict) -> dict:
        """The registration limits of `build_whitening`, from the full dev fit."""
        sc = self.G @ p["W"].T.astype(np.float64) - p["c"][None]
        best = sc.argmax(axis=1)
        hc, wc = int(round(W.WHITEN_CANVAS[0] * SCALE)), int(round(W.WHITEN_CANVAS[1] * SCALE))
        cov = np.array([W._coverage(self.G[i].reshape(hc, wc).astype(np.float32),
                                    p["refs"][best[i]].reshape(hc, wc))
                        for i in range(len(self.G)) if p["names"][best[i]] == self.lab[i]])
        return {"excess": round(float(np.quantile(cov[:, 0], W.WHITEN_REG_QUANTILE)), 4),
                "deficit": round(float(np.quantile(cov[:, 1], W.WHITEN_REG_QUANTILE)), 4)}

    def gallery_without(self, name):
        if name is None:
            return self.gallery
        keep = np.array([str(n) != name for n in self.gallery["names"]])
        return {k: (v[keep] if isinstance(v, np.ndarray) and len(v) == len(keep) else v)
                for k, v in self.gallery.items()}


def d2_of(p: dict, canvases: np.ndarray) -> np.ndarray:
    """Mahalanobis distance of each canvas row to each reference row, (n, k)."""
    C = canvases.reshape(len(canvases), -1).astype(np.float64)
    q = np.einsum("nd,nd->n", C, cho_solve(p["cho"], C.T, check_finite=False).T)
    s = C @ p["W"].T.astype(np.float64) - p["c"][None].astype(np.float64)
    return q[:, None] - 2.0 * s


def load_probe(store: Store, path: Path) -> list[dict]:
    """The probe rows joined to the store's `killfeed_weapon` rows, each with
    its canvas (`soft_canvas`) and split."""
    index = json.loads(Path(path).read_text())
    by_sid: dict[str, dict] = {}
    out = []
    dev = set(W.WHITEN_DEV_SESSIONS)
    for r in index:
        sid = r["sid"]
        if sid not in by_sid:
            by_sid[sid] = {(float(o["t_ms"]), int(o["slot"])): o
                           for o in store.read_events("killfeed_weapon", sid) or []
                           if o.get("kind") == "weapon_icon_observation"}
        o = by_sid[sid].get((float(r["t_ms"]), int(r["slot"])))
        if o is None:
            continue
        cv, info = W.soft_canvas(o, SCALE)
        out.append({"sid": sid, "t_ms": float(r["t_ms"]), "slot": int(r["slot"]),
                    "name": r["name"], "part": "dev" if sid in dev else "held", "row": o,
                    "canvas": cv, "info": info,
                    "grid": unpack_icon_grid(o["grid"]), "aspect": o["aspect"]})
    return out


def null_frame(grid, aspect, tiers, canvas, d2row: dict, tau: float, scales=None) -> dict:
    """The NULL gate on one frame: per tier, the whitened winner among the
    tier's names; `new` (try the next tier) when its d2 exceeds `tau`;
    otherwise registration and tie as `_name_white`. A row without a
    readable canvas keeps `name_frame`'s IoU rule. `d2row` maps each
    reference name to the frame's smallest d2 over that name's rows. Given
    `scales` (`{"names": {name: median}, "fallback": x}`), the statistic is
    d2 over the winner's scale (NULLS)."""
    if canvas is None or canvas[0] is None:
        return W.name_frame(grid, aspect, tiers, canvas)
    c, info = canvas
    last = None
    for t in tiers:
        names = t["white"]["names"]
        if not names:
            continue
        v = W._name_white(c, t["white"], set(names))
        d2 = d2row.get(v["best"])
        if d2 is not None and scales is not None:
            d2 = d2 / scales["names"].get(v["best"], scales["fallback"])
        v.update(d2=None if d2 is None else round(float(d2), 1), tier=t["tier"],
                 registration=info, kit_floor=False)
        if d2 is None or d2 > tau:
            last = dict(v, name=None, reason=W.REFUSE_NEW)
            continue
        return v
    return last or {"name": None, "reason": W.REFUSE_NEW, "tier": tiers[-1]["tier"],
                    "best": None, "scorer": "whitened", "kit_floor": False}


def name_d2(p: dict, d2: np.ndarray) -> list[dict]:
    """Per frame, the smallest d2 of each name over its rows."""
    out = []
    names = p["names"]
    for row in d2:
        m: dict[str, float] = {}
        for n, v in zip(names, row):
            if n not in m or v < m[n]:
                m[n] = float(v)
        out.append(m)
    return out


GATES = ("iou", "wired", "null", "nulls", "inter")


def score_gates(base: Base, p: dict, rows: list[dict], tau: float, drop_name=None,
                scaled: dict | None = None) -> list[dict]:
    """IOU, WIRED, NULL, NULLS and INTER verdicts of `rows` against fold `p`
    and the IoU gallery without `drop_name`. NULLS is NULL on d2 over the
    winner's scale against `scaled["tau"]`; INTER is WIRED's name kept only
    when that scaled statistic passes (else `new`). Without `scaled` both
    repeat NULL."""
    gal = base.gallery_without(drop_name)
    iou_index = W._icon_index(gal)
    tiers = W.candidate_tiers(gal, None, None, p)
    have = [i for i, r in enumerate(rows) if r["canvas"] is not None]
    d2 = np.zeros((len(rows), len(p["names"])))
    if have:
        d2[have] = d2_of(p, np.stack([rows[i]["canvas"] for i in have]))
    per = name_d2(p, d2)
    out = []
    for i, r in enumerate(rows):
        canvas = ((r["canvas"], r["info"]) if r["canvas"] is not None
                  or r["info"].get("reason") == "no_edge" else None)
        iou = W._name_icon(r["grid"], r["aspect"], iou_index)
        wired = W.name_frame(r["grid"], r["aspect"], tiers, canvas)
        nul = null_frame(r["grid"], r["aspect"], tiers, canvas,
                         per[i] if r["canvas"] is not None else {}, tau)
        nuls, inter = nul, wired
        if scaled is not None:
            nuls = null_frame(r["grid"], r["aspect"], tiers, canvas,
                              per[i] if r["canvas"] is not None else {}, scaled["tau"], scaled)
            if wired["name"] is not None and wired.get("scorer") == "whitened":
                ratio = per[i][wired["name"]] / scaled["names"].get(wired["name"], scaled["fallback"])
                if ratio > scaled["tau"]:
                    inter = dict(wired, name=None, reason=W.REFUSE_NEW)
        best = None
        if r["canvas"] is not None:
            j = int(np.argmin(d2[i]))
            best = (str(p["names"][j]), float(d2[i, j]))
        out.append({"iou": (iou["name"], iou.get("reason")), "wired": (wired["name"], wired.get("reason")),
                    "null": (nul["name"], nul.get("reason")),
                    "nulls": (nuls["name"], nuls.get("reason")),
                    "inter": (inter["name"], inter.get("reason")), "argmin": best,
                    "own_d2": per[i].get(r["name"]) if r["canvas"] is not None else None})
    return out


def tally(rows, verdicts, gate, unseen=False) -> dict:
    """right / wrong / refused (by reason) of `gate`; under LOIO every name is wrong."""
    c = collections.Counter()
    for r, v in zip(rows, verdicts):
        name, why = v[gate]
        if name is None:
            c[f"refused:{why}"] += 1
        elif not unseen and name == r["name"]:
            c["right"] += 1
        else:
            c["wrong"] += 1
    return dict(sorted(c.items()))


def loio(base: Base, rows: list[dict], tau: float, names, scaled=None) -> dict:
    """Leave-one-icon-out over `names`: each name's rows scored with it gone."""
    out = {}
    for n in names:
        mine = [r for r in rows if r["name"] == n]
        if not mine:
            continue
        p = base.fold(drop_name=n)
        v = score_gates(base, p, mine, tau, drop_name=n, scaled=scaled)
        out[n] = {"rows": len(mine), **{g: tally(mine, v, g, unseen=True) for g in GATES},
                  **{f"{g}_named_as": dict(collections.Counter(x[g][0] for x in v if x[g][0]))
                     for g in GATES},
                  "d2_nearest_q": (np.quantile([x["argmin"][1] for x in v if x["argmin"]], [0, .1, .5]).round(1).tolist()
                                   if any(x["argmin"] for x in v) else None)}
        print(f"  LOIO {n}: {out[n]['rows']} rows; "
              + "; ".join(f"{g} {out[n][g]}" for g in GATES)
              + f"; d2 nearest q0/.1/.5 {out[n]['d2_nearest_q']}", flush=True)
    return out


def pooled(per: dict) -> dict:
    tot = {g: collections.Counter() for g in GATES}
    for v in per.values():
        for g in tot:
            tot[g].update(v[g])
    return {g: {"named": c.get("wrong", 0), "refused": sum(x for k, x in c.items() if k.startswith("refused")),
                **dict(c)} for g, c in tot.items()}


def loso_d2(base: Base, rows: list[dict], known) -> list[tuple[str, float]]:
    """(name, d2) of each dev crop the whitened argmax names right, scored
    under a covariance fit without its session."""
    out = []
    for sid in W.WHITEN_DEV_SESSIONS:
        mine = [r for r in rows if r["sid"] == sid and r["canvas"] is not None and r["name"] in known]
        if not mine:
            continue
        p = base.fold(drop_sessions={sid})
        d2 = d2_of(p, np.stack([r["canvas"] for r in mine]))
        j = d2.argmin(axis=1)
        lab = np.array([r["name"] for r in mine])
        right = p["names"][j] == lab
        best = d2[np.arange(len(mine)), j]
        out.extend(zip(lab[right].tolist(), best[right].tolist()))
        print(f"  LOSO {sid}: {len(mine)} rows, argmin right {int(right.sum())}, "
              f"d2 q.5/.99/max {np.quantile(best[right], [.5, .99, 1]).round(1).tolist()}", flush=True)
    return out


def fit_scales(pairs: list[tuple[str, float]]) -> dict:
    """NULLS's per-name scale: the median LOSO right d2 of each name with at
    least SCALE_MIN_CROPS dev crops; the fallback for any other name is the
    median of those medians."""
    by: dict[str, list[float]] = collections.defaultdict(list)
    for n, v in pairs:
        by[n].append(v)
    names = {n: float(np.median(v)) for n, v in by.items() if len(v) >= SCALE_MIN_CROPS}
    fb = float(np.median(list(names.values())))
    ratio = np.array([v / names.get(n, fb) for n, v in pairs])
    return {"names": names, "fallback": fb, "tau": float(np.quantile(ratio, SCALED_QUANTILE)),
            "quantile": SCALED_QUANTILE, "min_crops": SCALE_MIN_CROPS,
            "ratio_q": np.quantile(ratio, [.5, .99, .995, .999, 1]).round(2).tolist()}


def stage_dev(store: Store, args) -> dict:
    base = Base(store)
    rows = [r for r in load_probe(store, args.probe) if r["part"] == "dev"]
    known = set(base.names)
    print(f"dev: {len(rows)} probe rows, {sum(r['canvas'] is not None for r in rows)} with a canvas; "
          f"{len(base.G)} fit rows; {len(known)} reference names; limits {base.limits}", flush=True)
    pairs = loso_d2(base, rows, known)
    d2s = np.array([v for _n, v in pairs])
    tau = float(np.quantile(d2s, TAU_QUANTILE))
    print(f"tau = q{TAU_QUANTILE} of {len(d2s)} LOSO right d2 = {tau:.1f} "
          f"(q.5 {np.quantile(d2s, .5):.1f}, q.99 {np.quantile(d2s, .99):.1f}, max {d2s.max():.1f}; "
          f"dims {base.G.shape[1]})", flush=True)
    scaled = fit_scales(pairs)
    print(f"scaled: tau {scaled['tau']:.2f} = q{SCALED_QUANTILE} of d2/scale (q.5/.99/.995/.999/max "
          f"{scaled['ratio_q']}); fallback scale {scaled['fallback']:.1f}; "
          f"{len(scaled['names'])} named scales", flush=True)
    full = base.fold()
    inr = [r for r in rows if r["name"] in known]
    inv = score_gates(base, full, inr, tau, scaled=scaled)
    ing = {g: tally(inr, inv, g) for g in GATES}
    print(f"dev in gallery: {ing}", flush=True)
    names = sorted({r["name"] for r in inr})
    lo = loio(base, rows, tau, names, scaled)
    out = {"tau": tau, "tau_quantile": TAU_QUANTILE, "loso_right_d2": len(d2s), "scaled": scaled,
           "limits": base.limits, "fit_rows": int(len(base.G)), "in_gallery": ing,
           "loio": lo, "loio_pooled": pooled(lo)}
    print(f"dev LOIO pooled: {out['loio_pooled']}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "frozen.json").write_text(json.dumps({"tau": tau, "tau_quantile": TAU_QUANTILE,
                                                      "scaled": scaled, "limits": base.limits}, indent=1))
    return out


def stage_held(store: Store, args) -> dict:
    frozen = json.loads((args.out / "frozen.json").read_text())
    tau, scaled = frozen["tau"], frozen["scaled"]
    base = Base(store)
    rows = [r for r in load_probe(store, args.probe) if r["part"] == "held"]
    known = set(base.names)
    full = base.fold()
    inr = [r for r in rows if r["name"] in known]
    inv = score_gates(base, full, inr, tau, scaled=scaled)
    ing = {g: tally(inr, inv, g) for g in GATES}
    print(f"held: {len(rows)} probe rows ({len(inr)} with a reference name); tau {tau:.1f}, "
          f"scaled tau {scaled['tau']:.2f} frozen", flush=True)
    print(f"held in gallery: {ing}", flush=True)
    notright = [{"sid": r["sid"], "t": r["t_ms"] / 1000, "slot": r["slot"], "label": r["name"],
                 **{g: v[g] for g in GATES}, "argmin": v["argmin"], "own_d2": v["own_d2"]}
                for r, v in zip(inr, inv) if any(v[g][0] != r["name"] for g in GATES)]
    for x in notright:
        print("   ", x, flush=True)
    # Names absent from the references: a natural open set.
    outr = [r for r in rows if r["name"] not in known]
    outv = score_gates(base, full, outr, tau, scaled=scaled) if outr else []
    absent = {}
    for n in sorted({r["name"] for r in outr}):
        idx = [i for i, r in enumerate(outr) if r["name"] == n]
        absent[n] = {"rows": len(idx), **{g: dict(collections.Counter(
            f"{outv[i][g][0]}" if outv[i][g][0] else f"refused:{outv[i][g][1]}" for i in idx))
            for g in GATES}}
        print(f"  absent {n}: {absent[n]}", flush=True)
    lo = loio(base, rows, tau, sorted({r["name"] for r in inr}), scaled)
    out = {"tau": tau, "scaled": scaled, "in_gallery": ing, "not_right": notright, "absent": absent,
           "loio": lo, "loio_pooled": pooled(lo)}
    print(f"held LOIO pooled: {out['loio_pooled']}", flush=True)
    return out


def stage_paint(store: Store, args) -> dict:
    frozen = json.loads((args.out / "frozen.json").read_text())
    tau, scaled = frozen["tau"], frozen["scaled"]
    base = Base(store)
    full = base.fold()
    sid = "4f207c0c4e39"
    rows = [o for o in store.read_events("killfeed_weapon", sid) or []
            if o.get("kind") == "weapon_icon_observation" and 1759000 <= float(o["t_ms"]) <= 1767000
            and o.get("wx1")]
    out = []
    for o in rows:
        cv, info = W.soft_canvas(o, SCALE)
        if cv is None:
            out.append({"t": o["t_ms"] / 1000, "slot": o["slot"], "canvas": info})
            continue
        d2 = d2_of(full, cv[None])[0]
        per = name_d2(full, d2[None])[0]
        top = sorted(per.items(), key=lambda kv: kv[1])[:3]
        ratio = top[0][1] / scaled["names"].get(top[0][0], scaled["fallback"])
        out.append({"t": o["t_ms"] / 1000, "slot": o["slot"],
                    "nearest": [(n, round(v, 1)) for n, v in top], "null_pass": top[0][1] <= tau,
                    "ratio": round(ratio, 2), "nulls_pass": ratio <= scaled["tau"]})
    print(f"tau {tau:.1f}; scaled tau {scaled['tau']:.2f}, fallback scale {scaled['fallback']:.1f}")
    for x in out:
        print("   ", x)
    return {"tau": tau, "scaled_tau": scaled["tau"], "frames": out}


def stage_riot(store: Store, args) -> dict:
    """Deaths per gate from the pinned inputs, for the Riot scorer."""
    import pickle
    from reticle.cli import death_streams
    frozen = json.loads((args.out / "frozen.json").read_text())
    tau, scaled = frozen["tau"], frozen["scaled"]
    base = Base(store)
    full = base.fold()
    real_load, real_frame = W.load_whitening, W.name_frame
    canvas_d2: dict[int, dict] = {}

    def d2_for(canvas):
        key = id(canvas[0])
        if key not in canvas_d2:
            canvas_d2[key] = (canvas[0], name_d2(full, d2_of(full, canvas[0][None]))[0])
        return canvas_d2[key][1]

    def null_name_frame(grid, aspect, tiers, canvas=None, sc=None):
        if canvas is None or canvas[0] is None:
            return real_frame(grid, aspect, tiers, canvas)
        return null_frame(grid, aspect, tiers, canvas, d2_for(canvas),
                          tau if sc is None else sc["tau"], sc)

    def inter_name_frame(grid, aspect, tiers, canvas=None):
        # WIRED tier by tier; a whitened name whose scaled d2 fails is `new`
        # at that tier, and the next tier is tried, as an IoU `new` is.
        v = None
        for t in tiers:
            v = real_frame(grid, aspect, [t], canvas)
            if v.get("reason") == W.REFUSE_NEW:
                continue
            if v.get("scorer") == "whitened" and v["name"] is not None:
                ratio = d2_for(canvas)[v["name"]] / scaled["names"].get(v["name"], scaled["fallback"])
                if ratio > scaled["tau"]:
                    v = dict(v, name=None, reason=W.REFUSE_NEW, ratio=round(ratio, 2))
                    continue
            return v
        return v

    frames = {"null": null_name_frame, "nulls": lambda g, a, t, c=None: null_name_frame(g, a, t, c, scaled),
              "inter": inter_name_frame}
    report = {}
    for sid in args.sessions:
        obj = pickle.load(open(Path(args.inputs) / f"{sid}.pkl", "rb"))
        for gate in GATES:
            W._WHITEN_CACHE.clear()
            canvas_d2.clear()
            W.load_whitening = ((lambda *a, **k: (None, "no_whitening:disabled")) if gate == "iou"
                                else (lambda *a, **k: (full, None)))
            W.name_frame = frames.get(gate, real_frame)
            try:
                d = death_streams(store, obj["man"], hud=obj["hud"],
                                  portraits=obj["streams"]["killfeed_portrait"],
                                  weapons=obj["streams"]["killfeed_weapon"],
                                  names=obj["streams"]["killfeed_name"])
            finally:
                W.load_whitening, W.name_frame = real_load, real_frame
            p = args.out / "riot" / gate / "events" / "death" / f"{sid}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as f:
                for r in [d["head"]] + d["rows"] + d["collisions"]:
                    f.write(json.dumps(r, default=str) + "\n")
            st = collections.Counter((r.get("weapon_evidence") or {}).get("status") for r in d["rows"])
            report.setdefault(sid, {})[gate] = dict(st)
            print(f"{sid} {gate}: {len(d['rows'])} rows, weapon status {dict(st)} -> {p}", flush=True)
    return report


def stage_record(store: Store, args) -> dict:
    """Record the stored stage outputs as the `weapon_null` metric series
    (`reticle.metrics.record`): per split and gate the in-gallery and LOIO
    counts, the thresholds, and per gate the Riot weapon counts from the
    scorer's `--json` outputs (`<out>/riot/<gate>/score.json`)."""
    import hashlib
    from reticle import metrics
    src = Path(__file__).read_bytes()
    deps = {"prototype_sha1": hashlib.sha1(src).hexdigest()[:12],
            "weapon_adjudication": W.WEAPON_ADJUDICATION_VERSION,
            "weapon_gallery": W.WEAPON_GALLERY_VERSION, "whiten": W.WEAPON_WHITEN_VERSION,
            "tau_quantile": TAU_QUANTILE, "scaled_quantile": SCALED_QUANTILE, "scale": SCALE}
    ctx = {"probe": str(args.probe), "dev_sessions": list(W.WHITEN_DEV_SESSIONS),
           "outputs": str(args.out)}
    rec = {}
    for split in ("dev", "held"):
        p = args.out / f"{split}.json"
        if not p.is_file():
            continue
        r = json.loads(p.read_text())
        for g in GATES:
            ing, lo = r["in_gallery"][g], r["loio_pooled"][g]
            vals = {"right": ing.get("right", 0), "wrong": ing.get("wrong", 0),
                    "refused": sum(v for k, v in ing.items() if k.startswith("refused")),
                    "loio_named": lo["named"], "loio_refused": lo["refused"]}
            metrics.record("weapon_null", part=f"{split}/{g}", values=vals, deps=deps, context=ctx)
            rec[f"{split}/{g}"] = vals
        thr = {"tau": round(r["tau"], 1), "scaled_tau": round(r["scaled"]["tau"], 2),
               "scaled_fallback": round(r["scaled"]["fallback"], 1)}
        metrics.record("weapon_null", part=f"{split}/thresholds", values=thr, deps=deps, context=ctx)
        rec[f"{split}/thresholds"] = thr
    for g in GATES:
        p = args.out / "riot" / g / "score.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text())
        keys = ("weapon_right", "weapon_wrong", "weapon_refused")
        w = (d.get("pool") or {}).get("deaths") or {}
        vals = {k: w.get(k, 0) for k in keys}
        sessions = [r for r in d.get("sessions", []) if isinstance(r, dict) and "deaths" in r]
        metrics.record("weapon_null", part=f"riot/{g}", values=vals, deps=deps,
                       context=dict(ctx, sessions=sorted(r["session"] for r in sessions)))
        rec[f"riot/{g}"] = vals
        for r in sessions:
            sv = {k: (r["deaths"] or {}).get(k, 0) for k in keys}
            metrics.record("weapon_null", part=f"riot/{g}", session=r["session"], values=sv,
                           deps=deps, context=ctx)
            rec[f"riot/{g}@{r['session']}"] = sv
    for k, v in rec.items():
        print(k, " ".join(f"[metric:weapon_null/{k}#{n}={x}]" for n, x in v.items()))
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=("dev", "held", "paint", "riot", "record"))
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--store", default=None)
    ap.add_argument("--probe", default=None, help=f"probe index (default <store>/{DEFAULT_PROBE})")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--inputs", default=None, help="riot: directory of pinned <sid>.pkl inputs")
    args = ap.parse_args(argv)
    below_normal()
    store = Store(args.store) if args.store else Store()
    args.probe = Path(args.probe) if args.probe else store.root / DEFAULT_PROBE
    res = {"dev": stage_dev, "held": stage_held, "paint": stage_paint, "riot": stage_riot,
           "record": stage_record}[args.stage](store, args)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.stage}.json").write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
