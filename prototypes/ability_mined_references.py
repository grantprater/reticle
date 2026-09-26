r"""Mine minimap ability references from the local player's tray casts.

    .\.venv\Scripts\python.exe prototypes\ability_mined_references.py collect [SID ...]
    .\.venv\Scripts\python.exe prototypes\ability_mined_references.py evaluate

Purpose. `minimap_identity_calibration.py` showed that minimap icons labelled
by an independent witness (a killfeed death) make better references than the
official art. This applies the same principle to ability objects. The witness
is the local player's HUD ability tray: a charge drop (`ability_hud.casts`)
is the player's own cast, with slot identity, read from HUD structure and
carrying no minimap appearance. `ability_cast` names the slot's ability.

Inputs. Everything comes from the 15 Hz `minimap` roi cache (minimap and
`hud_abilities` crops over each round); nothing decodes the capture.
`ability_hud.slot_counts` reads each cached tray frame unchanged; the cache's
tray rectangle ends at y=1070, so the reader's lower guard band (1056-1076)
holds 14 of its 20 rows and its bleed ratio from that band reads low. The
upper band is whole. Spans are joined with a refused row between them, so no
drop is read across a round gap.

Candidates. `reticle.minimap.detect_ability_discs` (scaled by
`widget_scale`, static peaks from the baked `(map, profile)` geometry, the
self icon excluded) and `detect_ability_walls` (static lines from the same
geometry, and only the detector's teal/warm/bright colour classes: the first
run without that hint gave a median of 10 new candidates per window, nearly
all neutral LSD lines) run on cached minimap frames at 5 Hz. A candidate is
NEW when it is absent from the frame 1 s before the window opens, and
PERSISTENT when it holds its place for MIN_SAMPLES samples (1 s). The window is `ability_cast`'s position window: cast - POS_PRE
to cast + POS_POST, or + POS_POST_REUSE for a re-usable ability.

Join rule. A cast binds a candidate when exactly one new candidate lies
within NEAR_PX (reference-scale pixels) of the self icon at the cast. The
same rule at control times (cast-free, 8 s from any cast, same rounds)
measures the coincidence rate. Labels are (agent, slot); the slot's name
comes from the reference kit.

Descriptor. A 21x21 patch at reference scale around the candidate, minus the
baked static map patch (the object's own appearance over the map), as BGR
float, plus its 12-bin hue histogram of pixels that differ from the static
map. The mined reference is the mean descriptor per (agent, slot) over build
sessions. Score is cosine similarity.

Outcome (2026-09-26, falsified). Of 2764 cached tray drops, `ability_hud`
flags 2121 suspect, so 643 casts remain. The join binds 157 of them (0.24)
and 219 of 1233 cast-free controls (0.18). Run it Back, which draws nothing,
binds as often as Blaze. The labelled patches are mostly teammate icons that
`ally_icons` misses, death X markers and map texture. Held out, the mined
reference picks the bound object 6/19 times (response 5/19, chance 7.7) and
separates bound from control candidates at AUC 0.54 (response 0.55). Mining
needs cleaner labels first: gate candidates on the killfeed (death markers)
and on teammate identity before averaging.

Split. Within each player agent, sorted session ids, odd index held out;
fixed before measuring. Predictions and outcome: `ability-mined-references`
in the store's `notes/predictions.jsonl`. Analysis caches go to `--work`
(default: the system temp directory); nothing is written to the store.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import geometry  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import (detect_ability_discs, detect_ability_walls,  # noqa: E402
                             ally_icons, extract_static_lines, self_icons, slab_mask,
                             widget_scale,
                             BH_K, BH_MIN)
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402

import ability_cast as ac  # noqa: E402
import ability_hud as ah  # noqa: E402

STORE = ac.STORE
WORK = Path(tempfile.gettempdir()) / "ability_mined_references"
TRAY_STEP_S = 0.5
WIN_STEP_S = 0.2
NEAR_PX = 120.0
PATCH = 21
CONTROL_GAP_S = 8.0
#: The wall detector's own colour classes; "neutral" lines are map texture.
WALL_COLORS = ("warm",)
#: A disc this close to a teammate icon (`reticle.minimap.ally_icons`, which
#: owns teammate icons) is that teammate, not an ability. Reference px.
ALLY_PX = 12.0
#: Samples at WIN_STEP_S a new candidate must hold its place for: 1 s.
MIN_SAMPLES = 5


def session_ids() -> list[str]:
    root = STORE / "roi_cache" / "minimap" / "roi-cache-0.1.0"
    return sorted(p.stem for p in root.glob("*.json") if load_lineup(p.stem, STORE))


def split_by_agent(agents: dict[str, str]) -> tuple[list[str], list[str]]:
    """Build and held-out sessions: within each player agent, odd sorted index held out."""
    build, held = [], []
    by = defaultdict(list)
    for sid, a in agents.items():
        by[a].append(sid)
    for a in sorted(by):
        for i, sid in enumerate(sorted(by[a])):
            (held if i % 2 else build).append(sid)
    return sorted(build), sorted(held)


def open_cache(sid: str):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    cache, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no minimap cache ({why})")
    return man, cache


def grid(cache, t0_ms: float, t1_ms: float, step_s: float) -> list[float]:
    """Cached times nearest a regular grid inside [t0, t1]."""
    t = np.asarray(cache.t_ms, float)
    t = np.unique(t[(t >= t0_ms) & (t <= t1_ms)])
    if not len(t):
        return []
    want = np.arange(t[0], t[-1] + 1, step_s * 1000.0)
    idx = np.unique(np.searchsorted(t, want).clip(0, len(t) - 1))
    return [float(x) for x in t[idx]]


def tray_casts_cached(cache) -> list[tuple]:
    """(t_s, slot, from, to, suspect) from cached tray crops, rounds joined by a refused row."""
    ts, rows, clean = [], [], []
    for a, b in cache.record["spans"]:
        times = grid(cache, a, b, TRAY_STEP_S)
        for smp in cache.samples(times, rois=["hud_abilities"]):
            c, ok = ah.slot_counts(smp.frame)
            ts.append(smp.t_ms / 1000.0)
            rows.append(c)
            clean.append(ok)
        ts.append((ts[-1] if ts else 0.0) + 0.01)
        rows.append([0, 0, 0, 0])
        clean.append(False)
    if not ts:
        return []
    return ah.casts(ts, np.asarray(rows, float), np.asarray(clean, bool))


class MapContext:
    """Baked geometry and detector settings for one session's widget."""

    def __init__(self, sid: str, cache):
        self.rect = cache.rect_of("minimap")
        self.static = geometry.reference_static(sid, STORE)
        self.floor = slab_mask(self.static)
        self.sc = widget_scale(self.rect[2] - self.rect[0])
        self.k = max(3, int(round(BH_K * self.sc)) | 1)
        sg = cv2.cvtColor(self.static, cv2.COLOR_BGR2GRAY)
        self.static_peaks = [(d["cx"], d["cy"], d["response"])
                             for d in detect_ability_discs(sg, self.floor, k=self.k, bh_min=80)]
        self.static_lines = extract_static_lines(self.static, self.floor)

    def crop(self, frame):
        x0, y0, x1, y1 = self.rect
        return frame[y0:y1, x0:x1]

    def detect(self, crop) -> tuple[list[dict], tuple | None]:
        s = self_icons(crop, self.floor)
        self_xy = (s[0]["cx"], s[0]["cy"]) if s else None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        out = [{"kind": "disc", "cx": d["cx"], "cy": d["cy"], "response": d["response"]}
               for d in detect_ability_discs(gray, self.floor, static_peaks=self.static_peaks,
                                             self_xy=self_xy, k=self.k, bh_min=BH_MIN,
                                             dist_tol_px=18.0 * self.sc)]
        for w in detect_ability_walls(crop, self.floor, static_lines=self.static_lines,
                                      self_xy=self_xy, color_hint=WALL_COLORS):
            x1, y1, x2, y2 = (w.get(k) for k in ("x1", "y1", "x2", "y2"))
            if None in (x1, y1, x2, y2):
                continue
            out.append({"kind": f"wall:{w['color']}", "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
                        "response": float(w.get("length", np.hypot(x2 - x1, y2 - y1)))})
        allies = ally_icons(crop, self.floor, static=self.static)
        for c in out:
            c["ally"] = any(np.hypot(c["cx"] - a["cx"], c["cy"] - a["cy"]) < ALLY_PX * self.sc
                            for a in allies)
        return out, self_xy

    def descriptor(self, crop, cx, cy) -> np.ndarray | None:
        """Patch minus static patch at reference scale, plus a hue histogram of changed pixels."""
        half = int(round(PATCH / 2 * self.sc))
        x, y = int(round(cx)), int(round(cy))
        h, w = crop.shape[:2]
        if x - half < 0 or y - half < 0 or x + half + 1 > w or y + half + 1 > h:
            return None
        p = crop[y - half:y + half + 1, x - half:x + half + 1]
        s = self.static[y - half:y + half + 1, x - half:x + half + 1]
        p = cv2.resize(p, (PATCH, PATCH), interpolation=cv2.INTER_AREA).astype(np.float32)
        s = cv2.resize(s, (PATCH, PATCH), interpolation=cv2.INTER_AREA).astype(np.float32)
        d = (p - s)
        changed = np.abs(d).sum(axis=2) > 60
        hsv = cv2.cvtColor(p.astype(np.uint8), cv2.COLOR_BGR2HSV)
        hist = np.bincount((hsv[..., 0][changed].astype(int) * 12) // 180, minlength=12)[:12]
        hist = hist / max(1, hist.sum())
        return np.concatenate([d.ravel() / 255.0, hist * 3.0]).astype(np.float32)


def window_candidates(ctx: MapContext, cache, t_s: float, pre: float, post: float) -> dict:
    """New candidates in [t - pre, t + post], with a descriptor at each one's best sample."""
    t0, t1 = (t_s - pre) * 1000.0, (t_s + post) * 1000.0
    ref_t = grid(cache, t0 - 1000.0, t0 - 800.0, WIN_STEP_S)
    times = grid(cache, t0, t1, WIN_STEP_S)
    if not ref_t or not times:
        return {"status": "uncached"}
    old = []
    for smp in cache.samples(ref_t[:1], rois=["minimap"]):
        old, _ = ctx.detect(ctx.crop(smp.frame))
    tol = 18.0 * ctx.sc
    tracks, self_at = [], None
    for smp in cache.samples(times, rois=["minimap"]):
        crop = ctx.crop(smp.frame)
        found, sxy = ctx.detect(crop)
        if sxy is not None and (self_at is None or abs(smp.t_ms / 1000 - t_s) < self_at[1]):
            self_at = (sxy, abs(smp.t_ms / 1000 - t_s))
        for c in found:
            if any(np.hypot(c["cx"] - o["cx"], c["cy"] - o["cy"]) < tol for o in old):
                continue
            tr = next((r for r in tracks if r["kind"] == c["kind"]
                       and np.hypot(c["cx"] - r["cx"], c["cy"] - r["cy"]) < tol), None)
            if tr is None:
                tr = {"kind": c["kind"], "cx": c["cx"], "cy": c["cy"], "n": 0, "resp": 0.0,
                      "t_on": smp.t_ms / 1000, "desc": None, "ally": 0}
                tracks.append(tr)
            tr["n"] += 1
            tr["ally"] += c["ally"]
            if c["response"] >= tr["resp"]:
                tr["resp"] = c["response"]
                tr["desc"] = ctx.descriptor(crop, c["cx"], c["cy"])
    new = [r for r in tracks if r["n"] >= 2 and r["desc"] is not None]
    sxy = self_at[0] if self_at else None
    for r in new:
        r["d_self"] = (float(np.hypot(r["cx"] - sxy[0], r["cy"] - sxy[1]) / ctx.sc)
                       if sxy is not None else None)
    return {"status": "ok", "self": sxy, "cands": new}


def controls(casts_t: list[float], spans, n: int, rng) -> list[float]:
    """Cast-free times inside the cached rounds, CONTROL_GAP_S from every cast."""
    out, tries = [], 0
    while len(out) < n and tries < 50 * n:
        tries += 1
        a, b = spans[rng.integers(len(spans))]
        t = rng.uniform(a / 1000 + 3, b / 1000 - 6.5)
        if all(abs(t - c) >= CONTROL_GAP_S for c in casts_t + out):
            out.append(float(t))
    return out


def collect_session(sid: str) -> dict:
    man, cache = open_cache(sid)
    agent = load_lineup(sid, STORE)["player"]["agent"]
    kit = ac.kit(agent)
    casts = tray_casts_cached(cache)
    ctx = MapContext(sid, cache)
    rows = []
    for t, slot, f0, f1, sus in casts:
        ab = kit.get(slot)
        post = ac.POS_POST_REUSE if ac.reusable(agent, ab) else ac.POS_POST
        w = window_candidates(ctx, cache, t, ac.POS_PRE, post)
        rows.append({"t": t, "slot": slot, "ability": ab, "suspect": sus,
                     "from": f0, "to": f1, **w})
    rng = np.random.default_rng(int(sid[:8], 16))
    ctrl = []
    for t in controls([r["t"] for r in rows], cache.record["spans"], len(rows), rng):
        ctrl.append({"t": t, **window_candidates(ctx, cache, t, ac.POS_PRE, ac.POS_POST)})
    return {"sid": sid, "agent": agent, "kit": kit, "casts": rows, "controls": ctrl,
            "path": man["source"]["path"], "scale": ctx.sc}


def bound(w: dict) -> dict | None:
    """The one new candidate near the self icon, or None."""
    if w.get("status") != "ok":
        return None
    near = [c for c in persistent(w) if c["d_self"] is not None and c["d_self"] <= NEAR_PX]
    return near[0] if len(near) == 1 else None


def load(work: Path) -> dict:
    return {f.stem: pickle.loads(f.read_bytes()) for f in sorted(work.glob("*.pkl"))}


def lineup_sets(sid: str) -> tuple[set, set]:
    """(named agents, named plus every refused slot's best guess) over both sides."""
    sides = load_lineup(sid, STORE).get("sides", {})
    named, maybe = set(), set()
    for rows in sides.values():
        for r in rows:
            if r.get("agent"):
                named.add(r["agent"])
            for k in ("agent", "best_guess"):
                if r.get(k):
                    maybe.add(r[k])
    return named, maybe


def persistent(w: dict) -> list[dict]:
    """New candidates that hold their place for 1 s and never sit on a teammate icon."""
    return [c for c in w.get("cands", []) if c["n"] >= MIN_SAMPLES and not c.get("ally")]


def cos(a, b) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def collect_labels(data: dict) -> tuple[dict, list[dict]]:
    """Per-session inventory and the cast-bound labels (non-suspect casts only)."""
    inv, labels = {}, []
    for sid, d in data.items():
        cs = [r for r in d["casts"] if not r["suspect"]]
        sus = [r for r in d["casts"] if r["suspect"]]
        inv[sid] = {"agent": d["agent"], "path": d["path"],
                    "casts": dict(Counter(r["slot"] for r in cs)), "suspect": len(sus),
                    "bound": dict(Counter(r["slot"] for r in cs if bound(r))),
                    "bound_suspect": sum(bound(r) is not None for r in sus),
                    "controls": len(d["controls"]),
                    "bound_controls": sum(bound(r) is not None for r in d["controls"])}
        for r in cs:
            b = bound(r)
            if b is not None:
                labels.append({"sid": sid, "agent": d["agent"], "slot": r["slot"],
                               "ability": r["ability"], "cand": b, "win": r})
    return inv, labels


def mean_refs(labels: list[dict], sids: list[str], min_sessions: int = 2) -> dict:
    """(agent, slot) -> mean descriptor over labels from `sids`, when >= min_sessions give one."""
    by = defaultdict(list)
    for L in labels:
        if L["sid"] in sids:
            by[(L["agent"], L["slot"])].append(L)
    return {k: np.mean([L["cand"]["desc"] for L in v], axis=0)
            for k, v in by.items() if len({L["sid"] for L in v}) >= min_sessions}


def auc(pos, neg) -> float | None:
    if not len(pos) or not len(neg):
        return None
    p, n = np.asarray(pos)[:, None], np.asarray(neg)[None, :]
    return round(float((p > n).mean() + 0.5 * (p == n).mean()), 3)


def evaluate(work: Path) -> dict:
    data = load(work)
    agents = {sid: d["agent"] for sid, d in data.items()}
    build, held = split_by_agent(agents)
    inv, labels = collect_labels(data)
    res = {"build": build, "held": held, "inventory": inv}
    rate = defaultdict(lambda: [0, 0])
    for d in data.values():
        for r in d["casts"]:
            if not r["suspect"]:
                k = f"{d['agent']}:{r['slot']}:{d['kit'].get(r['slot'])}"
                rate[k][0] += 1
                rate[k][1] += bound(r) is not None
    ctrl = [r for d in data.values() for r in d["controls"]]
    res["control_bind_rate"] = f"{sum(bound(r) is not None for r in ctrl)}/{len(ctrl)}"
    res["cast_bind_rate"] = {k: f"{b}/{n}" for k, (n, b) in sorted(rate.items())}
    per = defaultdict(lambda: [Counter(), Counter()])
    for L in labels:
        per[f"{L['agent']}:{L['slot']}"][L["sid"] in held][L["sid"]] += 1
    res["labels"] = {k: {"build": sum(b.values()), "build_sessions": len(b),
                         "held": sum(h.values()), "held_sessions": len(h)}
                     for k, (b, h) in sorted(per.items())}
    refs = mean_refs(labels, build)
    res["references"] = sorted(f"{a}:{s}" for a, s in refs)
    if not refs:
        return res
    # Held out: the bound object against the other persistent candidates of its window,
    # and against the persistent near candidates of control windows.
    pick = Counter()
    kit_n = kit_hit = all_hit = 0
    tgt, neg, tgt_resp, neg_resp = [], [], [], []
    for L in labels:
        key = (L["agent"], L["slot"])
        if L["sid"] not in held or key not in refs:
            continue
        c0 = L["cand"]
        m = lambda c: cos(c["desc"], refs[key])
        tgt.append(m(c0))
        tgt_resp.append(c0["resp"])
        others = [c for c in persistent(L["win"]) if c is not c0]
        if others:
            pick["n"] += 1
            pick["mined"] += all(m(c0) > m(c) for c in others)
            pick["response"] += all(c0["resp"] > c["resp"] for c in others)
            pick["chance"] += 1.0 / (1 + len(others))
        kit = [k for k in refs if k[0] == L["agent"]]
        if len(kit) >= 2:
            kit_n += 1
            kit_hit += max(kit, key=lambda k: cos(c0["desc"], refs[k])) == key
            all_hit += max(refs, key=lambda k: cos(c0["desc"], refs[k])) == key
    for sid in held:
        for r in data[sid]["controls"]:
            for c in persistent(r):
                if c["d_self"] is not None and c["d_self"] <= NEAR_PX:
                    for k in refs:
                        if k[0] == agents[sid]:
                            neg.append(cos(c["desc"], refs[k]))
                            neg_resp.append(c["resp"])
    pick["chance"] = round(pick["chance"], 1)
    res["held_pick_in_window"] = dict(pick)
    res["held_kit"] = {"n": kit_n, "kit_correct": kit_hit, "all_refs_correct": all_hit}
    res["held_bound_vs_control_auc"] = {"mined": auc(tgt, neg), "response": auc(tgt_resp, neg_resp),
                                        "n": [len(tgt), len(neg)]}
    # Match threshold: 10th percentile of build labels' leave-one-session-out scores.
    loso = []
    for sid in build:
        r = mean_refs([L for L in labels if L["sid"] != sid], build, 1)
        for L in labels:
            if L["sid"] == sid and (L["agent"], L["slot"]) in r:
                loso.append(cos(L["cand"]["desc"], r[(L["agent"], L["slot"])]))
    tau = float(np.percentile(loso, 10)) if loso else 1.0
    res["tau"] = round(tau, 3)
    tr = Counter()
    for sid in held:
        named, maybe = lineup_sets(sid)
        own = agents[sid]
        foreign = [k for k in refs if k[0] != own]
        if not foreign:
            continue
        tr["sessions"] += 1
        tr["chance_in"] += sum(k[0] in named for k in foreign) / len(foreign)
        used = {id(bound(r)) for r in data[sid]["casts"] if bound(r) is not None}
        for w in data[sid]["casts"] + data[sid]["controls"]:
            for c in persistent(w):
                if id(c) in used:
                    continue
                tr["cands"] += 1
                sc = {k: cos(c["desc"], refs[k]) for k in refs}
                best = max(sc, key=sc.get)
                if sc[best] < tau:
                    continue
                tr["matched"] += 1
                tr["own" if best[0] == own else "in_lineup" if best[0] in named
                   else "absent" if best[0] not in maybe else "undecided"] += 1
    if tr["sessions"]:
        tr["chance_in"] = round(tr["chance_in"] / tr["sessions"], 3)
    res["transfer"] = dict(tr)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "evaluate"])
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "collect":
        for sid in a.sids or session_ids():
            f = a.work / f"{sid}.pkl"
            if f.exists():
                continue
            d = collect_session(sid)
            f.write_bytes(pickle.dumps(d))
            c = d["casts"]
            print(sid, d["agent"], len(c), dict(Counter(r["slot"] for r in c)),
                  "bound", sum(bound(r) is not None for r in c),
                  "ctrl_bound", sum(bound(r) is not None for r in d["controls"]), flush=True)
        return 0
    print(json.dumps(evaluate(a.work), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
