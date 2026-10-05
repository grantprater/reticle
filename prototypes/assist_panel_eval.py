r"""Score the stored assist panel reads against Riot's records and the player's labels.

The panel is [domain:killfeed/assist-panel].

    .\.venv\Scripts\python.exe prototypes\assist_panel_eval.py [--sheet N] [--json OUT]

Reads the `assist` stream (`reticle assists <session>`), decodes nothing.

**Riot.** Each Riot kill's `assistants` lists the players Riot credited with
an assist (subjects; no ability, no kind). Stored deaths pair to Riot kills
through `prototypes/riot_ground_truth.py` (`score_session`'s `death_rows`,
which carry `death_id` and the kill's `gameTime`); this file pairs nothing
itself. Riot may credit assists the panel never draws, so a disagreement is
counted by kind (the panel read none, the panel read fewer, more, or other
agents) and `--sheet` draws samples of each kind from the crop cache to be
judged by eye, never all called reader errors. Riot truth is evaluation only.

**Labels.** The player's `killfeed_assist` labels (`prototypes/label_assists.py`)
give the count, each assister's agent (left to right) and the icon (an
ability, `none`, `other` or `unsure`): they score the count, the agents and
the icons; Riot gives no ability.

**Consistency.** Where an assister is the player's own agent on the player's
side, the stored `tray_drop` player casts in the `CAST_WINDOW_MS` before the
kill are compared with the icon read: agreement is consistency, not accuracy,
and each disagreement is stored.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import riot_ground_truth as rgt  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.lineup import abilities_for, load_lineup  # noqa: E402

#: A player cast this long before a kill can be the assist's ability.
CAST_WINDOW_MS = 20000.0
OUT = Store().root / "analysis" / "assist-panel-20261004"


def _below_normal():
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except (AttributeError, OSError):
        pass


def paired(store_root: Path, sid: str, d: dict, ident: dict, ref) -> list[dict]:
    """`riot_ground_truth.score_session`'s death rows (death_id <-> Riot kill)."""
    opts = SimpleNamespace(match_tol=rgt.MATCH_TOL_MS, derive_rounds=None, ult=False,
                           no_minimap=True, legacy=set(), deaths_from=None, podcast=set())
    out = rgt.score_session(sid, d, ident, ref, store_root, None, opts)
    return out.get("death_rows") or []


def canon(a):
    return rgt.canon(a)


def score_riot(store: Store, sids: list[str]) -> tuple[dict, list[dict]]:
    recs = rgt.riot_records(store.root)
    ref = rgt.Reference(store.root / "external" / "valorant-api", fetch=False)
    idents = rgt.identify_player(recs, store.root)
    c = Counter()
    reasons = Counter()
    rows = []
    for sid in sids:
        if sid not in recs or not store.has_events("assist", sid):
            continue
        d = recs[sid]
        ident = rgt.resolve_lineup_player(d, idents[sid], ref)
        who = {p["subject"]: p for p in d["match"]["players"]}
        agent_of = {s: ref.agent(p["characterId"]) for s, p in who.items()}
        kills = {k["gameTime"]: k for k in d["match"]["kills"]}
        av = {r["death_id"]: r for r in store.read_events("assist", sid)
              if r.get("kind") == "assist_verdict"}
        for pr in paired(store.root, sid, d, ident, ref):
            v = av.get(pr.get("death_id"))
            k = kills.get(pr["riot_game_ms"])
            if v is None or k is None:
                continue
            truth = sorted(canon(agent_of.get(s)) for s in (k.get("assistants") or []))
            c["paired"] += 1
            c[f"riot_n{len(truth)}"] += 1
            row = {"session": sid, "death_id": v["death_id"], "t_ms": v["t_ms"],
                   "riot": truth, "count": v["count"], "count_status": v["count_status"],
                   "count_reason": v.get("count_reason"),
                   "agents": [a["agent"] for a in v["assisters"]],
                   "icons": [a.get("icon") for a in v["assisters"]],
                   "ambiguous_pair": pr.get("ambiguous")}
            rows.append(row)
            present = v.get("present", None if v["count"] is None else v["count"] > 0)
            if v["count"] is None:
                c["count_refused"] += 1
                reasons[v.get("count_reason")] += 1
                if present is None:
                    continue
                # the ROI cut the panel after count_min assisters: presence
                # and the assisters found are read, the count is not
                c["lower_bound"] += 1
                c["lower_bound_riot_has"] += int(bool(truth))
                c["lower_bound_riot_at_least"] += int(len(truth) >= v.get("count_min", 0))
                for a_ in v["assisters"]:
                    c["lb_assisters"] += 1
                    if a_["agent"]:
                        c["lb_named"] += 1
                        c["lb_in_riot"] += int(canon(a_["agent"]) in truth)
                row["kind"] = "lower_bound"
                continue
            c["count_read"] += 1
            t_has, p_has = bool(truth), v["count"] > 0
            c[{(True, True): "tp", (False, False): "tn", (True, False): "fn",
               (False, True): "fp"}[(t_has, p_has)]] += 1
            c["count_exact"] += int(v["count"] == len(truth))
            if t_has and p_has:
                kind = ("same_n" if v["count"] == len(truth)
                        else "panel_fewer" if v["count"] < len(truth) else "panel_more")
                c[kind] += 1
            row["kind"] = ("tn" if not t_has and not p_has else "fn_panel_none" if t_has and not p_has
                           else "fp_riot_none" if not t_has else
                           "same_n" if v["count"] == len(truth) else
                           "panel_fewer" if v["count"] < len(truth) else "panel_more")
            for a in v["assisters"]:
                c["assisters"] += 1
                if a["agent"] is None:
                    c["assister_unnamed"] += 1
                    reasons[f"unnamed:{(a.get('identity') or {}).get('reason')}"] += 1
                    continue
                c["assister_named"] += 1
                c["assister_in_riot" if canon(a["agent"]) in truth else "assister_not_in_riot"] += 1
            if p_has and t_has and all(a["agent"] for a in v["assisters"]):
                c["set_scored"] += 1
                c["set_exact"] += int(sorted(canon(a["agent"]) for a in v["assisters"]) == truth)
            if len(truth) >= 3:
                c["riot3_panel_count_" + str(v["count"])] += 1
    out = dict(c)
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    out["presence_recall"] = round(tp / max(1, tp + fn), 4)
    out["presence_precision"] = round(tp / max(1, tp + fp), 4)
    out["count_exact_rate"] = round(c["count_exact"] / max(1, c["count_read"]), 4)
    out["set_exact_rate"] = round(c["set_exact"] / max(1, c["set_scored"]), 4)
    out["assister_precision"] = round(c["assister_in_riot"] / max(1, c["assister_named"]), 4)
    out["assister_refusal_rate"] = round(c["assister_unnamed"] / max(1, c["assisters"]), 4)
    out["lower_bound_presence_precision"] = round(c["lower_bound_riot_has"] / max(1, c["lower_bound"]), 4)
    out["lower_bound_assister_precision"] = round(c["lb_in_riot"] / max(1, c["lb_named"]), 4)
    out["reasons"] = dict(reasons.most_common())
    return out, rows


def _labels(store: Store) -> list[dict]:
    last = {}
    for p in (store.root / "labels" / "killfeed_assist").glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
    return [r for r in last.values() if r.get("answer")]


def score_labels(store: Store) -> tuple[dict, list[dict]]:
    """Count, agents and icons against the player's labels."""
    c = Counter()
    icon_conf = Counter()
    rows = []
    cache = {}
    for lab in _labels(store):
        sid = lab["session_id"]
        if sid not in cache:
            cache[sid] = ({r["death_id"]: r for r in store.read_events("assist", sid)
                           if r.get("kind") == "assist_verdict"}
                          if store.has_events("assist", sid) else None)
        av = cache[sid]
        if av is None:
            c["no_stream"] += 1
            continue
        v = av.get(lab["key"])
        if v is None:   # the death id moved: same slot, nearest time
            near = [r for r in av.values() if abs((r.get("t_ms") or 0) - lab["t_ms"]) <= 4500
                    and r["death_id"].rsplit(":", 1)[-1] == str(lab["slot"])]
            v = min(near, key=lambda r: abs(r["t_ms"] - lab["t_ms"])) if near else None
        if v is None:
            c["unmatched"] += 1
            continue
        ans = lab["answer"]
        c["labels"] += 1
        if v["count"] is None:
            c["count_refused"] += 1
            continue
        c["count_read"] += 1
        c["count_exact"] += int(v["count"] == ans["count"])
        c[f"count_{ans['count']}_read_{v['count']}"] += 1
        if v["count"] != ans["count"]:
            rows.append({"session": sid, "t_ms": lab["t_ms"], "death_id": v["death_id"],
                         "label": ans, "count": v["count"], "kind": "count"})
            continue
        # the label goes left to right; the reader from the killer leftwards
        for la, a in zip(reversed(ans["assisters"]), v["assisters"]):
            c["assisters"] += 1
            if la["agent"] and a["agent"]:
                c["agent_scored"] += 1
                c["agent_right"] += int(canon(la["agent"]) == canon(a["agent"]))
            elif la["agent"]:
                c["agent_refused"] += 1
            li, ri = la["icon"], a.get("icon")
            if li in ("unsure", "other", None):
                c[f"icon_label_{li}"] += 1
                continue
            lab_none = li == "none"
            if ri is None:
                c["icon_refused_none" if lab_none else "icon_refused_named"] += 1
                icon_conf[(li, f"refused:{a.get('icon_reason')}:{a.get('drawn')}")] += 1
                continue
            c["icon_presence_scored"] += 1
            c["icon_presence_right"] += int(lab_none == (ri == "none"))
            if not lab_none:
                c["icon_named_scored"] += 1
                ok = " ".join(li.split()).casefold() == " ".join(ri.split()).casefold()
                c["icon_named_right"] += int(ok)
                icon_conf[(li, ri if ok else f"WRONG:{ri}")] += 1
            if not (lab_none == (ri == "none")) or (not lab_none and ri != li):
                rows.append({"session": sid, "t_ms": lab["t_ms"], "death_id": v["death_id"],
                             "label": la, "read": {"agent": a["agent"], "icon": ri,
                                                   "set": a.get("icon_set"),
                                                   "scores": a.get("icon_scores")},
                             "kind": "icon"})
    out = dict(c)
    out["count_exact_rate"] = round(c["count_exact"] / max(1, c["count_read"]), 4)
    out["agent_right_rate"] = round(c["agent_right"] / max(1, c["agent_scored"]), 4)
    out["icon_presence_rate"] = round(c["icon_presence_right"] / max(1, c["icon_presence_scored"]), 4)
    out["icon_named_rate"] = round(c["icon_named_right"] / max(1, c["icon_named_scored"]), 4)
    out["icon_confusion"] = {f"{a} -> {b}": n for (a, b), n in icon_conf.most_common()}
    return out, rows


def cross_check_tray(store: Store, sids: list[str]) -> tuple[dict, list[dict]]:
    """The player's own assists against stored `tray_drop` player casts."""
    c = Counter()
    rows = []
    for sid in sids:
        if not (store.has_events("assist", sid) and store.has_events("tray_drop", sid)):
            continue
        lineup = load_lineup(sid, store.root) or {}
        me = (lineup.get("player") or {}).get("agent")
        if not me:
            continue
        kit = abilities_for(me, store.root)
        casts = [r for r in store.read_events("tray_drop", sid)
                 if r.get("kind") == "drop" and r.get("player_cast")]
        for v in store.read_events("assist", sid):
            if v.get("kind") != "assist_verdict" or v.get("killer_side") != "ally":
                continue
            for a in v["assisters"]:
                if a["agent"] != me or a.get("icon") in (None,):
                    continue
                t = v["t_ms"]
                near = [r for r in casts if t - CAST_WINDOW_MS <= r["t_ms"] <= t + 500]
                cast_names = sorted({kit.get(r["slot"]) for r in near if kit.get(r["slot"])})
                c["own_assists"] += 1
                if a["icon"] == "none":
                    c["none_icon"] += 1
                    continue
                ok = any(" ".join(n.split()).casefold() == " ".join(a["icon"].split()).casefold()
                         for n in cast_names)
                c["agree" if ok else ("no_cast_seen" if not cast_names else "disagree")] += 1
                if not ok:
                    rows.append({"session": sid, "death_id": v["death_id"], "t_ms": t,
                                 "icon": a["icon"], "casts": cast_names})
    return dict(c), rows


def sheet(store: Store, rows: list[dict], kinds: tuple, n: int, name: str) -> Path | None:
    """Crops of the panel region for `n` rows of each kind, for judging by eye."""
    import cv2
    import numpy as np
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    pick = []
    for kind in kinds:
        pick += [r for r in rows if r.get("kind") == kind][:n]
    by = defaultdict(list)
    for r in pick:
        by[r["session"]].append(r)
    tiles = []
    for sid, rs in sorted(by.items()):
        man = store.read_manifest(sid)
        cache, _why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "killfeed")
        obs = defaultdict(list)
        for o in store.read_events("killfeed_assist", sid):
            obs[o.get("death_id")].append(o)
        want = {}
        for r in rs:
            views = [o for o in obs[r["death_id"]] if o.get("rests_on")]
            if views:
                want.setdefault(float(views[len(views) // 2]["t_ms"]), []).append(
                    (r, views[len(views) // 2]))
        x0, y0, x1, y1 = cache.rect_of("killfeed")
        for smp in cache.samples(sorted(want), rois="killfeed"):
            crop = smp.frame[y0:y1, x0:x1]
            for r, o in want[smp.t_ms]:
                ro = o["rests_on"][0]
                L, T = int(round(ro["x"])), int(ro["art_y0"])
                a = max(0, L - 130)
                t = crop[max(0, T - 2):T + 36, a:L + 30]
                t = np.pad(t, ((0, 0), (130 - (L - a), 0), (0, 0)))
                t = cv2.resize(t, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
                lab = np.full((16, t.shape[1], 3), 20, np.uint8)
                txt = (f"{sid} {r['t_ms'] / 1000:.1f} {r['kind']} riot={r.get('riot', r.get('label'))} "
                       f"read={r.get('agents', r.get('read'))} n={r.get('count')}")
                cv2.putText(lab, txt[:110], (2, 12), 0, 0.4, (255, 255, 255), 1)
                tiles.append(np.vstack([lab, t]))
    if not tiles:
        return None
    w = max(t.shape[1] for t in tiles)
    tiles = [np.hstack([t, np.zeros((t.shape[0], w - t.shape[1], 3), np.uint8)]) for t in tiles]
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"sheet_{name}.png"
    cv2.imwrite(str(p), np.vstack(tiles))
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sheet", type=int, default=0, help="crops per disagreement kind")
    ap.add_argument("--json", default=str(OUT / "eval.json"))
    ap.add_argument("--record", action="store_true", help="append metrics to notes/metrics.jsonl")
    args = ap.parse_args(argv)
    _below_normal()
    store = Store()
    sids = sorted(rgt.riot_records(store.root))
    riot, riot_rows = score_riot(store, sids)
    labels, label_rows = score_labels(store)
    tray, tray_rows = cross_check_tray(store, sids)
    print("riot:", json.dumps(riot, indent=1))
    print("labels:", json.dumps(labels, indent=1))
    print("tray cross-check:", tray)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({"riot": riot, "labels": labels, "tray": tray,
                                           "riot_rows": riot_rows, "label_rows": label_rows,
                                           "tray_disagreements": tray_rows}, indent=1),
                               encoding="utf-8")
    print("->", args.json)
    if args.record:
        from reticle import metrics
        from reticle.adjudication.assist import ASSIST_ADJUDICATION_VERSION
        from reticle.killfeed_assist import KILLFEED_ASSIST_VERSION
        deps = {"reader": KILLFEED_ASSIST_VERSION, "adjudication": ASSIST_ADJUDICATION_VERSION,
                "sessions": len(sids)}
        flat = lambda d: {k: v for k, v in d.items() if isinstance(v, (int, float))}
        metrics.record("assist_panel", part="riot", values=flat(riot), deps=deps)
        metrics.record("assist_panel", part="labels", values=flat(labels), deps=deps)
        metrics.record("assist_panel", part="tray", values=flat(tray), deps=deps)
        print("recorded assist_panel/riot, /labels, /tray")
    if args.sheet:
        for kinds, name in ((("fn_panel_none",), "fn"), (("fp_riot_none",), "fp"),
                            (("panel_fewer", "panel_more"), "count")):
            print(sheet(store, riot_rows, kinds, args.sheet, name))
        print(sheet(store, label_rows, ("count", "icon"), args.sheet * 2, "labels"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
