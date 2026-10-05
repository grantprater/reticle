r"""Per-frame cost and prior share of a minimap ability-glyph reader, on cached minimap crops (no decode).

    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py [cost] --out DIR [--sessions c40d950031bb,a06f04a0059f]
                                                                [--windows 10] [--per 10] [--no-gpu]
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py rotation --out DIR
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py births --out DIR
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py record --out DIR     (the dir of the three runs)
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py table
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py rotrule --out DIR   (a new DIR per run)
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py record2 --out DIR   (the rotrule DIR, once)
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py baseline030         (stage 1's S1 baseline, once)
    .\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py crosscheck          (cross-channel casts, once)

`cost`, `rotation`, `births` and `rotrule` refuse to overwrite an output file, and `--out` has no default: the
stored 0.1.0 outputs (analysis/glyph-wiring-20261004) are evidence. `record2`, `baseline030` and `crosscheck`
refuse to append a row whose input is already recorded.

`baseline030` records single-frame top-1 of rotate-all and upright on the dev items of minimap-glyph-eval-0.3.0
(analysis/minimap-glyphs-killjoy-refs-20261004/gamedata-on), the windows stage 1 runs on, as
`glyph_channel_cost/dev_030`. `crosscheck` reads the per-cast rows of cross-channel-independence-0.1.0 (store
analysis/cross-channel-independence-20261004/casts.jsonl, branch cross-channel-independence-20261004) and records,
on the matches' casts of glyph-drawing abilities, the audio witness's precision and the glyph follow's (seeded at
the self icon) as `glyph_channel_cost/cross_channel@matches`; it recomputes nothing.

`rotrule` (prediction rows G1-G4) tests the two-flag rotation hypothesis (`rule_verdict`) on every minimap
component of the raw ability-states export, against the player's rotation answers, the dev fitted angles of
minimap-glyph-eval-0.3.0 and, single frame, the contaminated answers-on windows. `record2` records that run and
the stored clean held-out runs as metric series (`cmd_record2`); it reruns nothing.

`record` stores the three runs' summaries as metric series `glyph_channel_cost/<part>[@session]`; `table`
counts the game-data table's minimap rows (`cmd_table`).

`rotation` rescores the stored answers-on windows (analysis/minimap-glyphs-answers-20261004/answers-on, the
contaminated set, never a gate) under three rotation arms and with the ally candidate set in place of the
labelled caster's kit (`cmd_rotation`).

It sizes the production reader that docs/MINIMAP_GLYPH_CHANNEL.md proposes, with the matcher of
`prototypes/minimap_glyph_eval.py` (minimap-glyph-eval-0.2.0: game glyphs plus the player's texture answers,
probe states, masked Pearson of luma over a +-3 px centre search, canvas 11-22 px x scale, rotations 0-345 by
15 deg). Per session it reads `--windows` windows of `--per` consecutive cached minimap frames, the windows evenly
spaced over frames the stored `team_vision` stream calls widget drawn, and times per frame:

- `luma` and `propose`: the ability pass's proposer (`ability_icons.propose_icons` over `IconTerms`);
- bank A: per proposed disc, the kits of the ally candidate set (the lineup's named ally slots plus each refused
  slot's best guess and rival, as the arbiter admits rivals), every ability searched over all rotations;
- bank B: the same set, rotated only where ability-states-gamedata-0.2.0 sets `bRotates` on a minimap component of
  that ability (matched by display name), else upright;
- bank C: every agent's kit under policy B, the audit and surprise path;
- bank A on the GPU (torch CUDA): all discs of a frame in one matmul, transfer and sync included.

It also times `ability_icons.verify_icons` rescoring the previous cached frame's discs (the follow's cheap
path), and counts the prior's share: discs within 2 px x scale of a disc of the previous cached frame, which a
tracker carries without a fresh full-kit score. `stored_prior` reads the same share at the ability pass's 2 Hz
from every stored `ability_icon` stream, storage only. It names nothing: no verdict here is a claim.

Writes cost.json (per frame rows and the summary) under --out. Predictions: store notes/predictions.jsonl,
glyph-wiring-design-20261004 W1-W8 and the amendment W9. Wire: no (a measurement for the design document).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"
if os.name == "nt":
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

import minimap_glyph_eval as mge  # noqa: E402

VERSION = "glyph-channel-cost-0.2.1"   # 0.2.1: overwrite and duplicate guards, baseline030, crosscheck; 0.2.0
#                                        added rotrule and heldout; no command's measurement changed
STATES_TABLE = mge.STORE / "reference" / "ability-states" / "ability-states-gamedata-0.2.0.jsonl"
PRIOR_R = 2.0


def rotating_keys() -> tuple[set, list]:
    """(agent, catalogue key) of every ability one of whose minimap components sets bRotates in the game-data
    table, matched to the glyph keys by display name; and the table rows that matched none."""
    rot, unmatched = set(), []
    for ln in open(STATES_TABLE, encoding="utf-8"):
        r = json.loads(ln)
        if not r["cue_type"].startswith("minimap_") or not (r.get("minimap_props") or {}).get("bRotates"):
            continue
        names = [n for n in re.split(r"\s*/\s*", r["ability"] or "") if n]
        hit = next((k for n in names for k in [mge.find(r["agent"], n)] if k), None)
        if hit:
            rot.add(hit)
        else:
            unmatched.append(f"{r['agent']}:{r['key']}:{r['ability']}")
    return rot, sorted(set(unmatched))


def candidate_agents(sid: str) -> tuple[list, dict]:
    """The ally candidate set: named slots, plus each refused slot's best guess and rival (rivals, never names)."""
    d = json.load(open(mge.STORE / "lineups" / f"{sid}.json", encoding="utf-8"))
    out, why = [], {}
    for s in d["sides"]["ally"]:
        if s["agent"]:
            out.append(s["agent"])
            why[s["agent"]] = "named slot"
        else:
            for a, w in ((s["best_guess"], "refused slot best guess"), (s["rival"], "refused slot rival")):
                if a and a not in out:
                    out.append(a)
                    why[a] = w
    return [a.replace("KAY_O", "KAY/O") for a in out], why


def drawn_times(sid: str) -> set:
    rx = re.compile(r'"t_ms":([0-9.eE+-]+)')
    out = set()
    for ln in open(mge.STORE / "events" / "team_vision" / f"{sid}.jsonl", encoding="utf-8"):
        head = ln[:200]
        if '"kind":"frame"' in head and '"widget":"drawn"' in ln[:400]:
            m = rx.search(head)
            if m:
                out.add(round(float(m.group(1)), 3))
    return out


class Bank:
    """One template bank over a key set and rotation policy at one scale: z-scored rows and each row's key."""

    def __init__(self, keys: list, scale: float, rotate):
        self.keys = keys
        rows, owner = [], []
        W, h, sh, mask = mge.geom(scale)
        m = mask > 0
        for i, key in enumerate(keys):
            rots = mge.ROTS if (rotate is True or (rotate is not False and key in rotate)) else [0]
            for si in range(len(mge.sources(key))):
                for c in mge.CANVAS * scale:
                    for rot in rots:
                        T = mge.place(mge.template(key, float(round(c)), rot, si), W)
                        if T[m].std() < 1e-3:
                            continue
                        rows.append(T[m])
                        owner.append(i)
        self.T = mge.zrows(np.array(rows, np.float32))
        self.owner = np.array(owner)
        self.n = len(rows)

    def score(self, P: np.ndarray) -> np.ndarray:
        S = mge.zrows(P) @ self.T.T
        per = np.full(len(self.keys), -2.0, np.float32)
        np.maximum.at(per, self.owner, S.max(0))
        return per


def stored_prior() -> dict:
    """The prior's share at the ability pass's own cadence, from storage only: per session with a stored
    `ability_icon` stream, the share of each read frame's candidates within 2 px x widget scale of a candidate of
    the read frame before it (gap <= 600 ms), the candidates per read frame and the share of verify rows kept."""
    out = {}
    for f in sorted((mge.STORE / "events" / "ability_icon").glob("*.jsonl")):
        rows = [json.loads(ln) for ln in open(f, encoding="utf-8")]
        ws = rows[0]["map_scale"]["widget_scale"]
        fr = [r for r in rows[1:] if r.get("kind") == "frame" and r.get("reason") is None]
        car = tot = ver = kept = 0
        for a, b in zip(fr, fr[1:]):
            if b.get("verify"):
                ver += len(b["verify"]["rows"])
                kept += sum(v["score"] is not None for v in b["verify"]["rows"])
            if abs(b["t_ms"] - a["t_ms"]) > 600 or not b["candidates"]:
                continue
            Q = np.array([[c["cx"], c["cy"]] for c in b["candidates"]], float)
            tot += len(Q)
            if a["candidates"]:
                P = np.array([[c["cx"], c["cy"]] for c in a["candidates"]], float)
                car += int((np.hypot(Q[:, None, 0] - P[None, :, 0], Q[:, None, 1] - P[None, :, 1]).min(1)
                            <= PRIOR_R * ws).sum())
        n = [len(r["candidates"]) for r in fr]
        out[f.stem] = {"version": rows[0]["ability_icon_version"], "hz": rows[0]["hz"], "widget_scale": ws,
                       "read_frames": len(fr), "candidates_per_frame_median": float(np.median(n)) if n else None,
                       "prior_share": round(car / max(tot, 1), 4), "carried": car, "candidates": tot,
                       "verify_kept": round(kept / max(ver, 1), 4), "verify_rows": ver}
    return out


ANSWERS_ON = mge.STORE / "analysis" / "minimap-glyphs-answers-20261004" / "answers-on"


def fresh(f: Path) -> Path:
    """`f`, refusing when it exists: a stored output is evidence and is never overwritten."""
    if f.exists():
        raise SystemExit(f"{f} exists; write each run to a new --out directory")
    return f


def recorded(part: str, field: str, value: str) -> bool:
    """True when the metric log holds a glyph_channel_cost/`part` row whose context `field` equals `value`."""
    from reticle import metrics
    return any(r.get("tool") == "glyph_channel_cost" and r.get("part") == part
               and str((r.get("context") or {}).get(field)) == value for r in metrics.load())


def cmd_rotation(out: Path) -> None:
    """Single-frame top-1 on the stored answers-on windows (no cache; the contaminated set, never a gate) under
    three rotation arms, then with the candidate set widened from the labelled caster's kit to the session's
    ally candidate set (`candidate_agents`). Predictions W10 and W11."""
    import copy
    d, z = mge.load_scores(ANSWERS_ON)
    rot, _ = rotating_keys()
    mge.ROTATING = rot
    rep = {"version": VERSION, "base": d["meta"]["version"], "windows": str(ANSWERS_ON), "rotating": len(rot)}
    fn = lambda P, T, s, meta, r: mge.pearson(P, T)  # noqa: E731
    for tag, arm in (("rotate_all", True), ("upright", False), ("gamedata_policy", "policy")):
        eng = mge.Engine(d, z, rotate=arm)
        sc = eng.run(fn)
        rep[tag] = {sp: mge.verdicts(sc, eng.items, sp)["top1"] for sp in ("heldout", "dev")}
        print(tag, rep[tag], flush=True)
    all_keys = sorted(k for k in mge.GLYPHS if k[1] in "CQEX")
    d2 = copy.deepcopy(d)
    keep, outside, why = [], 0, {}
    for r in d2["items"]:
        if r.get("refused") or not r.get("kit") or r["split"] != "heldout" or \
                not (mge.STORE / "lineups" / f"{r['sid']}.json").exists():
            continue
        if r["sid"] not in why:
            why[r["sid"]] = candidate_agents(r["sid"])
        agents = why[r["sid"]][0]
        r["kit"] = [f"{k[0]}:{k[1]}" for k in all_keys if k[0] in agents]
        outside += bool(r.get("truth")) and r["truth"].split(":")[0] not in agents
        keep.append(r)
    d2["items"] = keep
    for tag, arm in (("rotate_all", True), ("gamedata_policy", "policy")):
        ids = {k["win_index"] for k in keep}
        e_k = mge.Engine({"items": [x for x in d["items"] if not x.get("refused") and x.get("win_index") in ids]},
                         z, rotate=arm)
        kit_sc = e_k.run(fn)
        e_a = mge.Engine(d2, z, rotate=arm)
        ally_sc = e_a.run(fn)
        P = [r for r in mge.positives(keep, "heldout") if r["win_index"] in ally_sc and r["win_index"] in kit_sc]

        def top(sc, r):
            return max(sc[r["win_index"]], key=lambda k: sc[r["win_index"]][k][0])
        rep[f"ally_set_{tag}"] = {
            "items": len(P), "truth_outside_set": int(outside),
            "caster_kit_right": sum(top(kit_sc, r) == r["truth"] for r in P),
            "ally_set_right": sum(top(ally_sc, r) == r["truth"] for r in P),
            "ally_set_agent_right": sum(top(ally_sc, r).split(":")[0] == r["truth"].split(":")[0] for r in P),
            "lost": sorted(f"{r['sid']} {r['t_ms'] / 1000:.2f}s {r['truth']}->{top(ally_sc, r)}" for r in P
                           if top(kit_sc, r) == r["truth"] != top(ally_sc, r)),
            "candidate_sets": {s: w[1] for s, w in why.items()}}
        print(f"ally_set_{tag}", {k: v for k, v in rep[f'ally_set_{tag}'].items() if k != 'candidate_sets'}, flush=True)
    json.dump(rep, open(fresh(out / "rotation.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("wrote", out / "rotation.json")


TEX_RX = re.compile(r"(TX_[A-Za-z0-9_]+?)(?:\.png|')")
MINIMAP_COMPONENT_RX = re.compile(r"Minimap", re.I)
KILLJOY_REFS_DEV = mge.STORE / "analysis" / "minimap-glyphs-killjoy-refs-20261004" / "gamedata-on" / "items.json"


def rule_verdict(c: dict) -> str:
    """The two-flag hypothesis for one minimap component (merged down its class chain): RotationSource Upright
    forces upright; another RotationSource (Custom, Rotation, None) leaves the verdict undetermined; else the icon
    turns iff bRotates XOR RotationSpace == ConstantMinimap. A hypothesis under test, never a domain fact."""
    src = str(c.get("RotationSource") or "")
    if src.endswith("AMRSRC_Upright"):
        return "upright"
    if src:
        return "undetermined"
    return "rotates" if bool(c.get("bRotates")) != str(c.get("RotationSpace") or "").endswith("ConstantMinimap") \
        else "upright"


def minimap_components() -> list[dict]:
    """Every minimap component of the ability-states export that names a texture: package, component, class,
    the three rotation flags (merged down the class chain, then the component class's own defaults) and the
    textures it names."""
    import ability_states_gamedata as asg
    root = asg.EXP / "ShooterGame" / "Content" / "Characters"
    out = []
    for f in sorted(root.rglob("*.json")):
        if not MINIMAP_COMPONENT_RX.search(f.read_text(encoding="utf-8", errors="ignore")):
            continue
        pkg = "/Game/" + str(f.relative_to(asg.EXP / "ShooterGame" / "Content")).replace("\\", "/")[:-5]
        if not asg.bp(pkg).ok:
            continue
        for name, c in asg.merged_components(pkg).items():
            if not MINIMAP_COMPONENT_RX.search(c["type"] or ""):
                continue
            props = dict(c["props"])
            for k, v in asg.comp_defaults(c.get("class_path")).items():
                props.setdefault(k, v)
            tex = sorted(set(TEX_RX.findall(json.dumps(props))))
            if tex:
                out.append({"pkg": pkg, "component": name, "type": c["type"], "textures": tex,
                            "bRotates": props.get("bRotates"), "RotationSpace": props.get("RotationSpace"),
                            "RotationSource": props.get("RotationSource"), "verdict": rule_verdict(props)})
    return out


def texture_keys() -> dict:
    """{texture name: {catalogue key}} for every reference the matcher scores (build_extra, answers on), plus each
    ability-states-gamedata-0.2.0 minimap row's texture joined to its key by display name (as `rotating_keys`);
    the second join covers textures eval 0.2.0 does not score, such as Killjoy's Q_InActive."""
    mge.build_extra(mge.PROBE_STATES, answers=True)
    out: dict = {}
    for key, refs in mge.EXTRA.items():
        for _g, prov in refs:
            for t in TEX_RX.findall(prov):
                out.setdefault(t, set()).add(f"{key[0]}:{key[1]}")
    for ln in open(STATES_TABLE, encoding="utf-8"):
        r = json.loads(ln)
        if not r["cue_type"].startswith("minimap_") or not r.get("png"):
            continue
        names = [n for n in re.split(r"\s*/\s*", r["ability"] or "") if n]
        hit = next((k for n in names for k in [mge.find(r["agent"], n)] if k), None)
        if hit:
            out.setdefault(Path(r["png"]).stem, set()).add(f"{hit[0]}:{hit[1]}")
    return out


def rotation_answers() -> dict:
    """{key: answer} from the rotation rows (last row wins): rotates, upright, unsure, or the player's own
    words for `other`."""
    out = {}
    for ln in mge.ANSWERS.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("kind") == "rotation":
                out[r["key"].split(":", 1)[1]] = ("unsure" if r.get("unsure") else
                                                  r["answer"] if r["answer"] != "other" else f"other: {r['other']}")
    return out


def fitted_angles(path: Path = KILLJOY_REFS_DEV, split: str = "dev") -> dict:
    """{key: [(fitted rotation of the truth key, rotated minus upright truth score)]} over the right items of
    `split` (the rotate-all verdict equals the truth)."""
    out: dict = {}
    for r in json.load(open(path, encoding="utf-8"))["items"]:
        t = r.get("truth")
        if r.get("refused") or r["split"] != split or not t or r.get("rot_pred") != t or t not in r.get("rot_fits", {}):
            continue
        out.setdefault(t, []).append((int(r["rot_fits"][t][1]), round(r["rot_scores"][t] - r["norot_scores"][t], 4)))
    return out


def near_zero(a: int, tol: int = 15) -> bool:
    return min(a % 360, 360 - a % 360) <= tol


def rule_per_key(comps: list[dict], tk: dict) -> tuple[dict, dict]:
    """({key: [component evidence]}, {key: two-flag verdict}): each catalogue key's minimap components, joined by
    the textures they name (`texture_keys`), and the rule's verdict over them; one verdict when every component
    agrees, `mixed` otherwise. A key no component draws has no entry."""
    per_key: dict = {}
    for c in comps:
        for t in c["textures"]:
            for k in tk.get(t, ()):
                per_key.setdefault(k, []).append({**{x: c[x] for x in ("pkg", "component", "bRotates", "RotationSpace",
                                                                       "RotationSource", "verdict")}, "texture": t})
    verdict = {k: (lambda v: v.pop() if len(v) == 1 else "mixed")({r["verdict"] for r in rs}) for k, rs in per_key.items()}
    return per_key, verdict


def cmd_rotrule(out: Path) -> None:
    """The two-flag rotation hypothesis (prediction rows G1-G4): its verdict per catalogue key from the raw
    export's minimap components, checked against the player's rotation answers and the dev fitted angles, and its
    per-key policy scored single frame on the contaminated answers-on windows beside an upright control."""
    comps = minimap_components()
    per_key, verdict = rule_per_key(comps, texture_keys())
    ans = rotation_answers()
    ang = fitted_angles()
    check = {}
    for k, a in sorted(ans.items()):
        said = "rotates" if a.startswith("other") and "normal to the wall" in a else a
        v = verdict.get(k, "no_component")
        comp_v = sorted({r["verdict"] for r in per_key.get(k, [])})
        check[k] = {"answer": a, "answer_as": said, "rule": v, "component_verdicts": comp_v,
                    "agrees": None if said == "unsure" else v == said,
                    "agrees_some_component": None if said == "unsure" else said in comp_v}
    sure = [c for c in check.values() if c["agrees"] is not None]
    dev = {}
    for k, xs in sorted(ang.items()):
        dev[k] = {"rule": verdict.get(k, "no_component"), "n": len(xs), "angles": sorted(a for a, _ in xs),
                  "near_zero": sum(near_zero(a) for a, _ in xs),
                  "gain_median": round(float(np.median([g for _, g in xs])), 4)}
    side = {}
    for tag in ("upright", "rotates"):
        ks = [k for k, d in dev.items() if d["rule"] == tag]
        n = sum(dev[k]["n"] for k in ks)
        side[tag] = {"keys": ks, "items": n, "near_zero": sum(dev[k]["near_zero"] for k in ks),
                     "share": round(sum(dev[k]["near_zero"] for k in ks) / n, 4) if n else None}
    rep = {"version": VERSION, "rule": rule_verdict.__doc__.split(".")[0], "components": len(comps),
           "keys_with_component": len(verdict), "verdicts": dict(sorted(verdict.items())),
           "evidence": {k: per_key[k] for k in sorted(per_key)}, "answers": check,
           "answers_sure": len(sure), "answers_agree": sum(c["agrees"] for c in sure),
           "answers_agree_some_component": sum(c["agrees_some_component"] for c in sure), "dev_angles": dev,
           "dev_sides": side}
    d, z = mge.load_scores(ANSWERS_ON)
    rot = {tuple(k.split(":")) for k, v in verdict.items() if v != "upright"}
    mge.ROTATING = rot
    fn = lambda P, T, s, meta, r: mge.pearson(P, T)  # noqa: E731
    for tag, arm in (("upright", False), ("two_flag_policy", "policy")):
        eng = mge.Engine(d, z, rotate=arm)
        sc = eng.run(fn)
        rep[tag] = {sp: mge.verdicts(sc, eng.items, sp)["top1"] for sp in ("heldout", "dev")}
        print(tag, rep[tag], flush=True)
    rep["two_flag_rotating"] = sorted(f"{a}:{b}" for a, b in rot)
    f = fresh(out / "rotrule.json")
    json.dump(rep, open(f, "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({k: rep[k] for k in ("components", "keys_with_component", "answers_sure", "answers_agree",
                                          "answers_agree_some_component",
                                          "dev_sides", "upright", "two_flag_policy")}, default=str))
    print("wrote", f)


HELDOUT_RUNS = {"heldout_020": mge.STORE / "analysis" / "minimap-heldout-score-20261004" / "heldout.json",
                "heldout_030": mge.STORE / "analysis" / "minimap-heldout-score-killjoy-refs-k5-20261004" / "heldout.json"}


def corrected_truths(marks: list[dict]) -> list[dict]:
    """The marks with each named truth replaced by the latest label row of its item (last row wins), matched by
    position within 3 px; the Chamber correction (ccff4a11ff5a) is the only later row today. Biased upward: the
    player was re-asked only where the matcher disagreed."""
    latest = {}
    for f in sorted((mge.LABELS / "minimap_glyph_heldout").glob("*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            if ln.strip():
                r = json.loads(ln)
                latest[r["key"]] = r
    out = []
    for m in marks:
        m = dict(m)
        r = latest.get(m["item"])
        if r and m["class"] == "named":
            near = sorted((q for q in r["marks"] if np.hypot(q["x"] - m["x"], q["y"] - m["y"]) <= 3 and q.get("ability")),
                          key=lambda q: (round(float(np.hypot(q["x"] - m["x"], q["y"] - m["y"])), 2),
                                         q["ability"] != m["truth"]))   # overlapping marks: nearest, then same truth
            if near and ":" in near[0]["ability"]:
                m["truth"] = near[0]["ability"]
        out.append(m)
    return out


def cmd_record2(rotrule_dir: Path) -> None:
    """Record the 0.2.0 parts. `rotation_rule`: rotrule.json under `rotrule_dir` (answers agreeing, dev angles,
    the policy against the upright control). `heldout_020`, `heldout_030`: the stored clean held-out runs
    (minimap-heldout-score-20261004 and killjoy-refs K5): headline and dev_session follow counts, the two leading
    confusions, the proposer's raw recall of icon marks, and the headline under the corrected labels. Reads only;
    reruns nothing."""
    from reticle import metrics
    if recorded("rotation_rule", "run", str(rotrule_dir)):
        raise SystemExit(f"{rotrule_dir} is already recorded; a rerun would append duplicate rows")
    rr = json.load(open(rotrule_dir / "rotrule.json", encoding="utf-8"))
    num = lambda s: int(s.split("/")[0])  # noqa: E731
    vals = {"answers_sure": rr["answers_sure"], "answers_agree": rr["answers_agree"],
            "answers_agree_some_component": rr["answers_agree_some_component"],
            "keys_with_component": rr["keys_with_component"], "rotating_keys": len(rr["two_flag_rotating"]),
            "mixed_keys": sum(v == "mixed" for v in rr["verdicts"].values()),
            "dev_rotates_items": rr["dev_sides"]["rotates"]["items"],
            "dev_rotates_near_zero": rr["dev_sides"]["rotates"]["near_zero"],
            "dev_upright_items": rr["dev_sides"]["upright"]["items"],
            "heldout_policy": num(rr["two_flag_policy"]["heldout"]), "dev_policy": num(rr["two_flag_policy"]["dev"]),
            "heldout_upright": num(rr["upright"]["heldout"]), "dev_upright": num(rr["upright"]["dev"])}
    metrics.record("glyph_channel_cost", part="rotation_rule", values=vals,
                   deps={"version": VERSION, "build": "release-13.06-shipping-18-5590001",
                         "states_table": STATES_TABLE.name, "answers": "answers.jsonl rotation rows, last wins"},
                   context={"run": str(rotrule_dir), "windows": str(ANSWERS_ON), "contaminated": True,
                            "dev_angles": str(KILLJOY_REFS_DEV)},
                   controls=[{"name": "upright arm reproduces rotation.json (157/192 heldout windows)",
                              "observed": vals["heldout_upright"], "expected": 157, "tol": 0},
                             {"name": "upright arm reproduces rotation.json (35/59 dev)",
                              "observed": vals["dev_upright"], "expected": 35, "tol": 0}])
    print("rotation_rule", json.dumps(vals))
    for part, f in HELDOUT_RUNS.items():
        d = json.load(open(f, encoding="utf-8"))
        h = mge.naming_summary(d["marks"], "headline")
        dv = mge.naming_summary(d["marks"], "dev_session")
        hc = mge.naming_summary(corrected_truths(d["marks"]), "headline")
        det = mge.detection_summary(d["frames"], "headline")
        vals = {"headline_n": h["n"], "headline_follow_right": h["follow"]["right"],
                "headline_base_right": h["base"]["right"], "headline_refused": h["follow"]["refused"],
                "dev_session_n": dv["n"], "dev_session_follow_right": dv["follow"]["right"],
                "astra_e_to_q": h["confusions"].get("Astra:E -> Astra:Q", 0),
                "omen_e_to_q": h["confusions"].get("Omen:E -> Omen:Q", 0),
                "icon_marks": det["icon_marks"], "found_raw": det["found_raw"],
                "corrected_headline_follow_right": hc["follow"]["right"]}
        print(part, json.dumps(vals))
        metrics.record("glyph_channel_cost", part=part, values=vals,
                       deps={"version": VERSION, "run": d["meta"]["version"], "matcher": d["meta"]["matcher"],
                             "follow": d["meta"]["follow"], "queue": d["meta"]["queue"]},
                       context={"file": str(f), "corrected": "labels/minimap_glyph_heldout last row per item"})


def cmd_baseline030() -> None:
    """Stage 1's S1 baseline: single-frame top-1 of rotate-all (`rot_pred`) and upright (`norot_pred`) on the
    labelled dev items of minimap-glyph-eval-0.3.0, gamedata on, as stored; recorded as
    `glyph_channel_cost/dev_030`. Reads only."""
    from reticle import metrics
    if recorded("dev_030", "file", str(KILLJOY_REFS_DEV)):
        raise SystemExit(f"{KILLJOY_REFS_DEV} is already recorded as dev_030")
    d = json.load(open(KILLJOY_REFS_DEV, encoding="utf-8"))
    dev = [r for r in d["items"] if r["split"] == "dev" and r.get("truth") and not r.get("refused")]
    vals = {"dev_n": len(dev), "dev_rotate_all": sum(r.get("rot_pred") == r["truth"] for r in dev),
            "dev_upright": sum(r.get("norot_pred") == r["truth"] for r in dev)}
    print("dev_030", json.dumps(vals))
    metrics.record("glyph_channel_cost", part="dev_030", values=vals,
                   deps={"version": VERSION, "eval": d["meta"]["version"], "build": d["meta"].get("build"),
                         "gamedata": d["meta"].get("gamedata")},
                   context={"file": str(KILLJOY_REFS_DEV), "single_frame": True, "split": "dev"})


CROSS_CASTS = mge.STORE / "analysis" / "cross-channel-independence-20261004" / "casts.jsonl"
GLYPH_SLOTS_SEEN = {("Sova", "C"), ("Skye", "Q"), ("Skye", "E"), ("Skye", "X")}


def cmd_crosscheck(path: Path = CROSS_CASTS) -> None:
    """On the matches' own casts of abilities that draw a glyph (`B_source == "glyph"`, chosen there from domain
    facts and game data), count the audio witness's verdicts (`A`: right, wrong, refused) and the glyph follow's
    (seeded at the self icon), overall and for Sova:C and Skye:Q/E/X; recorded as
    `glyph_channel_cost/cross_channel@matches`. Precision is right over named (right plus wrong). Reads only."""
    from reticle import metrics
    if recorded("cross_channel", "file", str(path)):
        raise SystemExit(f"{path} is already recorded as cross_channel")
    rows = [json.loads(ln) for ln in open(path, encoding="utf-8") if ln.strip()]
    g = [r for r in rows if r["kind"] == "match" and r["B_source"] == "glyph"]
    sub = [r for r in g if (r["agent"], r["slot"]) in GLYPH_SLOTS_SEEN]

    def counts(rs, f, tag):
        right = sum(r[f] == "right" for r in rs)
        wrong = sum(r[f] == "wrong" for r in rs)
        return {f"{tag}_n": len(rs), f"{tag}_right": right, f"{tag}_wrong": wrong,
                f"{tag}_refused": sum(r[f] == "refused" for r in rs),
                f"{tag}_precision": round(right / (right + wrong), 4) if right + wrong else None}
    vals = {**counts(g, "A", "audio"), **counts(sub, "A", "audio_sova_skye"), **counts(g, "glyph", "glyph_self_seed")}
    print("cross_channel", json.dumps(vals))
    metrics.record("glyph_channel_cost", part="cross_channel", session="matches", values=vals,
                   deps={"version": VERSION, "casts": rows[0]["version"]},
                   context={"file": str(path), "branch": "cross-channel-independence-20261004",
                            "audio": "ability-audio-0.4.0 / params-0.2.6, recomputed there",
                            "glyph": "minimap_glyph_eval follow seeded at the self icon"})


def cmd_births(out: Path, sid: str = "c40d950031bb", n: int = 100) -> None:
    """New discs at the ability pass's 2 Hz and what a first-frame glyph gate keeps (W12, W13): `n` stored
    ability_icon read frames evenly spaced, each with the read frame before it; each frame read alone from the
    crop cache (timed); each new disc scored against the ally candidate set, rotate-all."""
    rows = [json.loads(ln) for ln in open(mge.STORE / "events" / "ability_icon" / f"{sid}.jsonl", encoding="utf-8")]
    ws = rows[0]["map_scale"]["widget_scale"]
    fr = [r for r in rows[1:] if r.get("kind") == "frame" and r.get("reason") is None]
    pairs = [(a, b) for a, b in zip(fr, fr[1:]) if abs(b["t_ms"] - a["t_ms"]) <= 600]
    pick = [pairs[int(i)] for i in np.linspace(0, len(pairs) - 1, n)]
    c, why, man = mge.crop_cache(sid)
    x0, y0, x1, y1 = c.rect_of("minimap")
    mge.build_extra(mge.PROBE_STATES, answers=True)
    agents, _ = candidate_agents(sid)
    keys = sorted(k for k in mge.GLYPHS if k[1] in "CQEX" and k[0] in agents)
    bank, scale, read_ms, best, n_new, n_all = None, None, [], [], 0, 0
    for a, b in pick:
        P = np.array([[q["cx"], q["cy"]] for q in a["candidates"]], float).reshape(-1, 2)
        new = [q for q in b["candidates"]
               if not len(P) or np.hypot(P[:, 0] - q["cx"], P[:, 1] - q["cy"]).min() > PRIOR_R * ws]
        n_all += len(b["candidates"])
        n_new += len(new)
        t0 = time.perf_counter()
        got = [s.frame[y0:y1, x0:x1] for s in c.samples([b["t_ms"]], rois=["minimap"])]
        read_ms.append((time.perf_counter() - t0) * 1e3)
        if not got or not new:
            continue
        crop = got[0]
        if bank is None:
            scale = crop.shape[1] / 465.0
            bank = Bank(keys, scale, True)
        Y = mge.luma(crop)
        sh = mge.geom(scale)[2]
        for q in new:
            Pq = mge.window_patches(Y, (q["cx"], q["cy"]), scale, sh)
            if Pq is not None:
                best.append(float(bank.score(Pq).max()))
    best = np.array(best)
    rep = {"version": VERSION, "session": sid, "capture": man.get("source"), "frames": len(pick),
           "candidates": n_all, "new": n_new, "scored_new": int(len(best)),
           "new_at_or_above_icon_score": int((best >= 0.4).sum()),
           "share_at_or_above": round(float((best >= 0.4).mean()), 4) if len(best) else None,
           "best_score_quartiles": [round(float(v), 3) for v in np.percentile(best, [25, 50, 75])] if len(best) else None,
           "read_ms": {"median": round(float(np.median(read_ms)), 3), "p90": round(float(np.percentile(read_ms, 90)), 3)}}
    print(json.dumps(rep, indent=1, default=str))
    json.dump(rep, open(fresh(out / "births.json"), "w", encoding="utf-8"), indent=1, default=str)


def cmd_record(out: Path) -> None:
    """Record the three runs' summaries (cost.json, rotation.json, births.json under `out`) as metric series
    `glyph_channel_cost/<part>[@session]`, so the design document cites them by token."""
    from reticle import metrics
    deps = {"version": VERSION, "base": mge.VERSION, "build": mge.BUILD, "states_table": STATES_TABLE.name,
            "matcher": metrics.fingerprint(list(mge.CANVAS), mge.MASK_R, mge.SHIFT, list(mge.ROTS), PRIOR_R)}
    cost = json.load(open(out / "cost.json", encoding="utf-8"))
    for sid, v in cost["sessions"].items():
        s = v["summary"]
        pf = s["per_frame_ms"]
        vals = {"propose_ms": pf["propose_ms"]["median"], "verify_ms": pf["verify_ms"]["median"],
                "luma_ms": pf["luma_ms"]["median"],
                "bank_a_ms": pf["A_ally_rotate_all_ms"]["median"], "bank_b_ms": pf["B_ally_gamedata_rotation_ms"]["median"],
                "bank_c_ms": pf["C_all_agents_gamedata_rotation_ms"]["median"],
                "bank_a_gpu_ms": pf["A_ally_rotate_all_gpu_ms"]["median"],
                "bank_a_ms_per_disc": s["per_disc_ms"]["A_ally_rotate_all"],
                "bank_b_ms_per_disc": s["per_disc_ms"]["B_ally_gamedata_rotation"],
                "bank_c_ms_per_disc": s["per_disc_ms"]["C_all_agents_gamedata_rotation"],
                "templates_a": s["templates"]["A_ally_rotate_all"], "templates_b": s["templates"]["B_ally_gamedata_rotation"],
                "templates_c": s["templates"]["C_all_agents_gamedata_rotation"],
                "keys_a": s["keys"]["A_ally_rotate_all"], "keys_c": s["keys"]["C_all_agents_gamedata_rotation"],
                "discs_per_frame": s["discs_per_frame"]["median"], "prior_share": s["prior_share"],
                "hold_gap_ms": s["hold_gap_ms"]["median"], "frames": s["frames"]}
        metrics.record("glyph_channel_cost", part="cost", session=sid, values=vals, deps=deps,
                       context={"frames": s["frames"], "crop_px": s["crop_px"], "gpu": s["gpu"]})
    for sid, v in cost.get("stored_prior_2hz", {}).items():
        metrics.record("glyph_channel_cost", part="prior2hz", session=sid,
                       values={k: v[k] for k in ("prior_share", "candidates_per_frame_median", "verify_kept",
                                                 "read_frames")},
                       deps={**deps, "ability_icon": v["version"]}, context={"hz": v["hz"]})
    rot = json.load(open(out / "rotation.json", encoding="utf-8"))
    vals = {}
    for tag in ("rotate_all", "upright", "gamedata_policy"):
        for sp in ("heldout", "dev"):
            vals[f"{sp}_{tag}"] = int(rot[tag][sp].split("/")[0])
    vals["heldout_n"], vals["dev_n"] = int(rot["rotate_all"]["heldout"].split("/")[1]), int(rot["rotate_all"]["dev"].split("/")[1])
    for tag in ("rotate_all", "gamedata_policy"):
        a = rot[f"ally_set_{tag}"]
        for k in ("items", "caster_kit_right", "ally_set_right", "ally_set_agent_right", "truth_outside_set"):
            vals[f"ally_{tag}_{k}"] = a[k]
    metrics.record("glyph_channel_cost", part="rotation", values=vals, deps=deps,
                   context={"windows": rot["windows"], "contaminated": True})
    items = json.load(open(ANSWERS_ON / "items.json", encoding="utf-8"))["items"]
    pos = [r["rot_score"] for r in items if not r.get("refused") and r.get("truth") and r.get("rot_score") is not None
           and r["cat"] not in ("NOT", "smoke")]
    neg = [r["rot_score"] for r in items if not r.get("refused") and r["cat"] == "NOT" and r.get("rot_score") is not None]
    q = lambda v, p: round(float(np.percentile(v, p)), 3)  # noqa: E731
    metrics.record("glyph_channel_cost", part="null",
                   values={"pos_n": len(pos), "pos_p10": q(pos, 10), "pos_p50": q(pos, 50),
                           "not_n": len(neg), "not_p50": q(neg, 50), "not_p90": q(neg, 90),
                           "not_at_or_above_04": round(float(np.mean(np.array(neg) >= 0.4)), 4)},
                   deps=deps, context={"windows": str(ANSWERS_ON), "bank": "labelled caster kit, rotate-all"})
    b = json.load(open(out / "births.json", encoding="utf-8"))
    metrics.record("glyph_channel_cost", part="births", session=b["session"],
                   values={"new": b["new"], "candidates": b["candidates"], "new_at_or_above": b["new_at_or_above_icon_score"],
                           "best_q50": b["best_score_quartiles"][1], "read_ms": b["read_ms"]["median"],
                           "frames": b["frames"]}, deps=deps, context={"icon_score": 0.4})
    print(metrics.report(tool="glyph_channel_cost"))


def cmd_table() -> None:
    """Count what ability-states-gamedata-0.2.0 says of minimap drawings (rows whose cue_type starts `minimap_`)
    and record it as `glyph_channel_cost/gamedata_minimap`: rows, abilities, rows and abilities with an exported
    png, abilities with a teammate-view or enemy-view row, and abilities with a bRotates or ConstantMinimap row."""
    from reticle import metrics
    mm = [r for r in (json.loads(ln) for ln in open(STATES_TABLE, encoding="utf-8"))
          if r["cue_type"].startswith("minimap_")]
    ab = lambda rs: {(r["agent"], r["key"]) for r in rs}  # noqa: E731
    props = lambda r: r.get("minimap_props") or {}  # noqa: E731
    vals = {"minimap_rows": len(mm), "minimap_abilities": len(ab(mm)),
            "rows_with_png": sum(bool(r.get("png")) for r in mm),
            "abilities_with_png": len(ab([r for r in mm if r.get("png")])),
            "teammate_view_abilities": len(ab([r for r in mm if (r.get("views") or {}).get("teammate") is True])),
            "enemy_view_abilities": len(ab([r for r in mm if (r.get("views") or {}).get("enemy") is True])),
            "brotates_abilities": len(ab([r for r in mm if props(r).get("bRotates")])),
            "constant_minimap_abilities": len(ab([r for r in mm if "ConstantMinimap" in str(props(r).get("RotationSpace"))]))}
    print(json.dumps(vals))
    metrics.record("glyph_channel_cost", part="gamedata_minimap", values=vals,
                   deps={"version": VERSION, "states_table": STATES_TABLE.name}, context={})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="cost", choices=("cost", "rotation", "births", "record", "table",
                                                                   "rotrule", "record2", "baseline030", "crosscheck"))
    ap.add_argument("--sessions", default="c40d950031bb,a06f04a0059f")
    ap.add_argument("--windows", type=int, default=10)
    ap.add_argument("--per", type=int, default=10)
    ap.add_argument("--out", default=None, help="output dir; required except for table, baseline030, crosscheck")
    ap.add_argument("--no-gpu", action="store_true")
    a = ap.parse_args()
    if a.cmd == "table":
        cmd_table()
        return
    if a.cmd == "baseline030":
        cmd_baseline030()
        return
    if a.cmd == "crosscheck":
        cmd_crosscheck()
        return
    if not a.out:
        ap.error("--out is required for " + a.cmd)
    out = Path(a.out)
    writes = {"cost": "cost.json", "rotation": "rotation.json", "births": "births.json", "rotrule": "rotrule.json"}
    if a.cmd in writes:
        fresh(out / writes[a.cmd])   # refuse before any work, not after it
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "rotation":
        cmd_rotation(out)
        return
    if a.cmd == "births":
        cmd_births(out)
        return
    if a.cmd == "record":
        cmd_record(out)
        return
    if a.cmd == "rotrule":
        cmd_rotrule(out)
        return
    if a.cmd == "record2":
        cmd_record2(out)
        return
    from reticle import ability_icons

    mge.build_extra(mge.PROBE_STATES, answers=True)
    rot, rot_unmatched = rotating_keys()
    all_keys = sorted(k for k in mge.GLYPHS if k[1] in "CQEX")
    torch = None
    if not a.no_gpu:
        try:
            import torch as _t
            if _t.cuda.is_available():
                torch = _t
                torch.set_num_threads(1)
        except ImportError:
            torch = None
    res = {"version": VERSION, "base": mge.VERSION, "build": mge.BUILD, "states_table": STATES_TABLE.name,
           "rotating_keys": sorted(f"{k[0]}:{k[1]}" for k in rot), "rotating_unmatched": rot_unmatched,
           "sessions": {}}
    for sid in a.sessions.split(","):
        c, why, man = mge.crop_cache(sid)
        if c is None:
            res["sessions"][sid] = {"refused": why}
            continue
        x0, y0, x1, y1 = c.rect_of("minimap")
        holds = np.asarray(sorted(c.holds()), float)
        drawn = drawn_times(sid)
        dh = [float(t) for t in holds if round(float(t), 3) in drawn]
        idx = [int(round(q * (len(dh) - a.per))) for q in np.linspace(0.05, 0.95, a.windows)]
        want = sorted({dh[i + j] for i in idx for j in range(a.per)})
        got = {s.t_ms: s.frame[y0:y1, x0:x1].copy() for s in c.samples(want, rois=["minimap"])}
        first = next(iter(got.values()))
        scale = first.shape[1] / 465.0
        terms = mge.icon_terms(sid, first.shape)
        agents, agent_why = candidate_agents(sid)
        keys_ally = sorted(k for k in all_keys if k[0] in agents)
        t0 = time.perf_counter()
        banks = {"A_ally_rotate_all": Bank(keys_ally, scale, True),
                 "B_ally_gamedata_rotation": Bank(keys_ally, scale, rot),
                 "C_all_agents_gamedata_rotation": Bank(all_keys, scale, rot)}
        build_s = time.perf_counter() - t0
        gT = gown = None
        if torch is not None:
            bA = banks["A_ally_rotate_all"]
            gT = torch.from_numpy(bA.T).cuda()
            gown = torch.from_numpy(bA.owner).cuda()
            for _ in range(3):                                  # warm the kernels the timed path uses
                Sw = (torch.randn(2 * 49, bA.T.shape[1], device="cuda") @ gT.T).view(2, 49, -1).amax(1)
                pw = torch.full((2, len(keys_ally)), -2.0, device="cuda")
                pw.scatter_reduce_(1, gown.expand(2, -1), Sw, reduce="amax")
                pw.cpu()
            torch.cuda.synchronize()
        sh = mge.geom(scale)[2]
        rows, prev = [], None
        for wi, i in enumerate(idx):
            prev = None
            for j in range(a.per):
                t = dh[i + j]
                if t not in got:
                    continue
                crop = got[t]
                r = {"window": wi, "t_ms": t}
                q0 = time.perf_counter()
                Y = mge.luma(crop)
                q1 = time.perf_counter()
                discs = ability_icons.propose_icons(crop, terms)[:ability_icons.MAX_CANDIDATES]
                q2 = time.perf_counter()
                r.update(luma_ms=(q1 - q0) * 1e3, propose_ms=(q2 - q1) * 1e3, discs=len(discs))
                Ps = [mge.window_patches(Y, (d["cx"], d["cy"]), scale, sh) for d in discs]
                Ps = [P for P in Ps if P is not None]
                r["scored_discs"] = len(Ps)
                for name, b in banks.items():
                    s0 = time.perf_counter()
                    for P in Ps:
                        b.score(P)
                    r[f"{name}_ms"] = (time.perf_counter() - s0) * 1e3
                if gT is not None:
                    g0 = time.perf_counter()
                    if Ps:
                        n_sh = Ps[0].shape[0]
                        Z = torch.from_numpy(mge.zrows(np.concatenate(Ps))).cuda()
                        S = (Z @ gT.T).view(len(Ps), n_sh, -1).amax(1)
                        per = torch.full((len(Ps), len(keys_ally)), -2.0, device="cuda")
                        per.scatter_reduce_(1, gown.expand(len(Ps), -1), S, reduce="amax")
                        per.cpu()
                    r["A_ally_rotate_all_gpu_ms"] = (time.perf_counter() - g0) * 1e3
                if prev is not None:
                    v0 = time.perf_counter()
                    ability_icons.verify_icons(crop, terms, prev)
                    r["verify_ms"] = (time.perf_counter() - v0) * 1e3
                    near = sum(any(np.hypot(d["cx"] - e["cx"], d["cy"] - e["cy"]) <= PRIOR_R * scale for e in prev)
                               for d in discs)
                    r["carried_by_prior"] = int(near)
                    r["new"] = len(discs) - int(near)
                    r["gap_ms"] = t - r_prev_t
                prev, r_prev_t = discs, t
                rows.append(r)

        def med(k, rs=rows):
            v = [x[k] for x in rs if k in x]
            return None if not v else {"median": round(float(np.median(v)), 3), "p90": round(float(np.percentile(v, 90)), 3),
                                       "mean": round(float(np.mean(v)), 3), "n": len(v)}
        withd = [x for x in rows if x["scored_discs"]]
        per_disc = {name: round(float(np.sum([x[f"{name}_ms"] for x in withd]) /
                                      max(1, sum(x["scored_discs"] for x in withd))), 4) for name in banks}
        carried = sum(x.get("carried_by_prior", 0) for x in rows)
        followed = sum(x["discs"] for x in rows if "carried_by_prior" in x)
        summ = {"capture": man.get("source", {}).get("path") if isinstance(man.get("source"), dict) else man.get("source"),
                "crop_px": list(first.shape[:2]), "scale": round(scale, 4), "frames": len(rows),
                "holds_total": int(len(holds)), "drawn_holds": len(dh),
                "candidate_agents": agent_why, "keys": {n: len(b.keys) for n, b in banks.items()},
                "templates": {n: b.n for n, b in banks.items()}, "bank_build_s": round(build_s, 2),
                "per_frame_ms": {k: med(k) for k in ("luma_ms", "propose_ms", "verify_ms",
                                                     *[f"{n}_ms" for n in banks],
                                                     "A_ally_rotate_all_gpu_ms")},
                "per_disc_ms": per_disc, "discs_per_frame": med("discs"), "new_per_frame": med("new"),
                "hold_gap_ms": med("gap_ms"),
                "prior_share": None if not followed else round(carried / followed, 4),
                "prior_counts": {"carried": carried, "discs_in_followed_frames": followed},
                "gpu": None if gT is None else torch.cuda.get_device_name(0)}
        res["sessions"][sid] = {"summary": summ, "frames": rows}
        print(sid, json.dumps(summ, indent=1, default=str), flush=True)
    res["stored_prior_2hz"] = stored_prior()
    for sid, v in res["stored_prior_2hz"].items():
        print("stored 2 Hz", sid, json.dumps(v), flush=True)
    json.dump(res, open(fresh(out / "cost.json"), "w", encoding="utf-8"), indent=1, default=float)
    print("wrote", out / "cost.json")


if __name__ == "__main__":
    main()
