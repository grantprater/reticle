r"""Stage 3 of docs/MINIMAP_GLYPH_CHANNEL.md, measured: the tracks and the glyph verdict on stored rows.

    .\.venv\Scripts\python.exe prototypes\glyph_stage3_eval.py matches --out DIR --before FILE [--stale-tray] SID...  (P4, P5, G6, G7, T1, V1, C1, I1)
    .\.venv\Scripts\python.exe prototypes\glyph_stage3_eval.py marks --out DIR       (A1, P6: the labelled dev and held-out marks)
    .\.venv\Scripts\python.exe prototypes\glyph_stage3_eval.py montage --out DIR SID --what pending|named|thrown [--n 24]
    .\.venv\Scripts\python.exe prototypes\glyph_stage3_eval.py record --out DIR      (glyph_stage3/* metric series, once)

Wire: no. It scores the production verdict (`reticle.adjudication.ability_glyph`, stage 3's owner of
`ability-glyph-name`) and never decides anything the pipeline reads. The predictions it tests are the store's
`notes/predictions.jsonl` row `glyph-stage3-20261005`, logged before any of these ran.

`matches` reads what `reticle ability-glyphs <sid>` wrote (`ability_disc_track`, `ability_glyph_name`) beside the
stored `round_entity` fixes, `ally_icon` self icon, `tray_drop` rows and the player-cast gate's inputs
(`ability_timeline.stored_gate_inputs`, as `reticle smokes` reads them). Gate 6 crosses the glyph claim with two
other channels and stores every disagreement (`g6_disagreements.jsonl`): the ally fragment a track is born at
(a resolved ally `round_entity` fix within BIRTH_MS_ALLY and BIRTH_R px x scale of the birth) and the player's tray
drop (a player cast of a slot whose key a minimap component draws, the birth within THROWN_MS after it and within
BIRTH_R px x scale of the self icon). Agreement is consistency, not accuracy. `T1` counts the births after the
player's glyph casts that the verify kept for one fix only (the thrown icon's track at 2 Hz).

`marks` runs the ability pass's two readers in memory over the minimap crop cache (no decode, nothing written to
the store's streams) at 2 Hz on windows of [-4 s, +1 s] about each labelled mark, then the verdict on those rows,
and scores the track under each mark. The marks are the eval 0.3.0 dev glyph items (59) and the stage 2 held-out
marks (`labels/minimap_glyph_heldout`, the last row per item, marks named Agent:Slot and sure; the dev sessions'
marks reported apart). No lineup is stored for a demo, so the context set is the session agent's kit (the queue's
and the eval's `agent`): the context path's agent is wrong only on a mark of another agent's ability. The audit
path (every kit, every rotation) is the every-kit arm. Neither is gate 4's fresh set; both were seen by stage 1 or
stage 2.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import glyph_channel_cost as gcc  # noqa: E402  (sets single-threaded, Below Normal)
import numpy as np  # noqa: E402

VERSION = "glyph-stage3-eval-0.1.0"
STORE = Path(gcc.mge.STORE)
BIRTH_R = 34.0          # px x scale: 2 x OCC_R, the crowding radius of cross-channel-independence and S5
BIRTH_MS_ALLY = 250.0   # an ally fix this close in time to a birth stands for the caster at the birth
THROWN_MS = 1500.0      # S5's BIRTH_MS: a thrown icon is born within 1.5 s of the tray drop (a design guess)
MARK_MS = 250.0         # a fix this close in time to a mark is the mark's sample at 2 Hz
MARK_R = 8.0            # px x scale: the held-out snap radius (glyph_reader/heldout_050)
WINDOW_MS = (-4000.0, 1000.0)
VOID_CORNER = (21.0, 91.0)  # 4f207c0c4e39's void-corner disc (stage 2)


def wilson95(k: int, n: int) -> list:
    """`metrics.wilson`, rounded to 4 places; [None, None] when nothing was tried."""
    from reticle.metrics import wilson
    return [None, None] if n == 0 else [round(x, 4) for x in wilson(k, n)]


def fresh(p: Path) -> Path:
    if p.exists():
        raise SystemExit(f"{p} exists; write to a new --out")
    return p


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if p.is_file() else []


# ------------------------------------------------------------------ matches


def ally_fixes(store, sid: str) -> dict:
    """Resolved ally round_entity fixes: t, x, y, agent."""
    ents, obs = {}, []
    for r in read_jsonl(store.events_path("round_entity", sid)):
        if r.get("kind") == "entity" and r.get("family") == "ally" and r.get("agent") \
                and r.get("identity_status") == "resolved":
            ents[r["id"]] = r["agent"]
        elif r.get("kind") == "observation" and r.get("family") == "ally":
            obs.append((r["t_ms"], r["x"], r["y"], r["entity_id"]))
    keep = [(t, x, y, ents[e]) for t, x, y, e in obs if e in ents]
    return {"t": np.array([k[0] for k in keep], float), "x": np.array([k[1] for k in keep], float),
            "y": np.array([k[2] for k in keep], float), "agent": np.array([k[3] for k in keep], object)}


def self_fixes(store, sid: str) -> dict:
    t, x, y = [], [], []
    for r in read_jsonl(store.events_path("ally_icon", sid)):
        if r.get("kind") == "frame" and r.get("self") and len(r["self"]) >= 2:
            t.append(r["t_ms"]); x.append(r["self"][0]); y.append(r["self"][1])
    o = np.argsort(t)
    return {"t": np.array(t, float)[o], "x": np.array(x, float)[o], "y": np.array(y, float)[o]}


def player_casts(store, sid: str, player: str | None, stale_ok: bool = False) -> tuple[list[dict], str | None]:
    """The player's tray casts as `ability_timeline.player_tray_casts` decides them (as `reticle smokes`).
    `stale_ok` reads drops written at an older tray stamp (an evaluation's choice, stated in its output:
    tray-0.2.0 adds drops a half going empty shows, so older drops are a subset)."""
    from reticle.ability_timeline import player_tray_casts, stored_gate_inputs
    from reticle.adjudication.ult_cast import DROP_FIELDS
    from reticle.version import TRAY_VERSION
    if player is None:
        return [], "no_player_agent"
    drops = store.read_events("tray_drop", sid)
    if not drops:
        return [], "no_tray_drops"
    if drops[0].get("tray_version") != TRAY_VERSION and not stale_ok:
        return [], f"tray_drops_stale {drops[0].get('tray_version')}"
    man = store.read_manifest(sid)
    date = man["ingested_at"][:10]
    table = store.read_rounds(sid, date)
    rounds = table.to_pylist() if table is not None else []
    gate, _ = stored_gate_inputs(store, sid, date, rounds, player)
    d = [{k: r[k] for k in DROP_FIELDS if k in r} for r in drops if r.get("kind") == "drop"]
    stamp = drops[0].get("tray_version")
    return ([c for c in player_tray_casts(d, rounds=rounds, **gate) if c.get("player_cast")],
            None if stamp == TRAY_VERSION else f"read stale drops {stamp} (current {TRAY_VERSION})")


def drawn_keys() -> set:
    """Keys a minimap component draws (the policy table's rows not decided by `no_component_default`)."""
    from reticle.minimap_glyph import GLYPH_DATA
    pdir, pver = GLYPH_DATA["policy"]
    pol = json.loads((STORE / pdir / f"{pver}.json").read_text(encoding="utf-8"))
    return {r["key"] for r in pol["rows"] if r.get("decided_by") != "no_component_default"}


def session_matches(store, sid: str, stale_tray: bool = False) -> tuple[dict, list[dict]]:
    from reticle.adjudication.ult_cast import player_agent
    from reticle.lineup import load_lineup
    names = read_jsonl(store.events_path("ability_glyph_name", sid))
    tracks = {r["track"]: r for r in read_jsonl(store.events_path("ability_disc_track", sid))
              if r.get("kind") == "track"}
    cov = names[0]
    rows = names[1:]
    clean = [r for r in rows if r["samples"]["clean"]]
    out = {"tracks": cov["tracks"], "with_clean_sample": len(clean), "wall_s_command": cov.get("wall_s_command"),
           "refused": cov["refused"], "refused_with_clean_sample": cov["refused_with_clean_sample"],
           "named": cov["named"], "pending": cov["pending"], "kit_clear": cov["kit_clear"],
           "agents_named": cov["agents_named"], "claims": cov["claims"], "claims_named": cov["claims_named"]}
    bn = sum(r["reason"] == "below_null" for r in clean)
    out["P4"] = {"below_null": bn, "n": len(clean), "share": round(bn / len(clean), 4) if clean else None,
                 "wilson95": wilson95(bn, len(clean)), "omen_tracks": sum(bool(r["omen_rule"]) for r in rows),
                 "omen_rule_applied": sum(bool(r["omen_rule"] and r["omen_rule"]["applied"]) for r in rows)}
    a_rows = [r for r in rows if r["audit"]]
    both = [r for r in a_rows if r["audit"]["named"] and r["ability"]]
    agree = sum(r["audit"]["best"] == r["ability"]["key"] for r in both)
    out["P5"] = {"audit_tracks": len(a_rows), "both_named": len(both), "agree": agree,
                 "wilson95": wilson95(agree, len(both)),
                 "audit_only": sum(r["audit"]["named"] and not r["ability"] for r in a_rows),
                 "context_only": sum(not r["audit"]["named"] and bool(r["ability"]) for r in a_rows),
                 "audit_reasons": dict(Counter(r["audit"]["reason"] for r in a_rows if not r["audit"]["named"]))}
    # V1: named tracks keep their map_shown samples inside them.
    named = [r for r in rows if r["ability"] or r["pending"]]
    with_ms = [r for r in named if "map_shown" in (tracks[r["track"]]["fix"]["reason"] or [])]
    inner = 0
    for r in with_ms:
        rs = tracks[r["track"]]["fix"]["reason"]
        clean_ix = [i for i, x in enumerate(rs) if x is None]
        ms_ix = [i for i, x in enumerate(rs) if x == "map_shown"]
        inner += any(clean_ix[0] < i < clean_ix[-1] for i in ms_ix) if clean_ix else 0
    out["V1"] = {"named": len(named), "named_with_map_shown_sample": len(with_ms),
                 "map_shown_between_clean_samples": inner,
                 "map_shown_max_on_named": max([r["map_shown"]["max"] or 0 for r in named], default=None)}
    # C1: the void corner.
    corner = [t for t in tracks.values()
              if np.any(np.hypot(np.array(t["fix"]["cx"]) - VOID_CORNER[0],
                                 np.array(t["fix"]["cy"]) - VOID_CORNER[1]) <= 4.0)]
    by_t = {r["track"]: r for r in rows}
    out["C1"] = {"tracks": len(corner),
                 "reasons": dict(Counter(by_t[t["track"]]["reason"] for t in corner)),
                 "named": sum(bool(by_t[t["track"]]["ability"] or by_t[t["track"]]["pending"]) for t in corner),
                 "fix_reasons": dict(Counter(x for t in corner for x in t["fix"]["reason"]))}
    # Gate 6 and T1.
    lineup = load_lineup(sid, STORE)
    player = player_agent(lineup, sid)
    allies = ally_fixes(store, sid)
    selfs = self_fixes(store, sid)
    casts, cast_why = player_casts(store, sid, player, stale_tray)
    drawn = drawn_keys()
    dis = []
    g6a = Counter()
    for r in rows:
        if not r["agent"]:
            continue
        t = tracks[r["track"]]
        tb, (bx, by), sc = t["birth_ms"], t["birth_xy"], t["scale"]
        near = (np.abs(allies["t"] - tb) <= BIRTH_MS_ALLY) & \
               (np.hypot(allies["x"] - bx, allies["y"] - by) <= BIRTH_R * sc)
        ag = sorted({str(a).replace("/", "_") for a in allies["agent"][near]})
        if not ag:
            g6a["no_fragment"] += 1
            continue
        if len(ag) > 1:
            g6a["ambiguous"] += 1
            continue
        same = ag[0] == str(r["agent"]).replace("/", "_")
        g6a["agree" if same else "disagree"] += 1
        if not same:
            dis.append({"session": sid, "kind": "ally_fragment", "track": r["track"], "birth_ms": tb,
                        "claim": r["agent"], "key": (r["ability"] or {}).get("key") or r["best"],
                        "fragment": ag[0], "rests_on": ["round_entity", "ability_glyph_name"]})
    g6t, t1 = Counter(), Counter()
    tl = [tracks[k] for k in tracks]
    bt = np.array([t["birth_ms"] for t in tl], float)
    for c in casts:
        key = f"{player}:{c['slot']}"
        if key.replace("_", "/") not in drawn and key not in drawn:
            continue
        t0 = float(c["t_ms"])
        js = np.flatnonzero((bt >= t0) & (bt <= t0 + THROWN_MS))
        g6t["casts"] += 1
        hit = False
        for j in js:
            t = tl[j]
            k = np.searchsorted(selfs["t"], t["birth_ms"])
            cand = [i for i in (k - 1, k) if 0 <= i < len(selfs["t"])
                    and abs(selfs["t"][i] - t["birth_ms"]) <= BIRTH_MS_ALLY]
            if not cand:
                continue
            i = min(cand, key=lambda i: abs(selfs["t"][i] - t["birth_ms"]))
            if math.hypot(selfs["x"][i] - t["birth_xy"][0], selfs["y"][i] - t["birth_xy"][1]) > BIRTH_R * t["scale"]:
                continue
            hit = True
            t1["births"] += 1
            t1["single_fix"] += t["fixes"] == 1
            t1["gated_at_birth"] += t["fix"]["reason"][0] is not None
            v = by_t[t["track"]]
            got = (v["ability"] or {}).get("key") or (v["best"] if v["kit_clear"] else None)
            if got is None:
                g6t["unnamed"] += 1
                continue
            same_slot = got.split(":")[1] == c["slot"] and got.split(":")[0].replace("/", "_") == player
            g6t["agree" if same_slot else "disagree"] += 1
            if not same_slot:
                dis.append({"session": sid, "kind": "tray_drop", "track": t["track"], "birth_ms": t["birth_ms"],
                            "claim_key": got, "drop": f"{sid}:tray_drop:{c['slot']}:{int(round(t0))}",
                            "drop_key": key, "rests_on": ["tray_drop", "ability_glyph_name"]})
        g6t["casts_with_birth"] += hit
    out["G6"] = {"ally_fragment": dict(g6a), "tray_drop": dict(g6t), "player": player, "casts_reason": cast_why,
                 "ally_agree_wilson95": wilson95(g6a["agree"], g6a["agree"] + g6a["disagree"]),
                 "tray_agree_wilson95": wilson95(g6t["agree"], g6t["agree"] + g6t["disagree"])}
    out["T1"] = {**dict(t1), "single_fix_share": round(t1["single_fix"] / t1["births"], 4) if t1["births"] else None,
                 "wilson95": wilson95(t1["single_fix"], t1["births"])}
    # Single-fix tracks overall, and births by end reason, for the thrown-icon question.
    out["tracks_overall"] = {"single_fix": sum(t["fixes"] == 1 for t in tl),
                             "single_fix_clean": sum(t["fixes"] == 1 and t["scored_fixes"] == 1 for t in tl),
                             "jumps": sum(bool(t["jumps"]) for t in tl)}
    out["named_keys"] = dict(Counter((r["ability"] or {}).get("key") for r in rows if r["ability"]).most_common())
    out["agents"] = dict(Counter(r["agent"] for r in rows if r["agent"]).most_common())
    return out, dis


def identity_check(before: dict, sid: str) -> dict:
    """I1: the lineup's identity verdicts and the other identity streams, against the snapshot."""
    import hashlib
    from reticle.lineup import load_lineup
    lu = load_lineup(sid, STORE)
    now = sorted((v["entity_id"], v["agent"], v["status"]) for v in (lu or {}).get("agent_identity") or [])
    was = [tuple(x) for x in before[sid]["lineup_agent_identity"]]
    changes = [{"was": a, "now": b} for a, b in zip(was, now) if a != b]
    if len(was) != len(now):
        changes.append({"count_was": len(was), "count_now": len(now)})
    files = {}
    for name, h in before[sid]["identity_streams"].items():
        f = STORE / "events" / name / f"{sid}.jsonl"
        files[name] = (hashlib.sha256(f.read_bytes()).hexdigest() == h) if f.is_file() else False
    return {"lineup_verdicts": len(now), "lineup_changes": changes,
            "identity_streams_unchanged": files, "changes": len(changes) + sum(not v for v in files.values())}


def cmd_matches(out: Path, sids: list[str], before: Path, stale_tray: bool = False) -> None:
    from reticle.store import Store
    store = Store(STORE)
    fresh(out / "matches.json")
    snap = json.loads(before.read_text(encoding="utf-8"))
    res, dis = {}, []
    for sid in sids:
        r, d = session_matches(store, sid, stale_tray)
        r["I1"] = identity_check(snap, sid)
        res[sid] = r
        dis += d
        print(sid, json.dumps({k: r[k] for k in ("P4", "P5", "G6", "T1", "V1", "C1", "I1")})[:1600], flush=True)
    tot = {}
    for k in ("below_null", "n"):
        tot[f"P4_{k}"] = sum(res[s]["P4"][k] for s in sids)
    tot["P4_share"] = round(tot["P4_below_null"] / tot["P4_n"], 4)
    tot["P4_wilson95"] = wilson95(tot["P4_below_null"], tot["P4_n"])
    for k in ("both_named", "agree", "audit_tracks", "audit_only", "context_only"):
        tot[f"P5_{k}"] = sum(res[s]["P5"][k] for s in sids)
    tot["P5_wilson95"] = wilson95(tot["P5_agree"], tot["P5_both_named"])
    for k in ("agree", "disagree", "no_fragment", "ambiguous"):
        tot[f"G6_ally_{k}"] = sum(res[s]["G6"]["ally_fragment"].get(k, 0) for s in sids)
    for k in ("agree", "disagree", "unnamed", "casts", "casts_with_birth"):
        tot[f"G6_tray_{k}"] = sum(res[s]["G6"]["tray_drop"].get(k, 0) for s in sids)
    tot["G6_ally_wilson95"] = wilson95(tot["G6_ally_agree"], tot["G6_ally_agree"] + tot["G6_ally_disagree"])
    tot["G6_tray_wilson95"] = wilson95(tot["G6_tray_agree"], tot["G6_tray_agree"] + tot["G6_tray_disagree"])
    for k in ("births", "single_fix", "gated_at_birth"):
        tot[f"T1_{k}"] = sum(res[s]["T1"].get(k, 0) for s in sids)
    tot["T1_wilson95"] = wilson95(tot["T1_single_fix"], tot["T1_births"])
    tot["G7_max_wall_s"] = max(res[s]["wall_s_command"] for s in sids)
    tot["I1_changes"] = sum(res[s]["I1"]["changes"] for s in sids)
    tot["V1_inner"] = sum(res[s]["V1"]["map_shown_between_clean_samples"] for s in sids)
    payload = {"version": VERSION, "sessions": sids, "per_session": res, "total": tot,
               "params": {"BIRTH_R": BIRTH_R, "BIRTH_MS_ALLY": BIRTH_MS_ALLY, "THROWN_MS": THROWN_MS}}
    (out / "matches.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    with open(fresh(out / "g6_disagreements.jsonl"), "w", encoding="utf-8") as fh:
        for d in dis:
            fh.write(json.dumps(d) + "\n")
    print(json.dumps(tot, indent=1))


# ------------------------------------------------------------------ marks


def load_marks() -> list[dict]:
    """The dev glyph items and the held-out marks, each {sid, t_ms, x, y, truth, agent, src, dev_session}
    in the production minimap ROI's crop px."""
    import glyph_tables as gt
    _, _, items = gt.load_dev()
    _, pos = gt.split_items(items)
    marks = [{"sid": r["sid"], "t_ms": float(r["t_ms"]), "x": float(r["cx"]), "y": float(r["cy"]),
              "roi": r["roi"], "truth": r["truth"], "agent": r["agent"], "src": "dev_item",
              "dev_session": True} for r in pos]
    d = STORE / "labels" / "minimap_glyph_heldout"
    for p in sorted(d.glob("*.jsonl")):
        last = {}
        for r in read_jsonl(p):
            last[r["key"]] = r
        for r in last.values():
            for m in r.get("marks") or []:
                a = m.get("ability") or ""
                if m.get("unsure") or ":" not in a or a.split(":")[1] not in ("C", "Q", "E", "X"):
                    continue
                marks.append({"sid": r["session_id"], "t_ms": float(r["t_ms"]), "x": float(m["x"]),
                              "y": float(m["y"]), "roi": r["roi"], "truth": a, "agent": r["agent"],
                              "src": "heldout_mark", "dev_session": bool(r.get("dev_session"))})
    return marks


def bank_agent(name: str, keys: list[str]) -> str | None:
    from reticle.adjudication.ability_glyph import _agent_key
    for k in keys:
        if _agent_key(k.split(":")[0]) == _agent_key(name):
            return k.split(":")[0]
    return None


def run_session(store, sid: str, marks: list[dict], tables, tmp: Path) -> dict:
    """The ability pass's readers in memory over the cache on the marks' windows, then the verdict."""
    from reticle import geometry
    from reticle.ability_icons import icon_reader
    from reticle.adjudication import ability_glyph as ag
    from reticle.minimap import minimap_roi_px
    from reticle.minimap_glyph import LiveIcons, glyph_reader
    from reticle.passes import SessionContext
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache, grid_times
    man = store.read_manifest(sid)
    profile = get_profile(man["source_profile"])
    ctx = SessionContext(store=store, manifest=man, profile=profile)
    agent = bank_agent(marks[0]["agent"], tables.keys)
    cands = {"ally": {"agents": {agent: "named"}, "blind": 0}}
    ip = icon_reader(ctx, None, phase_at=None, phase_reason="stage 3 eval: demo windows, no live phase gate")
    gp = glyph_reader(ctx, None, LiveIcons(ip), cands,
                      f"demo agent {agent} (the marks' session agent; no lineup is stored for a demo)")
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        return {"refused": f"no minimap cache: {why}"}
    spans = []
    for m in sorted(marks, key=lambda m: m["t_ms"]):
        a, b = m["t_ms"] + WINDOW_MS[0], m["t_ms"] + WINDOW_MS[1]
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    want = sorted({x for a, b in spans for x in grid_times(cache.t_ms, a, b, 0.5)})
    n = 0
    for smp in cache.samples(want, rois=("minimap",)):
        ip.feed(smp)
        gp.feed(smp)
        n += 1
    gkey = geometry.key_of(sid, store.root)
    gp_rows = gp.events(sid, gkey)
    ip_rows = ip.events(sid, gkey)
    gpath, ipath = tmp / f"{sid}.ability_glyph.jsonl", tmp / f"{sid}.ability_icon.jsonl"
    for p, rows in ((gpath, gp_rows), (ipath, ip_rows)):
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, separators=(",", ":"), allow_nan=False) + "\n")
    g = ag.load_glyph_rows(gpath, tables.keys)
    v = ag.load_icon_verify(ipath)
    res = ag.adjudicate(sid, g, v, tables, None, None, None, kit_reason="demo: no tray_kit")
    box = minimap_roi_px(profile, *ctx.wh)
    return {"frames": n, "asked": len(want), "res": res, "ctx": g["context"], "box": box, "agent": agent,
            "scale": float(np.nanmedian(g["context"]["scale"])) if g["context"]["n"] else None}


def score_marks(marks: list[dict], run: dict) -> list[dict]:
    res, c = run["res"], run["ctx"]
    from reticle.adjudication.ability import disc_tracks  # noqa: F401  (the verdict joined them)
    rows = {r["track"]: r for r in res["rows"][1:]}
    tracks = res["tracks"][1:]
    # Each context disc row's track: the verdict's tracks hold their fix disc ids.
    track_of = {}
    for t in tracks:
        for d in t["fix"]["disc"]:
            track_of[d] = t["track"]
    out = []
    bx, by = run["box"][0], run["box"][1]
    for m in marks:
        x = m["x"] + m["roi"][0] - bx
        y = m["y"] + m["roi"][1] - by
        if c["n"] == 0:
            out.append({**m, "outcome": "no_disc"})
            continue
        dt = np.abs(c["t_ms"] - m["t_ms"])
        dd = np.hypot(c["cx"] - x, c["cy"] - y)
        ok = (dt <= MARK_MS) & (dd <= MARK_R * c["scale"])
        if not ok.any():
            out.append({**m, "outcome": "no_disc"})
            continue
        j = np.flatnonzero(ok)[np.argmin((dd + dt / 100.0)[ok])]
        tr = track_of.get(str(c["disc"][j]))
        v = rows.get(tr)
        named = v["ability"]["key"] if v and v["ability"] else None
        kit_agent = (v["best"].split(":")[0] if v and v["kit_clear"] and v["best"] else None)
        audit = v["audit"] if v else None
        out.append({**m, "outcome": "named" if named else ("pending" if v and v["pending"] else "refused"),
                    "track": tr, "reason": v["reason"] if v else None, "named": named, "kit_agent": kit_agent,
                    "slot_right": None if not named else named == m["truth"],
                    "agent_right": None if not kit_agent else
                    kit_agent.replace("/", "_") == m["truth"].split(":")[0].replace("/", "_"),
                    "audit_named": audit["best"] if audit and audit["named"] else None,
                    "best": v["best"] if v else None, "pooled": v["pooled"] if v else None,
                    "disc_reason": str(c["reason"][j]) or None})
    return out


def cmd_marks(out: Path) -> None:
    from reticle.adjudication import ability_glyph as ag
    from reticle.store import Store
    store = Store(STORE)
    fresh(out / "marks.json")
    tmp = out / "marks_rows"
    tmp.mkdir(parents=True, exist_ok=True)
    tables = ag.VerdictTables.load(STORE)
    marks = load_marks()
    by = defaultdict(list)
    for m in marks:
        by[m["sid"]].append(m)
    scored, runs = [], {}
    for sid in sorted(by):
        r = run_session(store, sid, by[sid], tables, tmp)
        if "refused" in r:
            runs[sid] = r
            scored += [{**m, "outcome": "session_refused", "why": r["refused"]} for m in by[sid]]
            print(sid, r["refused"], flush=True)
            continue
        cov = r["res"]["rows"][0]
        runs[sid] = {"frames": r["frames"], "asked": r["asked"], "agent": r["agent"], "tracks": cov["tracks"],
                     "named": cov["named"], "refused": cov["refused"], "wall_s": cov["wall_s"]}
        s = score_marks(by[sid], r)
        scored += s
        print(sid, r["agent"], len(by[sid]), "marks", Counter(x["outcome"] for x in s), flush=True)

    def summary(sub):
        named = [m for m in sub if m["outcome"] == "named"]
        kit = [m for m in sub if m.get("agent_right") is not None]
        sr = sum(m["slot_right"] for m in named)
        ar = sum(m["agent_right"] for m in kit)
        covered = [m for m in sub if m["outcome"] not in ("no_disc", "session_refused")]
        aud = [m for m in sub if m.get("audit_named")]
        aud_agent = sum(m["audit_named"].split(":")[0].replace("/", "_") ==
                        m["truth"].split(":")[0].replace("/", "_") for m in aud)
        aud_slot = sum(m["audit_named"] == m["truth"] for m in aud)
        return {"marks": len(sub), "covered": len(covered), "named": len(named), "slot_right": sr,
                "slot_wilson95": wilson95(sr, len(named)), "kit_clear": len(kit), "agent_right": ar,
                "agent_wilson95": wilson95(ar, len(kit)),
                "named_share_of_covered": round(len(named) / len(covered), 4) if covered else None,
                "outcomes": dict(Counter(m["outcome"] for m in sub)),
                "reasons": dict(Counter(m["reason"] for m in sub if m["outcome"] == "refused")),
                "pending": sum(m["outcome"] == "pending" for m in sub),
                "other_agent_marks": sum(m["truth"].split(":")[0].lower().replace("/", "_") !=
                                         str(m["agent"]).lower().replace("/", "_") for m in sub),
                "audit_named": len(aud), "audit_agent_right": aud_agent, "audit_slot_right": aud_slot,
                "confusions": dict(Counter(f"{m['truth']}->{m['named']}" for m in named
                                           if not m["slot_right"]).most_common(12))}
    arms = {"dev_items": [m for m in scored if m["src"] == "dev_item"],
            "heldout_dev_sessions": [m for m in scored if m["src"] == "heldout_mark" and m["dev_session"]],
            "heldout": [m for m in scored if m["src"] == "heldout_mark" and not m["dev_session"]]}
    summ = {k: summary(v) for k, v in arms.items()}
    payload = {"version": VERSION, "params": {"MARK_MS": MARK_MS, "MARK_R": MARK_R, "WINDOW_MS": WINDOW_MS},
               "runs": runs, "summary": summ, "marks": scored,
               "note": "context set = the session agent's kit; not gate 4's fresh set"}
    (out / "marks.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summ, indent=1))


# ------------------------------------------------------------------ montage


def cmd_montage(out: Path, sid: str, what: str, n: int, seed: int = 20261005) -> None:
    """Tiles of the crop cache at each sampled track's birth (60 px about it), in a fixed random draw."""
    import cv2
    from reticle.minimap import minimap_roi_px
    from reticle.passes import SessionContext
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    store = Store(STORE)
    rows = read_jsonl(store.events_path("ability_glyph_name", sid))[1:]
    tracks = {r["track"]: r for r in read_jsonl(store.events_path("ability_disc_track", sid))
              if r.get("kind") == "track"}
    if what == "pending":
        pick = [r for r in rows if r["pending"]]
    elif what == "named":
        pick = [r for r in rows if r["ability"]]
    else:
        raise SystemExit(f"unknown --what {what}")
    rng = np.random.default_rng(seed)
    pick = [pick[i] for i in sorted(rng.choice(len(pick), size=min(n, len(pick)), replace=False))]
    man = store.read_manifest(sid)
    profile = get_profile(man["source_profile"])
    ctx = SessionContext(store=store, manifest=man, profile=profile)
    box = minimap_roi_px(profile, *ctx.wh)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    tiles = []
    times = [tracks[r["track"]]["birth_ms"] for r in pick]
    got = {float(s.t_ms): s.frame for s in cache.samples(sorted(set(times)), rois=("minimap",))}
    for r, t in zip(pick, times):
        fr = got.get(float(t))
        if fr is None:
            continue
        crop = fr[box[1]:box[3], box[0]:box[2]]
        x, y = (int(round(v)) for v in tracks[r["track"]]["birth_xy"])
        h = 30
        pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        tile = pad[y:y + 2 * h, x:x + 2 * h]
        tile = cv2.resize(tile, (180, 180), interpolation=cv2.INTER_NEAREST)  # display only
        lab = (r["pending"] or (r["ability"] or {}).get("key") or "")[:14]
        cv2.putText(tile, f"{lab} {r['pooled']}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
        cv2.putText(tile, f"{t / 1000:.1f}s", (2, 174), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
        tiles.append(tile)
    cols = 6
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    p = fresh(out / f"montage_{sid}_{what}.png")
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), grid)
    print(p, len(pick), "tiles")


# ------------------------------------------------------------------ record


def cmd_record(out: Path) -> None:
    from reticle import metrics
    if any(r.get("tool") == "glyph_stage3" and (r.get("context") or {}).get("run") == str(out)
           for r in metrics.load()):
        raise SystemExit(f"{out} is already recorded")
    from reticle.version import ABILITY_DISC_TRACK_VERSION, ABILITY_GLYPH_NAME_VERSION
    from reticle.minimap_glyph import GLYPH_BANK_STAMP
    deps = {"eval": VERSION, "ability_glyph_name": ABILITY_GLYPH_NAME_VERSION,
            "ability_disc_track": ABILITY_DISC_TRACK_VERSION, "glyph_bank": GLYPH_BANK_STAMP}
    ctx = {"run": str(out)}
    m = json.loads((out / "matches.json").read_text(encoding="utf-8"))
    for sid, r in m["per_session"].items():
        v = {"tracks": r["tracks"], "with_clean_sample": r["with_clean_sample"], "named": r["named"],
             "pending": r["pending"], "agents_named": r["agents_named"], "kit_clear": r["kit_clear"],
             "below_null": r["P4"]["below_null"], "below_null_share": r["P4"]["share"],
             "audit_tracks": r["P5"]["audit_tracks"], "audit_both_named": r["P5"]["both_named"],
             "audit_agree": r["P5"]["agree"], "wall_s": r["wall_s_command"],
             "g6_ally_agree": r["G6"]["ally_fragment"].get("agree", 0),
             "g6_ally_disagree": r["G6"]["ally_fragment"].get("disagree", 0),
             "g6_tray_agree": r["G6"]["tray_drop"].get("agree", 0),
             "g6_tray_disagree": r["G6"]["tray_drop"].get("disagree", 0),
             "t1_births": r["T1"].get("births", 0), "t1_single_fix": r["T1"].get("single_fix", 0),
             "v1_named_with_map_shown": r["V1"]["named_with_map_shown_sample"],
             "c1_tracks": r["C1"]["tracks"], "c1_named": r["C1"]["named"],
             "i1_changes": r["I1"]["changes"]}
        v |= {f"refused_{k}": n for k, n in r["refused"].items()}
        v |= {f"refused_clean_{k}": n for k, n in r["refused_with_clean_sample"].items()}
        metrics.record("glyph_stage3", part="matches", session=sid, values=v, deps=deps, context=ctx)
    t = m["total"]
    metrics.record("glyph_stage3", part="matches", session="handful",
                   values={k: v for k, v in t.items() if not isinstance(v, list)} |
                   {f"{k}_lo": v[0] for k, v in t.items() if isinstance(v, list)} |
                   {f"{k}_hi": v[1] for k, v in t.items() if isinstance(v, list)},
                   deps=deps, context=ctx | {"sessions": ",".join(m["sessions"])})
    if (out / "marks.json").exists():
        k = json.loads((out / "marks.json").read_text(encoding="utf-8"))
        for arm, s in k["summary"].items():
            v = {x: s[x] for x in ("marks", "covered", "named", "slot_right", "kit_clear", "agent_right",
                                   "pending", "other_agent_marks", "audit_named", "audit_agent_right",
                                   "audit_slot_right")}
            v |= {"slot_lo95": s["slot_wilson95"][0], "slot_hi95": s["slot_wilson95"][1],
                  "agent_lo95": s["agent_wilson95"][0], "agent_hi95": s["agent_wilson95"][1],
                  "named_share_of_covered": s["named_share_of_covered"]}
            v |= {f"refused_{x}": n for x, n in s["reasons"].items() if x}
            metrics.record("glyph_stage3", part=f"marks_{arm}", session="marks", values=v, deps=deps,
                           context=ctx)
    print(metrics.report(tool="glyph_stage3"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("matches", "marks", "montage", "record"))
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--before", type=Path)
    ap.add_argument("--what", default="pending")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--stale-tray", action="store_true",
                    help="matches: read tray drops at an older tray stamp (stated in the output)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "matches":
        cmd_matches(a.out, a.sids, a.before, a.stale_tray)
    elif a.cmd == "marks":
        cmd_marks(a.out)
    elif a.cmd == "montage":
        cmd_montage(a.out, a.sids[0], a.what, a.n)
    else:
        cmd_record(a.out)


if __name__ == "__main__":
    main()
