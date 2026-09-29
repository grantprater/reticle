r"""Stage 1 of the minimap object classifier: cross-reference the portrait gate's kept fits.

    .\.venv\Scripts\python.exe prototypes\minimap_objects.py --labels [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects.py --sample [--n 40] [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects.py --minimap-labels [--per-session 60] [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects.py --deaths [--record]

The design is docs/MINIMAP_OBJECTS_DESIGN.md. `icon_portrait_gate` (rule Bs)
keeps a teardrop fit as an agent icon where a portrait of its side's lineup
explains it; it still keeps red ping triangles, X death marks and the Wingman
glyph, whose portraits fit as well as real ones. A portrait fit alone cannot
reject them (docs/STATISTICAL_ADJUDICATOR.md, E6). Other channels already
observe those objects, so this stage asks them instead of tuning the gate:

    W1  the stored ping stream (`events/ping`, owner `ping`, ping-0.1.0): a
        fit coincides with a ping live at its time within PING_PX. Danger
        (red) pairs with the enemy key, standard (cyan) with the ally key.
        An enemy fit on a danger ping becomes `ping:danger`; an ally fit on a
        standard ping becomes `disputed`, because the ping owner measured
        ally icons as its main false positive (`reticle/ping.py`).
    W1b the ping owner's own rule (`ping.sightings`, `Grouper`, `resolve`)
        over the minimap crop cache for 12 s either side of the fit:
        whether the owner confirms, leaves unconfirmed or rejects a ping
        there. A diagnostic of the stream, never a verdict.
    W2  X marks at stored deaths: a death's place is the X that the owner's
        extractor (`adjudication.death.extract_minimap_death_marks`, blue for
        an ally death, red for an enemy one [domain:minimap/ally-death-mark]
        [domain:minimap/enemy-death-mark]) sees born at the death's killfeed
        time. A fit of the victim's side on such a place, in the same round,
        whose own frame still holds an X there, becomes `death_mark`.

Enemy "?" marks have no owner, and the domain fact that names them leaves
the marker unmeasured [domain:minimap/vision-trailing-persistence], so no
witness reads them. `--minimap-labels` only scores the gate against the
player's `?` marks in `labels/minimap`.

Adjudication is pure over stored observations and the crop cache: no video
is decoded, nothing is written to the store without `--record` (a `metrics`
row) or a sheet path. Every verdict keeps its alternatives and evidence. The
gate rests on the lineup prior; this stage adds no name and counts the
lineup once, through the gate. Unwired: `"wire": "no"` in the store's
`notes/predictions.jsonl` (task `minimap-objects-20260929`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_portrait_gate as gate_  # noqa: E402
import icon_teardrop as it_  # noqa: E402
from reticle import ping  # noqa: E402
from reticle.adjudication.death import extract_minimap_death_marks  # noqa: E402
from reticle.adjudication.identity import load_ally_portrait_references  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.version import PING_VERSION  # noqa: E402

VERSION = "minimap-objects-0.1.0"
STORE = gate_.STORE
OUT = STORE / "analysis" / "minimap-objects-20260929"
SESSIONS = gate_.LABELLED

#: A ping and a fit are one object within the ping owner's own grouping
#: distance (`ping.SAME_PX`), at the widget's scale.
PING_PX = float(ping.SAME_PX)
#: A stored ping is live from its first frame to first frame + its observed
#: lifetime; the slack covers the stream's 10 Hz sampling.
PING_SLACK_MS = 200.0
#: Which ping kinds each side's colour key can catch (`ping.PING_TYPES` hues:
#: danger 166-179 is the enemy red, standard 76-90 the ally teal).
PING_SIDE = {"danger": "enemy", "standard": "ally"}
#: W1b: the owner's rule over this much crop cache either side of a fit.
PING_WINDOW_MS = 12000.0

#: W2: the search around a death's killfeed time (the stored killfeed time is
#: a 0.5 s grid, and the entry is seen at or after the death).
X_WINDOW_MS = 3000.0
X_BORN_MS = (-2000.0, 1000.0)
X_PRESENT_MIN = 0.6
X_BEFORE_MAX = 0.2
X_BEFORE_GAP_MS = 300.0
X_CLUSTER_PX = 4.0
#: A fit is on an X when its teardrop centre lies this near the X's place:
#: half an X's span plus a fit's offset.
X_PX = 10.0
X_STRIDE = 2  # every second cached frame (about 7.5 Hz) in a death window

#: `--minimap-labels`: a kept fit and a player mark are one object within this.
MARK_PX = 8.0


def _cache_near(s, t: float) -> float | None:
    T = s.cache_t
    i = int(np.searchsorted(T, t))
    best = min((k for k in (i - 1, i) if 0 <= k < len(T)), key=lambda k: abs(T[k] - t), default=None)
    return None if best is None or abs(T[best] - t) > 70.0 else float(T[best])


# ------------------------------------------------------------------ W1 pings

def load_pings(sid: str) -> tuple[list[dict], str | None]:
    """The session's stored confirmed pings, each live over [t0, t1]."""
    p = STORE / "events" / "ping" / f"{sid}.jsonl"
    if not p.exists():
        return [], None
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for i, r in enumerate(rows):
        out.append({"i": i, "kind": r["kind"], "x": float(r["x"]), "y": float(r["y"]),
                    "t0": float(r["t_ms"]), "t1": float(r["t_ms"]) + 1000.0 * float(r["lifetime_s"]),
                    "hue": r.get("hue")})
    return out, (rows[0].get("ping_version") if rows else None)


def pings_at(pings: list[dict], t: float, x: float, y: float, sc: float) -> list[dict]:
    return [p for p in pings if p["t0"] - PING_SLACK_MS <= t <= p["t1"] + PING_SLACK_MS
            and math.hypot(p["x"] - x, p["y"] - y) <= PING_PX * sc]


def ping_owner_window(s, t: float, x: float, y: float) -> dict:
    """W1b: the ping owner's rule over the crop cache round `t`, for groups whose
    first sighting lies within PING_PX of (x, y). Lite carries no widget-drawn
    reference, so frames with the map closed are not refused here, as
    `PingReader` would with `sgray`."""
    T = [float(u) for u in s.cache_t if abs(u - t) <= PING_WINDOW_MS]
    if len(T) < 2:
        return {"status": "no_frames"}
    hz = 1000.0 / float(np.median(np.diff(T)))
    sc = None
    g = None
    ts = []
    for tt, crop in s.crops(T):
        if g is None:
            sc = widget_scale(crop.shape[1])
            g = ping.Grouper(hz, scale=sc)
        ts.append(tt / 1000.0)
        for px, py, hue in ping.sightings(crop, s.floor):
            g.add(tt / 1000.0, px, py, hue)
    conf, unconf, rej = ping.resolve(g, ts, hz)
    near = []
    for status, rows in (("confirmed", conf), ("unconfirmed", unconf), ("rejected", rej)):
        for kind, t0, t1, gx, gy, hue, n in rows:
            if math.hypot(gx - x, gy - y) <= PING_PX * sc and t0 <= t / 1000.0 + 0.2:
                near.append({"status": status, "kind": kind, "t0": round(t0, 2), "t1": round(t1, 2),
                             "life_s": round(n / hz, 1), "x": gx, "y": gy, "hue": hue})
    # Groups that never became a row (too few frames or an unnamed hue) stay out.
    return {"status": "read", "hz": round(hz, 2), "groups": near}


# ------------------------------------------------------------ W2 death marks

def load_deaths(sid: str) -> tuple[list[dict], str | None]:
    p = STORE / "events" / "death" / f"{sid}.jsonl"
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    ver = next((r.get("death_adjudication_version") for r in rows), None)
    return [r for r in rows if r.get("kind") == "death_verdict"], ver


def load_rounds(sid: str) -> list[dict]:
    st = Store(STORE)
    man = next(m for m in st.sessions() if m["session_id"] == sid)
    from reticle.cli import _date_of
    t = st.read_rounds(sid, _date_of(man))
    return t.to_pylist() if t is not None else []


def round_of(rounds: list[dict], t: float) -> int | None:
    for r in rounds:
        end = r.get("t_close_ms") if r.get("t_close_ms") is not None else r.get("t_end_ms")
        if r["t_start_ms"] <= t <= end:
            return int(r["round_no"])
    return None


def marks(crop: np.ndarray, floor: np.ndarray, side: str) -> list[tuple[int, float, float]]:
    blue, red = extract_minimap_death_marks(crop, floor)
    return blue if side == "ally" else red


def x_birth(s, death: dict, pings: list[dict]) -> dict:
    """W2 for one death: the X born at its killfeed time, as the owner's extractor
    sees it in the crop cache. Returns `placed` (one born X), `ambiguous`
    (several), `no_x_born` or `no_frames`, with every born cluster kept."""
    td, side = float(death["t_ms"]), death["side"]
    T = [float(u) for u in s.cache_t if abs(u - td) <= X_WINDOW_MS][::X_STRIDE]
    if len(T) < 6:
        return {"status": "no_frames", "places": []}
    frames = []
    sc = 1.0
    for tt, crop in s.crops(T):
        sc = widget_scale(crop.shape[1])
        frames.append((tt, [(a, x, y) for a, x, y in marks(crop, s.floor, side)]))
    clusters = []  # {"x","y","seen":[t]}
    for tt, blobs in frames:
        for a, x, y in blobs:
            c = next((c for c in clusters if math.hypot(c["x"] - x, c["y"] - y) <= X_CLUSTER_PX * sc), None)
            if c is None:
                clusters.append({"x": x, "y": y, "seen": [tt], "area": [a]})
            else:
                c["seen"].append(tt)
                c["area"].append(a)
    born = []
    for c in clusters:
        first = min(c["seen"])
        if not X_BORN_MS[0] <= first - td <= X_BORN_MS[1]:
            continue
        after = [tt for tt, _ in frames if tt >= first]
        before = [tt for tt, _ in frames if tt <= first - X_BEFORE_GAP_MS]
        seen = set(c["seen"])
        frac_after = sum(tt in seen for tt in after) / max(1, len(after))
        # A frame "before" holds the cluster if any blob of it lies at the place.
        frac_before = (sum(any(math.hypot(x - c["x"], y - c["y"]) <= X_CLUSTER_PX * sc for _a, x, y in b)
                           for tt, b in frames if tt <= first - X_BEFORE_GAP_MS) / len(before)) if before else 0.0
        if frac_after < X_PRESENT_MIN or frac_before > X_BEFORE_MAX:
            continue
        on_ping = [p["i"] for p in pings_at(pings, first, c["x"], c["y"], sc)]
        born.append({"x": round(float(c["x"]), 1), "y": round(float(c["y"]), 1),
                     "first_ms": first, "frac_after": round(frac_after, 2),
                     "frac_before": round(frac_before, 2), "area": int(np.median(c["area"])),
                     "on_ping": on_ping})
    places = [b for b in born if not b["on_ping"]]
    status = "placed" if len(places) == 1 else "ambiguous" if places else "no_x_born"
    return {"status": status, "places": places, "ping_excluded": [b for b in born if b["on_ping"]],
            "frames": len(frames), "scale": sc}


def death_places(s, pings: list[dict], deaths: list[dict]) -> list[dict]:
    out = []
    for d in deaths:
        w = x_birth(s, d, pings)
        out.append({"death_id": d["death_id"], "t_ms": float(d["t_ms"]), "side": d["side"],
                    "round_no": d.get("round_no"), "victim": d.get("victim"),
                    "death_cause": d.get("death_cause"), **w})
    return out


def on_death_mark(row: dict, crop: np.ndarray, floor: np.ndarray, places: list[dict],
                  rnd: int | None, sc: float) -> list[dict]:
    """W2 for one fit: same-side deaths of its round, before it, whose born X
    lies at the fit and whose X its own frame still shows."""
    here = marks(crop, floor, row["side"])
    hits = []
    for d in places:
        if d["side"] != row["side"] or d["status"] not in ("placed", "ambiguous"):
            continue
        if rnd is None or d["round_no"] != rnd or d["t_ms"] > row["t_ms"] + 500.0:
            continue
        for p in d["places"]:
            if math.hypot(p["x"] - row["x"], p["y"] - row["y"]) > X_PX * sc:
                continue
            if any(math.hypot(x - p["x"], y - p["y"]) <= X_PX * sc for _a, x, y in here):
                hits.append({"death_id": d["death_id"], "x": p["x"], "y": p["y"],
                             "death_t_ms": d["t_ms"], "place_status": d["status"]})
    return hits


# ----------------------------------------------------------------- verdicts

def stage1_verdict(row: dict, w1: list[dict], w2: list[dict]) -> dict:
    """The stage-1 class of one teardrop fit, its alternatives and why.

    The gate's Bs says agent icon or not; W1 and W2 name what else the fit may
    be. A witness that names the object overrules the gate's keep only where
    its colour matches the fit's key and the ping owner is not known to take
    that side's icons for pings."""
    side = row["side"]
    icon = f"agent_icon:{side}"
    kept = bool(row.get("Bs"))
    pk = [p for p in w1 if PING_SIDE.get(p["kind"]) == side]
    mismatch = [p for p in w1 if PING_SIDE.get(p["kind"]) != side]
    named = []
    if w2:
        named.append("death_mark")
    if pk:
        named.append(f"ping:{pk[0]['kind']}")
    if len(named) > 1:
        return {"class": "disputed", "alternatives": named + ([icon] if kept else []),
                "reason": "ping_and_death_mark", "mismatch": mismatch}
    if named == ["death_mark"]:
        return {"class": "death_mark", "alternatives": [icon] if kept else [],
                "reason": "x_born_at_same_side_death", "mismatch": mismatch}
    if named and side == "enemy":
        return {"class": named[0], "alternatives": [icon] if kept else [],
                "reason": "danger_ping_live_here", "mismatch": mismatch}
    if named:  # an ally fit on a standard ping
        return {"class": "disputed" if kept else named[0],
                "alternatives": [icon, named[0]] if kept else [icon],
                "reason": "ping_owner_takes_ally_icons" if kept else "gate_rejected_and_ping_live",
                "mismatch": mismatch}
    if kept:
        return {"class": icon, "alternatives": [], "reason": None, "mismatch": mismatch}
    return {"class": "unknown", "alternatives": [], "reason": row.get("why") or "portrait_gate_rejected",
            "mismatch": mismatch}


def cross(rows: list[dict], lites: dict, pings: dict, places: dict, rounds: dict,
          owner_window: bool = True) -> None:
    """Attach W1, W1b and W2 and the verdict to each gate row, in place."""
    for r in rows:
        s, crop = lites[r["session"]], r["_crop"]
        sc = widget_scale(crop.shape[1])
        w1 = pings_at(pings[r["session"]], r["t_ms"], r["x"], r["y"], sc)
        rnd = round_of(rounds[r["session"]], r["t_ms"])
        w2 = on_death_mark(r, crop, s.floor, places[r["session"]], rnd, sc)
        r["round_no"] = rnd
        r["w1_pings"] = w1
        r["w2_marks"] = w2
        sighted = any(math.hypot(px - r["x"], py - r["y"]) <= PING_PX * sc
                      for px, py, _h in ping.sightings(crop, s.floor))
        r["ping_sighted"] = sighted
        if owner_window and (r["side"] == "enemy" or sighted):
            r["w1b"] = ping_owner_window(s, r["t_ms"], r["x"], r["y"])
        r.update({f"v_{k}": v for k, v in stage1_verdict(r, w1, w2).items()})


# ------------------------------------------------------------ labels/minimap

def minimap_label_rows(per_session: int, cal: dict) -> list[dict]:
    """The gate at every enemy detection of labels/minimap frames that hold a
    player `?` or other-red mark, each detection matched to a mark within
    MARK_PX. Mirrors `icon_portrait_gate.label_rows` per detection."""
    refs = load_ally_portrait_references(STORE)
    out = []
    for sid in SESSIONS:
        s = gate_.Lite(sid)
        sp = gate_.SpikeRows(sid)
        names, why = gate_.side_gallery(load_lineup(sid, STORE), "enemy")
        p = STORE / "labels" / "minimap" / f"{sid}.jsonl"
        last = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[(r["t_ms"])] = r  # last row for a frame wins
        frames = [r for r in last.values() if not r.get("uncertain")
                  and any(m["kind"] in ("question", "other_red") for m in r.get("marks", []))
                  and list(r.get("roi", [])) == list(s.box)]
        frames.sort(key=lambda r: r["t_ms"])
        if len(frames) > per_session:
            frames = [frames[i] for i in np.linspace(0, len(frames) - 1, per_session).astype(int)]
        snap = {r["t_ms"]: _cache_near(s, float(r["t_ms"])) for r in frames}
        crops = dict(s.crops(sorted({v for v in snap.values() if v is not None})))
        for fr in frames:
            tc = snap[fr["t_ms"]]
            if tc is None:
                continue
            crop = crops[tc]
            sc = widget_scale(crop.shape[1])
            key = it_.CLASSES["enemy"].key(crop)
            used = set()
            for d in it_.detections(crop, "enemy", s):
                f = it_.fit(None, "enemy", d["cx"], d["cy"], key=key)
                x, y = (f["x"], f["y"]) if "x" in f else (d["cx"], d["cy"])
                ms = sorted(((math.hypot(m["x"] - x, m["y"] - y), i, m) for i, m in enumerate(fr["marks"])),
                            key=lambda z: z[0])
                m = ms[0] if ms and ms[0][0] <= MARK_PX * sc else None
                if m is not None:
                    used.add(m[1])
                row = {"session": sid, "t_ms": tc, "label_t_ms": fr["t_ms"], "side": "enemy",
                       "x": round(x, 2), "y": round(y, 2), "deg": f.get("deg"),
                       "teardrop_read": bool(f.get("read")),
                       "mark": m[2]["kind"] if m else "unmarked", "rests_on": "lineup",
                       "gallery": len(names), "gallery_reason": why}
                fl = gate_.spike_flags(sp.at(tc), d["cx"], d["cy"], sc)
                row.update({f"spike_{k}": v for k, v in fl.items()})
                row.update(gate_.gate(gate_.features_at(crop, x, y), names, refs, cal["b_max"],
                                      cal.get("bt_max"), cal.get("bs_max"), fl["carrier"]))
                row["_crop"] = crop
                out.append(row)
            for i, m in enumerate(fr["marks"]):
                if i not in used:
                    out.append({"session": sid, "t_ms": tc, "label_t_ms": fr["t_ms"], "side": "enemy",
                                "x": float(m["x"]), "y": float(m["y"]), "mark": m["kind"],
                                "undetected": True, "_crop": crop})
        print(sid, "minimap labels done", flush=True)
    return out


# ------------------------------------------------------------------- sheets

def tile(r: dict, K: int = 24, Z: int = 5) -> np.ndarray:
    crop = r["_crop"]
    x0, y0 = int(round(r["x"])) - K, int(round(r["y"])) - K
    pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
    big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                     interpolation=cv2.INTER_NEAREST)

    def P(x, y):
        return int(round((x - x0 + 0.5) * Z)), int(round((y - y0 + 0.5) * Z))
    col = (0, 220, 0) if r.get("Bs") else (0, 0, 230)
    cv2.circle(big, P(r["x"], r["y"]), int(10.5 * Z), col, 1)
    for p in r.get("w1_pings", []):
        cx, cy = P(p["x"], p["y"])
        cv2.drawMarker(big, (cx, cy), (255, 255, 0), cv2.MARKER_CROSS, 18, 2)
    for m in r.get("w2_marks", []):
        cv2.circle(big, P(m["x"], m["y"]), 4 * Z, (255, 0, 255), 2)
    top = f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r['side'][0]}"
    if r.get("class"):
        top += f" {r['class'][:10]}"
    if r.get("mark"):
        top += f" [{r['mark']}]"
    fs = "-" if r.get("fit_side") is None else f"{r['fit_side']:.2f}"
    line2 = f"fit {fs} Bs{'+' if r.get('Bs') else '-'}"
    w1b = r.get("w1b") or {}
    if w1b.get("groups"):
        g0 = w1b["groups"][0]
        line2 += f" own:{g0['status'][:5]} {g0['kind'][:6]} {g0['life_s']}s"
    line3 = f"-> {r.get('v_class', '?')}"
    if r.get("v_reason"):
        line3 += f" ({r['v_reason'][:22]})"
    for i, text in enumerate((top, line2, line3)):
        cv2.putText(big, text, (3, 14 + 15 * i), 0, 0.42, (0, 0, 0), 3)
        cv2.putText(big, text, (3, 14 + 15 * i), 0, 0.42, (255, 255, 255), 1)
    return big


def write_sheet(path: Path, rows: list[dict], cols: int = 6, limit: int = 72) -> None:
    rows = rows[:limit]
    if not rows:
        print("nothing for", path)
        return
    tiles = [tile(r) for r in rows]
    blank = np.zeros_like(tiles[0])
    grid = [np.hstack(tiles[i:i + cols] + [blank] * (cols - len(tiles[i:i + cols])))
            for i in range(0, len(tiles), cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(grid))
    print("wrote", path, len(rows), "tiles")


def death_sheet(path: Path, s, placed: list[dict], limit: int = 36) -> None:
    """Each placed death's X at 1 s after its birth, ringed, for looking."""
    rows = []
    want = {}
    for d in placed[:limit]:
        t = _cache_near(s, d["places"][0]["first_ms"] + 1000.0) or d["places"][0]["first_ms"]
        want.setdefault(t, []).append(d)
    crops = dict(s.crops(sorted(want)))
    for t, ds in want.items():
        for d in ds:
            p = d["places"][0]
            rows.append({"session": s.sid, "t_ms": t, "side": d["side"], "x": p["x"], "y": p["y"],
                         "Bs": True, "class": f"r{d['round_no']} {d['death_cause'] or ''}",
                         "v_class": f"X of {d['victim']}", "w2_marks": [p], "_crop": crops[t]})
    rows.sort(key=lambda r: r["t_ms"])
    write_sheet(path, rows, limit=limit)


# --------------------------------------------------------------------- main

def _inputs() -> tuple[dict, dict, dict, dict, dict]:
    lites, pings, rounds, deaths, vers = {}, {}, {}, {}, {}
    for sid in SESSIONS:
        lites[sid] = gate_.Lite(sid)
        pings[sid], pv = load_pings(sid)
        deaths[sid], dv = load_deaths(sid)
        rounds[sid] = load_rounds(sid)
        vers[sid] = {"ping": pv, "death": dv}
    return lites, pings, rounds, deaths, vers


def _places(lites, pings, deaths, cache: Path) -> dict:
    """W2 for every stored death, cached as JSON beside the sheets (a
    recomputation from stored data; delete the file to rebuild)."""
    if cache.exists():
        got = json.loads(cache.read_text(encoding="utf-8"))
        if got.get("version") == VERSION:
            return got["places"]
    places = {}
    for sid in SESSIONS:
        places[sid] = death_places(lites[sid], pings[sid], deaths[sid])
        print(sid, "death places", Counter(d["status"] for d in places[sid]), flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"version": VERSION, "places": places}, indent=1), encoding="utf-8")
    return places


def death_table(places: dict) -> dict:
    out = {}
    for sid, ds in places.items():
        for side in ("ally", "enemy"):
            sub = [d for d in ds if d["side"] == side]
            c = Counter(d["status"] for d in sub)
            n = max(1, len(sub))
            out[f"{sid}/{side}"] = {"n": len(sub), **{k: c.get(k, 0) for k in
                                    ("placed", "ambiguous", "no_x_born", "no_frames")},
                                    "placed_frac": round(c.get("placed", 0) / n, 3),
                                    "ambiguous_frac": round(c.get("ambiguous", 0) / n, 3)}
    return out


def _deps(cal: dict, vers: dict) -> dict:
    return {"prototype": VERSION, "gate": gate_.VERSION, "teardrop": it_.VERSION,
            "bs_max": cal.get("bs_max"), "ping": PING_VERSION,
            "ping_stored": sorted({str(v["ping"]) for v in vers.values()}),
            "death": sorted({str(v["death"]) for v in vers.values()}),
            "ping_px": PING_PX, "x_px": X_PX, "x_born_ms": list(X_BORN_MS), "rests_on": "lineup"}


def _strip(rows):
    return [{k: v for k, v in r.items() if k != "_crop"} for r in rows]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", action="store_true", help="the icon_facing labels")
    ap.add_argument("--sample", action="store_true", help="the gate's Lotus and Ascent sample")
    ap.add_argument("--minimap-labels", action="store_true", help="labels/minimap frames with ? or other-red marks")
    ap.add_argument("--deaths", action="store_true", help="W2 coverage over every stored death")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--per-session", type=int, default=60)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    gate_._idle()
    from reticle import metrics
    cal = gate_.load_calibration()
    lites, pings, rounds, deaths, vers = _inputs()
    places = _places(lites, pings, deaths, OUT / "death_places.json")
    OUT.mkdir(parents=True, exist_ok=True)
    session = "+".join(SESSIONS)

    if args.deaths:
        tab = death_table(places)
        for k, v in tab.items():
            print(k, v)
        for sid in SESSIONS:
            placed = [d for d in places[sid] if d["status"] == "placed"]
            death_sheet(OUT / f"death_x_{sid}.png", lites[sid], placed)
            miss = [d for d in places[sid] if d["status"] == "no_x_born"]
            print(sid, "no_x_born by side and cause:",
                  dict(Counter((d["side"], d["death_cause"]) for d in miss)))
        if args.record:
            for sid in SESSIONS:
                values = {}
                for side in ("ally", "enemy"):
                    for k, v in tab[f"{sid}/{side}"].items():
                        values[f"{side}_{k}"] = v
                metrics.record("minimap_objects", part="deaths", session=sid, values=values,
                               deps=_deps(cal, vers),
                               context={"capture": lites[sid].capture},
                               note="W2: an X born at each stored death's killfeed time, by side")
        return 0

    if args.labels:
        rows = gate_.label_rows(cal["b_max"], cal.get("bt_max"), cal.get("bs_max"))
        cross(rows, lites, pings, places, rounds)
        tab = Counter((r["side"], r["class"], r["v_class"]) for r in rows)
        for k in sorted(tab):
            print(k, tab[k])
        for r in rows:
            if r["class"] != "true_icon" or r["v_class"] != f"agent_icon:{r['side']}":
                print(" ", r["key"], r["class"], "Bs", r["Bs"], "->", r["v_class"], r["v_reason"],
                      "w1", [(p["kind"], p["i"]) for p in r["w1_pings"]],
                      "w2", [m["death_id"] for m in r["w2_marks"]],
                      "w1b", (r.get("w1b") or {}).get("groups"))
        order = {c: i for i, c in enumerate(gate_.CLASSES_ORDER)}
        sheet = sorted([r for r in rows if r["class"] != "true_icon"
                        or r["v_class"] != f"agent_icon:{r['side']}"],
                       key=lambda r: (r["side"], order.get(r["class"], 9), r["t_ms"]))
        write_sheet(OUT / "labels_sheet.png", sheet)
        (OUT / "labels_rows.json").write_text(json.dumps(_strip(rows), indent=1, default=str),
                                              encoding="utf-8")
        if args.record:
            values = {}
            for side in ("ally", "enemy"):
                for c in gate_.CLASSES_ORDER:
                    sub = [r for r in rows if r["side"] == side and r["class"] == c]
                    if not sub:
                        continue
                    values[f"{side}_{c}_n"] = len(sub)
                    values[f"{side}_{c}_kept_Bs"] = sum(bool(r["Bs"]) for r in sub)
                    values[f"{side}_{c}_icon"] = sum(r["v_class"] == f"agent_icon:{side}" for r in sub)
                    for v in ("death_mark", "ping:danger", "disputed", "unknown"):
                        values[f"{side}_{c}_{v.replace(':', '_')}"] = sum(r["v_class"] == v for r in sub)
            metrics.record("minimap_objects", part="labels", session=session, values=values,
                           deps=_deps(cal, vers) | {"labels": "icon_facing_20260928.jsonl"},
                           note="stage-1 verdicts of the labelled teardrop items, per side and class")
        return 0

    if args.sample:
        rows, meta = gate_.sample_rows(args.n, cal["b_max"], cal.get("bt_max"), SESSIONS, cal.get("bs_max"))
        cross(rows, lites, pings, places, rounds)
        tab = Counter((r["session"], r["side"], r["v_class"]) for r in rows)
        for k in sorted(tab):
            print(k, tab[k])
        odd = [r for r in rows if r["v_class"] != f"agent_icon:{r['side']}" or r["side"] == "enemy"]
        for r in odd:
            print(" ", r["session"], round(r["t_ms"] / 1000, 1), r["side"], (r["x"], r["y"]), "Bs", r["Bs"],
                  "->", r["v_class"], r["v_reason"], "w1b", (r.get("w1b") or {}).get("groups"))
        write_sheet(OUT / "sample_sheet.png", sorted(odd, key=lambda r: (r["side"], r["session"], r["t_ms"])))
        (OUT / "sample_rows.json").write_text(json.dumps(_strip(rows), indent=1, default=str),
                                              encoding="utf-8")
        if args.record:
            for sid in SESSIONS:
                values = {}
                for side in ("ally", "enemy"):
                    sub = [r for r in rows if r["session"] == sid and r["side"] == side]
                    values[f"{side}_read"] = len(sub)
                    values[f"{side}_kept_Bs"] = sum(bool(r["Bs"]) for r in sub)
                    for v in (f"agent_icon:{side}", "death_mark", "ping:danger", "ping:standard",
                              "disputed", "unknown"):
                        values[f"{side}_{v.replace(':', '_')}"] = sum(r["v_class"] == v for r in sub)
                metrics.record("minimap_objects", part="sample", session=sid, values=values,
                               deps=_deps(cal, vers) | {"n": args.n},
                               context={"capture": lites[sid].capture},
                               note="stage-1 verdicts of the gate's teardrop-read fits, unlabelled frames")
        return 0

    if args.minimap_labels:
        rows = minimap_label_rows(args.per_session, cal)
        det = [r for r in rows if not r.get("undetected")]
        cross(det, lites, pings, places, rounds, owner_window=False)
        tab = Counter((r["mark"], "undetected" if r.get("undetected") else
                       ("kept" if r.get("Bs") else "rejected")) for r in rows)
        for k in sorted(tab):
            print(k, tab[k])
        vt = Counter((r["mark"], r["v_class"]) for r in det if r.get("Bs"))
        for k in sorted(vt):
            print(" kept", k, vt[k])
        sheet = [r for r in det if r["mark"] in ("question", "other_red") and r.get("Bs")]
        sheet += [r for r in det if r["mark"] == "question" and not r.get("Bs")][:12]
        write_sheet(OUT / "minimap_labels_sheet.png", sorted(sheet, key=lambda r: (r["mark"], r["t_ms"])))
        (OUT / "minimap_labels_rows.json").write_text(json.dumps(_strip(rows), indent=1, default=str),
                                                      encoding="utf-8")
        if args.record:
            values = {}
            for mk in ("enemy", "question", "other_red", "unmarked"):
                sub = [r for r in rows if r["mark"] == mk]
                values[f"{mk}_n"] = len(sub)
                values[f"{mk}_detected"] = sum(not r.get("undetected") for r in sub)
                values[f"{mk}_kept_Bs"] = sum(bool(r.get("Bs")) for r in sub)
                kept = [r for r in sub if r.get("Bs") and not r.get("undetected")]
                for v in ("death_mark", "ping:danger", "disputed"):
                    values[f"{mk}_kept_{v.replace(':', '_')}"] = sum(r["v_class"] == v for r in kept)
            metrics.record("minimap_objects", part="minimap-labels", session=session, values=values,
                           deps=_deps(cal, vers) | {"labels": "labels/minimap", "per_session": args.per_session},
                           note="the gate and W1/W2 at enemy detections of labels/minimap frames with ? or other-red marks")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
