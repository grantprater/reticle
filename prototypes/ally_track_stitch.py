r"""Stitch named ally pieces into one track per teammate per round.

    .\.venv\Scripts\python.exe prototypes\ally_track_stitch.py diagnose [SID ...]
    .\.venv\Scripts\python.exe prototypes\ally_track_stitch.py stitch [SID ...]
    .\.venv\Scripts\python.exe prototypes\ally_track_stitch.py montage

Purpose. Ally round entities (`round-entity-0.7.0`) are pieces: segments cut
where the per-icon best teammate changes, named per round by
`identity.assign_ally_pieces`. A round holds a median of 19 pieces for four
teammates. This measures why pieces end and whether joining them gives one
track per teammate without new wrong names.

Input. Round entities rebuilt in memory WITHOUT deaths
(`ally_rendered_art_eval.entities`, the wired `session_lifetimes` with the
rendered-art references), so no death names or cuts a piece, and the
per-icon claims (`claims_from_ally_icons`, `evidence.scores`: log ratios
over the four teammates). Cached in %TEMP%; no store writes, no decode.

`diagnose` (step 1): piece end reasons; split boundaries whose two sides
carry the same name; pieces per (round, agent); tracks per round after
joining same-name pieces; co-observed piece pairs by median distance, and
those within the separation limit (duplicate fits); refusal reasons.

`stitch` (steps 2-3), per round:
1. Pieces the arbiter named one agent join that teammate's track. Names are
   not changed.
2. An unnamed piece is compared with each teammate's track, observation by
   observation in time order. Where both are observed in one frame, the
   piece is a DUPLICATE fit when its icon lies within one icon diameter
   (`2 * R_MAX`) of the track's; the teammate is excluded otherwise. The
   diagnosis finds no co-observed pair nearer than 16 px. A piece
   co-observed apart from all four tracks is a fifth icon. Between
   consecutive observations of the piece and the track, `track.refit_of`
   (the resolution limit), a jump within one icon diameter inside
   `REFIT_DT_S` (a refit of the same disc), or `track.admits` for the
   teammate's motion class must hold, with `association_tolerance` slack.
   The class is the `track.CLASSES` walker class whose note names the
   agent, else `walker`.
3. Evidence excludes a teammate whose summed log ratio over the piece's
   icons falls `margin_min` or more below the best teammate's. The piece
   attaches when kinematics and evidence leave exactly one teammate; the
   reason is recorded either way. Longer pieces go first, and passes repeat
   until nothing attaches. A piece the owner refused as `not_a_teammate`,
   or with no scored icon, is never attached: the montage of the first run
   showed unscored pieces attached on kinematics alone were ability dots,
   wall edges and bare floor.
4. Killfeed deaths are not an input. After stitching, icons on a teammate's
   track more than `WINDOW_MS[1]` after its death are counted as a
   consistency check; revive entries (`is_revive`) are not deaths, and a
   death followed by a revive of the victim in the round is skipped.

Measures, per widget width, against the pieces: tracks per round, share of
ally observations on a teammate's track, labels (`<store>/labels/death_icon`)
right/wrong/refused, segments at killfeed deaths (the binding rule of
`ally_rendered_art_eval.segments`), duplicates, and icons after death.
`montage` draws the attachments with the smallest evidence margin.

Predictions and outcome: `ally-track-stitching` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import track  # noqa: E402
from reticle.adjudication.identity import (claims_from_ally_icons,  # noqa: E402
                                           load_ally_portrait_references,
                                           load_identity_gallery)
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import MIN_ICON_SEPARATION_PX, R_MAX, widget_scale  # noqa: E402

import ally_rendered_art_eval as ev  # noqa: E402

STORE = ev.STORE
WORK = Path(tempfile.gettempdir()) / "reticle_ally_track_stitch"
#: One sample at 15 Hz, with jitter: a jump within one icon diameter this soon
#: is a refit of the same disc (lobe fits jump 10-20 px), not motion.
REFIT_DT_S = 0.15


# ---------------------------------------------------------------- data

def session_data(sid: str) -> dict | None:
    """Pieces without deaths, per-icon scores and killfeed deaths; cached."""
    path = WORK / "sessions" / f"{sid}.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    events = STORE.read_events("ally_icon", sid)
    lineup = load_lineup(sid, STORE.root)
    if not events or not lineup:
        return None
    man = STORE.read_manifest(sid)
    refs = load_ally_portrait_references(STORE.root)
    gallery = load_identity_gallery(STORE.root)
    rows = ev.entities(sid, man, events, lineup, gallery, refs)
    icons = [e for e in events if e.get("kind") == "icon"]
    scores, names = {}, Counter()
    for cl in claims_from_ally_icons(icons, lineup, gallery=gallery, session_id=sid,
                                     references=refs):
        s = (cl.get("evidence") or {}).get("scores")
        if s:
            scores[cl["entity_id"].rsplit(":ally_icon:", 1)[-1]] = s
            names[tuple(sorted(s))] += 1
    pieces = {}
    for e in rows:
        if e.get("kind") == "entity" and e.get("family") == "ally":
            pieces[e["id"]] = {"id": e["id"], "round": e["round_no"], "agent": e.get("agent"),
                               "reason": e.get("identity_reason"),
                               "end_reason": e.get("end_reason"),
                               "segment": e.get("segment_id") or e["id"],
                               "index": e.get("piece_index") or 0, "obs": []}
    for o in rows:
        if o.get("kind") == "observation" and o.get("entity_id") in pieces:
            pieces[o["entity_id"]]["obs"].append(
                (float(o["t_ms"]), int(o["frame_idx"]), o["observation_key"],
                 float(o["x"]), float(o["y"])))
    for p in pieces.values():
        p["obs"].sort()
    width = ev.widget_width(man)
    deaths = [(float(v["t_ms"]), v["victim"], v.get("round_no"))
              for v in STORE.read_events("death", sid)
              if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim")]
    d = {"sid": sid, "width": width, "scale": widget_scale(width),
         "names": list(names.most_common(1)[0][0]) if names else [],
         "pieces": pieces, "scores": scores, "deaths": deaths,
         "gate": float(refs["margin_min"])}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(d))
    return d


def rounds_of(d: dict) -> dict:
    out = defaultdict(list)
    for p in d["pieces"].values():
        if p["obs"]:
            out[p["round"]].append(p)
    return out


def evidence(d: dict, obs) -> dict:
    tot = Counter({a: 0.0 for a in d["names"]})
    for o in obs:
        tot.update(d["scores"].get(o[2], {}))
    return dict(tot)


# ---------------------------------------------------------------- step 1

def pair_distance(a, b):
    """Shared frames of two observation lists and their median distance."""
    fb = {o[1]: o for o in b}
    ds = [np.hypot(o[3] - fb[o[1]][3], o[4] - fb[o[1]][4]) for o in a if o[1] in fb]
    return len(ds), (float(np.median(ds)) if ds else None)


def diagnose(sids) -> dict:
    total, per_round, tracks_round, pieces_agent = Counter(), [], [], []
    for sid in sids:
        d = session_data(sid)
        if d is None:
            continue
        sep = MIN_ICON_SEPARATION_PX * d["scale"]
        for r, ps in rounds_of(d).items():
            per_round.append(len(ps))
            named = Counter(p["agent"] for p in ps if p["agent"])
            pieces_agent += list(named.values())
            tracks_round.append(len(named) + sum(1 for p in ps if not p["agent"]))
            for p in ps:
                er = p["end_reason"] or "none"
                total["end:" + ("split" if er.startswith("split") else er[:40])] += 1
                if not p["agent"]:
                    total["refused:" + (p["reason"] or "none")[:30]] += 1
            seg = defaultdict(list)
            for p in ps:
                seg[p["segment"]].append(p)
            for s in seg.values():
                s.sort(key=lambda p: p["index"])
                for a, b in zip(s, s[1:]):
                    k = ("both_named_same" if a["agent"] and a["agent"] == b["agent"] else
                         "both_named_diff" if a["agent"] and b["agent"] else "one_unnamed")
                    total["split_" + k] += 1
            for i, a in enumerate(ps):
                for b in ps[i + 1:]:
                    n, med = pair_distance(a["obs"], b["obs"])
                    if not n:
                        continue
                    total["coobs_pairs"] += 1
                    b8 = min(int(med / d["scale"] // 8) * 8, 40)
                    total[f"coobs_median_px_{b8:02d}+"] += 1
                    if med <= sep:
                        k = ("named_same" if a["agent"] and a["agent"] == b["agent"] else
                             "named_diff" if a["agent"] and b["agent"] else
                             "one_unnamed" if a["agent"] or b["agent"] else "both_unnamed")
                        total["dup_pairs_" + k] += 1
                        total["dup_shared_frames"] += n
    out = dict(sorted(total.items()))
    out["pieces_per_round_median"] = float(np.median(per_round))
    out["pieces_per_named_agent_round_median"] = float(np.median(pieces_agent))
    out["same_name_join_tracks_per_round_median"] = float(np.median(tracks_round))
    print(json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------- step 2

def compatible(piece_obs, track_obs, motion, scale, sep):
    """(kind, why): kind is 'join', 'duplicate' or None (excluded)."""
    tol = track.association_tolerance(scale)
    merged = sorted([(o, 0) for o in piece_obs] + [(o, 1) for o in track_obs],
                    key=lambda z: (z[0][0], z[1]))
    fr = {o[1]: o for o in track_obs}
    shared = [np.hypot(o[3] - fr[o[1]][3], o[4] - fr[o[1]][4])
              for o in piece_obs if o[1] in fr]
    if shared and float(np.median(shared)) > sep:
        return None, f"co-observed {len(shared)} frames, median {np.median(shared):.1f} px apart"
    worst = None
    for (a, sa), (b, sb) in zip(merged, merged[1:]):
        if sa == sb or a[1] == b[1]:
            continue
        dist, dt = float(np.hypot(a[3] - b[3], a[4] - b[4])), (b[0] - a[0]) / 1000.0
        if track.refit_of(b[3], b[4], [(a[3], a[4])], scale) is not None or \
                (dt <= REFIT_DT_S and dist <= sep):
            continue
        ok, why = track.admits(motion, max(0.0, dist - tol), dt, scale)
        if not ok:
            return None, f"{why}: {dist:.0f} px in {dt:.2f} s"
        if why != "within walking distance":
            worst = why
    kind = "duplicate" if shared else "join"
    return kind, worst or ("duplicate fit" if shared else "within walking distance")


def stitch_round(d: dict, ps: list[dict]) -> dict:
    sep = 2 * R_MAX * d["scale"]   # centres within one icon diameter share a disc
    tracks = {a: [p["id"] for p in ps if p["agent"] == a] for a in d["names"]}
    tobs = {a: sorted(o for p in ps if p["agent"] == a for o in p["obs"]) for a in d["names"]}
    verdict = {p["id"]: {"agent": p["agent"], "how": "named"} for p in ps if p["agent"]}
    todo = sorted((p for p in ps if not p["agent"]), key=lambda p: -len(p["obs"]))
    for p in todo:
        if (p["reason"] or "").startswith("not_a_teammate") or                 not any(o[2] in d["scores"] for o in p["obs"]):
            verdict[p["id"]] = {"agent": None, "how": "unattached", "kin": [], "why": {},
                                "margin": None, "evidence_best": None, "n": len(p["obs"]),
                                "reason": "owner refused: " + (p["reason"] or "")[:40]}
    changed = True
    while changed:
        changed = False
        for p in todo:
            if verdict.get(p["id"], {}).get("agent") or \
                    verdict.get(p["id"], {}).get("reason", "").startswith("owner refused"):
                continue
            E = evidence(d, p["obs"])
            best = max(E.values()) if E else 0.0
            kin, why = {}, {}
            for a in d["names"]:
                k, w = compatible(p["obs"], tobs[a], track.motion_for(a), d["scale"], sep)
                why[a] = w
                if k:
                    kin[a] = k
            allowed = [a for a in kin if E.get(a, 0.0) > best - d["gate"]]
            order = sorted(E, key=lambda a: -E[a])
            margin = (E[order[0]] - E[order[1]]) if len(order) > 1 else None
            v = {"agent": None, "how": "unattached", "kin": sorted(kin), "evidence_best": order[0] if order else None,
                 "margin": margin, "why": why, "n": len(p["obs"])}
            if len(allowed) == 1:
                a = allowed[0]
                v.update(agent=a, how=kin[a], reason=f"only {a}: {why[a]}",
                         runner=[b for b in order if b != a][:1])
                tracks[a].append(p["id"])
                tobs[a] = sorted(tobs[a] + p["obs"])
                changed = True
            else:
                v["reason"] = (("fifth icon: co-observed apart from every teammate"
                                if all(w.startswith("co-observed") for w in why.values())
                                else "no teammate admissible") if not kin else
                               "kinematics allow " + ",".join(sorted(kin)) +
                               "; evidence allows " + (",".join(allowed) or "none"))
            verdict[p["id"]] = v
    return {"tracks": tracks, "verdict": verdict}


# ---------------------------------------------------------------- step 3

def bind(deaths, ends):
    """`ally_rendered_art_eval.segments`' rule: the one end in the window."""
    lo, hi = ev.WINDOW_MS
    for t, victim, _ in deaths:
        e = [k for k, te in ends.items() if t - lo <= te <= t + hi]
        if len(e) != 1 or ends[e[0]] > t - ev.LEAD_MS:
            continue
        yield victim, e[0]


def measure(d, labs) -> tuple[Counter, list, list]:
    c, per_round, attach = Counter(), [], []
    name_of, piece_of, dup_keys = {}, {}, set()
    track_ends, piece_ends, track_obs = {}, {}, defaultdict(list)
    for r, ps in rounds_of(d).items():
        res = stitch_round(d, ps)
        by_id = {p["id"]: p for p in ps}
        unattached = [p for p in ps if not res["verdict"][p["id"]]["agent"]]
        per_round.append(sum(1 for a in res["tracks"] if res["tracks"][a]) + len(unattached))
        c["rounds"] += 1
        c["pieces"] += len(ps)
        for pid, v in res["verdict"].items():
            p = by_id[pid]
            piece_ends[pid] = p["obs"][-1][0]
            for o in p["obs"]:
                name_of[o[2]], piece_of[o[2]] = v["agent"], p["agent"]
            c["obs"] += len(p["obs"])
            c["obs_on_named_piece"] += len(p["obs"]) * bool(p["agent"])
            c["obs_on_track"] += len(p["obs"]) * bool(v["agent"])
            if v["how"] != "named":
                c["unnamed_pieces"] += 1
                c["attached_" + v["how"] if v["agent"] else "unattached"] += 1
                c["unattached_obs"] += 0 if v["agent"] else len(p["obs"])
                if not v["agent"]:
                    k = v["reason"].split(":")[0]
                    if k.startswith("kinematics"):
                        k = (f"kinematics allow {len(v['kin'])}, evidence allows "
                             + ("none" if k.endswith("none") else "several"))
                    c["why:" + k] += 1
                    c["whyobs:" + k] += len(p["obs"])
                if v["agent"]:
                    for o in p["obs"]:
                        lab = labs.get(o[2])
                        if lab:
                            c[f"lab_attached_{v['how']}_" + ("right" if lab["answer"] == v["agent"]
                                                             else "wrong")] += 1
                    attach.append({"sid": d["sid"], "round": r, "piece": pid, **v,
                                   "keys": [o[2] for o in p["obs"]]})
                    if v["how"] == "duplicate":
                        dup_keys |= {o[2] for o in p["obs"]}
        for a, ids in res["tracks"].items():
            if ids:
                obs = sorted(o for i in ids for o in by_id[i]["obs"])
                track_ends[(r, a)] = obs[-1][0]
                track_obs[(r, a)] = obs
        for p in unattached:
            track_ends[(r, p["id"])] = p["obs"][-1][0]
    for k, lab in labs.items():
        if k not in name_of:
            continue
        ans = lab["answer"]
        for tag, got in (("piece", piece_of[k]), ("track", name_of[k])):
            c[f"lab_{tag}_" + ("right" if got == ans else "refused" if got is None else "wrong")] += 1
    for tag, ends, name in (("piece", piece_ends, lambda k: d["pieces"][k]["agent"]),
                            ("track", track_ends,
                             lambda k: k[1] if k[1] in d["names"] else None)):
        for victim, k in bind(d["deaths"], ends):
            got = name(k)
            c[f"seg_{tag}_" + ("right" if got == victim else "none" if got is None else "wrong")] += 1
    hi = ev.WINDOW_MS[1]
    verdicts = [v for v in STORE.read_events("death", d["sid"])
                if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim")]
    revived = [(float(v["t_ms"]), v["victim"], v.get("round_no")) for v in verdicts
               if v.get("is_revive")]
    for v in verdicts:
        if v.get("is_revive"):
            continue
        t, victim, rno = float(v["t_ms"]), v["victim"], v.get("round_no")
        if any(a == victim and tr > t and rr == rno for tr, a, rr in revived):
            c["deaths_revived_skipped"] += 1
            continue
        for (r, a), obs in track_obs.items():
            if a != victim or not (obs[0][0] <= t <= obs[-1][0] + 60_000) or \
                    (rno is not None and rno != r):
                continue
            late = [o for o in obs if o[0] > t + hi]
            c["deaths_checked"] += 1
            c["deaths_with_late_icons"] += bool(late)
            c["late_icons"] += len(late)
            c["late_icons_on_named_pieces"] += sum(1 for o in late if piece_of[o[2]])
            c["deaths_with_late_icons_on_named_pieces"] += any(piece_of[o[2]] for o in late)
    c["duplicate_obs"] += len(dup_keys)
    return c, per_round, attach


def run_stitch(sids) -> dict:
    labs = ev.labels()
    total, rounds_n, attach = defaultdict(Counter), defaultdict(list), []
    for sid in sids:
        d = session_data(sid)
        if d is None:
            print(sid, "skipped: no events or no lineup", flush=True)
            continue
        c, pr, at = measure(d, labs)
        for k in ("all", f"w{d['width']}"):
            total[k] += c
            rounds_n[k] += pr
        attach += at
        print(sid, d["width"], "rounds", c["rounds"], "tracks/round", np.median(pr),
              "unattached", c["unattached"], flush=True)
    out = {}
    for k, v in total.items():
        o = dict(sorted(v.items()))
        o["tracks_per_round_median"] = float(np.median(rounds_n[k]))
        o["rounds_over_4_tracks"] = int(sum(n > 4 for n in rounds_n[k]))
        o["obs_on_track_share"] = round(v["obs_on_track"] / max(1, v["obs"]), 4)
        o["obs_on_named_piece_share"] = round(v["obs_on_named_piece"] / max(1, v["obs"]), 4)
        out[k] = o
    print(json.dumps(out, indent=1))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "run.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (WORK / "attach.pkl").write_bytes(pickle.dumps(attach))
    return out


def montage(n: int = 10) -> str:
    """Attachments with the smallest evidence margin between the chosen
    teammate and the runner-up: first, middle and last icon of each."""
    import cv2
    from label_death_icons import Crops
    rows = [a for a in pickle.loads((WORK / "attach.pkl").read_bytes()) if len(a["keys"]) >= 3]
    rows.sort(key=lambda a: (a["margin"] if a["evidence_best"] == a["agent"] else -1e9)
              if a["margin"] is not None else 1e9)
    crops, tiles = Crops(), []
    for a in rows[:n]:
        ks = [a["keys"][0], a["keys"][len(a["keys"]) // 2], a["keys"][-1]]
        strip = np.hstack([crops.get(a["sid"], k)[0] for k in ks])
        bar = np.zeros((22, max(strip.shape[1], 420), 3), np.uint8)
        m = "n/a" if a["margin"] is None else f"{a['margin']:.1f}"
        txt = (f"{a['sid'][:6]} R{a['round']} {a['piece'].split(':')[-1]} n={a['n']} "
               f"-> {a['agent']} ({a['how']}) ev_best={a['evidence_best']} m={m}")
        cv2.putText(bar, txt, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        strip = cv2.copyMakeBorder(strip, 0, 0, 0, bar.shape[1] - strip.shape[1],
                                   cv2.BORDER_CONSTANT)
        tiles.append(np.vstack([bar, strip]))
        print(txt, "|", a["reason"])
    img = np.vstack(tiles)
    out = WORK / "montage.png"
    cv2.imwrite(str(out), img)
    print(out, img.shape, "of", len(rows), "attachments")
    return str(out)


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("step", choices=("diagnose", "stitch", "montage"))
    a.add_argument("sids", nargs="*")
    args = a.parse_args()
    sids = args.sids or sorted(p.stem for p in (STORE.root / "events" / "round_entity").glob("*.jsonl"))
    if args.step == "diagnose":
        diagnose(sids)
    elif args.step == "stitch":
        run_stitch(sids)
    else:
        montage()


if __name__ == "__main__":
    main()
