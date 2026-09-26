r"""Calibrate minimap ally icon identity against killfeed deaths.

    .\.venv\Scripts\python.exe prototypes\minimap_identity_calibration.py collect [SID ...]
    .\.venv\Scripts\python.exe prototypes\minimap_identity_calibration.py evaluate [--dup MODEL ...]

Purpose. Per-icon identity evidence, not sampling rate, limits minimap ally
identity (`minimap-fidelity`). Its raw score is a histogram intersection
against official agent art, and art scores sit on agent-specific scales, as
killfeed portrait scores sat on source-specific ones
(`prototypes/portrait_likelihood.py`). This asks whether likelihood ratios
fitted on witnessed icons, and minimap references mined from them, name
teammates better.

Labels (`collect`). Per session it rebuilds the 15 Hz ally segments in memory
WITHOUT deaths (`minimap_fidelity.build_entities`, since death linkage would
name segments from the witness) and binds each killfeed ally death with a
named victim to the one segment that alone ends within [-500, +700] ms of it
(`minimap_identity_at_death.py`). The victim labels that segment's last 2 s
only: a segment may hold another teammate earlier. Per icon it keeps the
owner's evidence (`identity.claims_from_ally_icons`: raw `scores`,
`best_guess`) and the stored 90-bin `composition`. The analysis cache goes to
`--work` (default: the system temp directory); nothing is written to the store.

Split. Sorted session ids, index mod 3 == 2 held out; fixed before measuring.

Method (`evaluate`). Every model maps an icon to a log likelihood ratio per
candidate teammate; the posterior is each LR over their sum (uniform prior).
Fits use two Gaussians with a common spread, each labelled segment weighted
once, per-agent means shrunk toward the pooled mean by `SHRINK` segments.
- `art_pooled`: one table for the art score, all agents.
- `art_agent`: per-agent tables for the art score.
- `art_centered`: per-agent tables for the art score less the icon's mean
  art score over its candidates.
- `mined`: intersection with the mean labelled minimap icon of each agent
  from OTHER sessions (leave-one-session-out inside calibration; all
  calibration sessions for the test), per-agent tables.
- `exemplar`: best intersection with this session's labelled icons of other
  deaths (never the scored segment's own), per-agent tables. A name that uses
  one depends on the death that labelled it.
Sums of these are scored too. Segment identity sums per-icon LLRs over the
last 2 s or the whole segment, against the segment agent `session_lifetimes`
gave without deaths (the 0.568 baseline). `--dup` names every held-out
segment with a model and counts frames that name one agent twice. Predictions
and outcome: `minimap-identity-calibration` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.adjudication.identity import (claims_from_ally_icons,  # noqa: E402
                                           load_identity_gallery, portrait_posterior)
from reticle.lineup import load_lineup  # noqa: E402

import minimap_fidelity as mf  # noqa: E402

STORE = mf.STORE
LAST_MS = 2000.0
SHRINK = 10.0
WORK = Path(tempfile.gettempdir()) / "minimap_identity_calibration"


def session_ids() -> list[str]:
    root = STORE.root / "roi_cache" / "minimap" / "roi-cache-0.1.0"
    return sorted(p.stem for p in root.glob("*.json")
                  if load_lineup(p.stem, STORE.root))


def split_sessions(sids: list[str]) -> tuple[list[str], list[str]]:
    """Calibration and held-out sessions: every third of the sorted ids is held out."""
    sids = sorted(sids)
    return ([s for i, s in enumerate(sids) if i % 3 != 2],
            [s for i, s in enumerate(sids) if i % 3 == 2])


# ---------------------------------------------------------------- collect

def collect_session(sid: str, gallery: dict) -> dict:
    events = STORE.read_events("ally_icon", sid)
    lineup = load_lineup(sid, STORE.root)
    icons = [e for e in events if e.get("kind") == "icon"]
    claims = claims_from_ally_icons(icons, lineup, gallery=gallery, session_id=sid)
    by_key = {i["observation_key"]: i for i in icons}
    keys, comps, rows = [], [], {}
    for c in claims:
        ev = c.get("evidence") or {}
        if not ev.get("scores"):
            continue
        k = c["entity_id"].rsplit(":ally_icon:", 1)[-1]
        i = by_key[k]
        rows[k] = {"t": float(i["t_ms"]), "frame": i["frame_idx"], "scores": ev["scores"],
                   "best": ev.get("best_guess"), "row": len(keys),
                   **{f: i.get(f) for f in ("facing", "cov", "lobe", "inner_v", "map_diff", "pixels")}}
        keys.append(k)
        comps.append(np.asarray(i["composition"], np.float32))
    ents_rows = mf.build_entities(sid, events)
    ents = {e["id"]: {"agent": e.get("agent"), "round_no": e.get("round_no")}
            for e in ents_rows if e.get("kind") == "entity" and e.get("family") == "ally"}
    obs = defaultdict(list)
    for o in ents_rows:
        if o.get("kind") == "observation" and o.get("entity_id") in ents:
            obs[o["entity_id"]].append((float(o["t_ms"]), o["observation_key"]))
    for k in obs:
        obs[k].sort()
    lo, hi = mf.DEATH_WINDOW_MS
    deaths = []
    for v in STORE.read_events("death", sid):
        if v.get("kind") != "death_verdict" or v.get("side") != "ally" or not v.get("victim"):
            continue
        t = float(v["t_ms"])
        ends = [e for e in obs if t - lo <= obs[e][-1][0] <= t + hi]
        deaths.append({"death_id": v.get("death_id"), "t": t, "victim": v["victim"],
                       "segment": ends[0] if len(ends) == 1 else None})
    return {"sid": sid, "player": (lineup.get("player") or {}).get("agent"),
            "candidates": sorted({n for r in rows.values() for n in r["scores"]}),
            "icons": rows, "comp": np.stack(comps) if comps else np.zeros((0, 90), np.float32),
            "ents": ents, "obs": dict(obs), "deaths": deaths}


def collect_labels(sids: list[str], work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    gallery = load_identity_gallery(STORE.root)
    for sid in sids:
        data = collect_session(sid, gallery)
        (work / f"{sid}.pkl").write_bytes(pickle.dumps(data))
        bound = [d for d in data["deaths"] if d["segment"]]
        print(sid, "deaths", len(data["deaths"]), "bound", len(bound),
              "player_victim", sum(d["victim"] == data["player"] for d in bound),
              "victim_not_candidate", sum(d["victim"] not in data["candidates"] for d in bound),
              flush=True)


# ---------------------------------------------------------------- evaluate

def load_sessions(sids: list[str], work: Path) -> dict:
    return {sid: pickle.loads((work / f"{sid}.pkl").read_bytes()) for sid in sids
            if (work / f"{sid}.pkl").exists()}


def label_units(data: dict, counts: Counter) -> list[dict]:
    """Death-labelled segments: the victim over the last `LAST_MS` of a segment
    that alone ends at the death. Segments two deaths bind, the player's own
    death (his icon is the self key, never an ally icon) and victims outside
    the candidates are counted and dropped."""
    bound = [d for d in data["deaths"] if d["segment"]]
    counts["deaths"] += len(data["deaths"])
    counts["bound"] += len(bound)
    per_seg = Counter(d["segment"] for d in bound)
    units = []
    for d in bound:
        seg = d["segment"]
        if per_seg[seg] > 1:
            counts["drop_two_deaths_one_segment"] += 1
            continue
        if d["victim"] == data["player"]:
            counts["drop_player_victim"] += 1
            continue
        if d["victim"] not in data["candidates"]:
            counts["drop_victim_not_candidate"] += 1
            continue
        obs = data["obs"][seg]
        end = obs[-1][0]
        keys_all = [k for _, k in obs if k in data["icons"]]
        keys_last = [k for t, k in obs if t >= end - LAST_MS and k in data["icons"]]
        if not keys_last:
            counts["drop_no_scored_icon"] += 1
            continue
        units.append({"sid": data["sid"], "segment": seg, "victim": d["victim"],
                      "death_id": d["death_id"], "keys_last": keys_last, "keys_all": keys_all,
                      "base": data["ents"][seg]["agent"]})
    counts["units"] += len(units)
    return units


def unit_mean(data: dict, keys: list[str]) -> np.ndarray:
    return data["comp"][[data["icons"][k]["row"] for k in keys]].mean(axis=0)


def mean_templates(sessions: dict, units: list[dict]) -> dict:
    """Per agent, the mean over labelled segments of each segment's mean icon."""
    acc = defaultdict(list)
    for u in units:
        acc[u["victim"]].append(unit_mean(sessions[u["sid"]], u["keys_last"]))
    return {a: np.mean(v, axis=0) for a, v in acc.items()}


class Features:
    """Per-icon feature value per candidate, for one feature family."""

    def __init__(self, sessions, units_by_sid, templates_for):
        self.s, self.units, self.tmpl = sessions, units_by_sid, templates_for
        self._ex = {}

    def exemplars(self, sid: str):
        """This session's labelled last-2-s icons, the rows of each agent, and
        the segment each came from (so a segment never scores against itself)."""
        if sid not in self._ex:
            data, rows, segs, agents = self.s[sid], [], [], []
            for u in self.units.get(sid, ()):
                for k in u["keys_last"]:
                    rows.append(data["icons"][k]["row"])
                    segs.append(u["segment"])
                    agents.append(u["victim"])
            if not rows:
                self._ex[sid] = None
            else:
                agents = np.array(agents)
                self._ex[sid] = {"comp": data["comp"][rows], "segment": np.array(segs),
                                 "by_agent": {a: np.flatnonzero(agents == a) for a in set(agents)}}
        return self._ex[sid]

    def values(self, family: str, sid: str, key: str, own_segment: str | None) -> dict:
        data = self.s[sid]
        icon = data["icons"][key]
        cands = data["candidates"]
        if family == "art":
            return {a: icon["scores"][a] for a in cands if a in icon["scores"]}
        if family == "centered":
            m = float(np.mean([icon["scores"][a] for a in cands if a in icon["scores"]]))
            return {a: icon["scores"][a] - m for a in cands if a in icon["scores"]}
        comp = data["comp"][icon["row"]]
        if family == "mined":
            t = self.tmpl(sid)
            return {a: float(np.minimum(comp, t[a]).sum()) for a in cands if a in t}
        if family == "exemplar":
            ex = self.exemplars(sid)
            if ex is None:
                return {}
            sims = np.minimum(ex["comp"], comp).sum(axis=1)
            out = {}
            for a, rows in ex["by_agent"].items():
                if a not in cands:
                    continue
                keep = rows[ex["segment"][rows] != own_segment]
                if keep.size:
                    out[a] = float(sims[keep].max())
            return out
        raise ValueError(family)


def fit_table(samples: list[tuple], per_agent: bool) -> dict:
    """Two Gaussians with a common spread per agent (or pooled): samples are
    (agent, value, same, weight). Per-agent means shrink toward the pooled
    mean by `SHRINK` segments' weight."""
    def wmean(xs):
        w = sum(x[1] for x in xs)
        return (sum(x[0] * x[1] for x in xs) / w, w) if w else (0.0, 0.0)
    ms, _ = wmean([(v, w) for a, v, s, w in samples if s])
    md, _ = wmean([(v, w) for a, v, s, w in samples if not s])
    table = {"*": (ms, md)}
    if per_agent:
        for agent in {a for a, *_ in samples}:
            m1, w1 = wmean([(v, w) for a, v, s, w in samples if s and a == agent])
            m0, w0 = wmean([(v, w) for a, v, s, w in samples if not s and a == agent])
            table[agent] = ((m1 * w1 + ms * SHRINK) / (w1 + SHRINK),
                            (m0 * w0 + md * SHRINK) / (w0 + SHRINK))
    num = den = 0.0
    for a, v, s, w in samples:
        m = table.get(a, table["*"])[0 if s else 1]
        num += w * (v - m) ** 2
        den += w
    table["var"] = num / max(den, 1e-9)
    return table


def table_llr(table: dict, agent: str, value: float) -> float:
    ms, md = table.get(agent, table["*"])
    return (ms - md) / table["var"] * (value - (ms + md) / 2.0)


MODELS = {
    "art_pooled": (("art", False),),
    "art_agent": (("art", True),),
    "art_centered": (("centered", True),),
    "mined": (("mined", True),),
    "art+mined": (("art", True), ("mined", True)),
    "exemplar": (("exemplar", True),),
    "art+exemplar": (("art", True), ("exemplar", True)),
    "mined+exemplar": (("mined", True), ("exemplar", True)),
    "art+mined+exemplar": (("art", True), ("mined", True), ("exemplar", True)),
}
BINS = (0.0, 0.4, 0.6, 0.8, 0.9, 0.97, 1.01)


def reliability(pairs: list[tuple]) -> list:
    """(max posterior, right) pairs -> per bin [lo, n, mean posterior, accuracy]."""
    out = []
    for lo, hi in zip(BINS, BINS[1:]):
        b = [(p, r) for p, r in pairs if lo <= p < hi]
        if b:
            out.append([lo, len(b), round(float(np.mean([p for p, _ in b])), 3),
                        round(float(np.mean([r for _, r in b])), 3)])
    return out


def top_agent(llr: dict):
    """The candidate with the largest LLR; None when every candidate ties."""
    if not llr or max(llr.values()) == min(llr.values()):
        return None
    return max(sorted(llr), key=lambda a: llr[a])


def evaluate(work: Path) -> dict:
    cal_ids, test_ids = split_sessions(session_ids())
    sessions = load_sessions(cal_ids + test_ids, work)
    counts = {"cal": Counter(), "test": Counter()}
    units = {sid: label_units(sessions[sid], counts["cal" if sid in cal_ids else "test"])
             for sid in sessions}
    cal_units = [u for sid in cal_ids for u in units.get(sid, ())]
    tmpl_cache = {}

    def templates_for(sid):
        if sid not in tmpl_cache:
            tmpl_cache[sid] = mean_templates(sessions, [u for u in cal_units if u["sid"] != sid])
        return tmpl_cache[sid]

    feats = Features(sessions, units, templates_for)
    tables = {}
    for fam, per_agent in sorted({f for m in MODELS.values() for f in m}):
        samples = []
        for u in cal_units:
            w = 1.0 / len(u["keys_last"])
            for k in u["keys_last"]:
                for a, v in feats.values(fam, u["sid"], k, u["segment"]).items():
                    samples.append((a, v, a == u["victim"], w))
        tables[(fam, per_agent)] = fit_table(samples, per_agent)

    def icon_llr(model, sid, key, own):
        out = {a: 0.0 for a in sessions[sid]["candidates"]}
        for fam, per_agent in MODELS[model]:
            for a, v in feats.values(fam, sid, key, own).items():
                out[a] += table_llr(tables[(fam, per_agent)], a, v)
        return out

    test_units = [u for sid in test_ids for u in units.get(sid, ())]
    res = {"split": {"calibration": cal_ids, "test": test_ids},
           "labels": {k: dict(v) for k, v in counts.items()}}
    raw = Counter()
    for u in test_units:
        for k in u["keys_last"]:
            icon = sessions[u["sid"]]["icons"][k]
            raw["n"] += 1
            raw["best_guess"] += icon["best"] == u["victim"]
            raw["raw_argmax"] += max(sorted(icon["scores"]), key=icon["scores"].get) == u["victim"]
    seg_base = Counter("right" if u["base"] == u["victim"] else "none" if u["base"] is None
                       else "wrong" for u in test_units)
    res["baseline"] = {"icons": raw["n"],
                       "icon_best_guess": round(raw["best_guess"] / raw["n"], 3),
                       "icon_raw_argmax": round(raw["raw_argmax"] / raw["n"], 3),
                       "segments": len(test_units),
                       "segment_agent": f"{seg_base['right']}/{seg_base['right'] + seg_base['wrong']}"
                                        f" named, {seg_base['none']} unnamed"}
    res["models"] = {}
    for model in MODELS:
        right, pairs, seg, seg_pairs = 0, [], Counter(), []
        for u in test_units:
            per_icon = {k: icon_llr(model, u["sid"], k, u["segment"]) for k in u["keys_all"]}
            for k in u["keys_last"]:
                a = top_agent(per_icon[k])
                right += a == u["victim"]
                pairs.append((max(portrait_posterior(per_icon[k]).values()), a == u["victim"]))
            for span in ("last", "all"):
                tot = Counter()
                for k in u[f"keys_{span}"]:
                    tot.update(per_icon[k])
                a = top_agent(dict(tot))
                seg[span] += a == u["victim"]
                if span == "last":
                    seg_pairs.append((max(portrait_posterior(dict(tot)).values()),
                                      a == u["victim"]))
        res["models"][model] = {
            "icon": round(right / len(pairs), 3),
            "icon_reliability": reliability(pairs),
            "segment_last2s": f"{seg['last']}/{len(test_units)}",
            "segment_whole": f"{seg['all']}/{len(test_units)}",
            "segment_reliability_last2s": reliability(seg_pairs)}
        m = res["models"][model]
        print(model, m["icon"], m["segment_last2s"], m["segment_whole"], flush=True)
    res["tables"] = {f"{f}:{'agent' if p else 'pooled'}":
                     {k: ([round(x, 4) for x in v] if isinstance(v, tuple) else round(v, 6))
                      for k, v in t.items()} for (f, p), t in tables.items()}
    res["_icon_llr"], res["_sessions"] = icon_llr, sessions
    return res


def duplicate_share(res: dict, model: str) -> dict:
    """Name every held-out ally segment by its whole-segment summed LLR and
    count frames whose segments name one agent on two icons
    [domain:rounds/agent-uniqueness], against the segment agent built
    without deaths."""
    sessions, icon_llr = res["_sessions"], res["_icon_llr"]
    c = Counter()
    for sid in res["split"]["test"]:
        data = sessions[sid]
        frame_names = defaultdict(list)
        for seg, obs in data["obs"].items():
            keys = [k for _, k in obs if k in data["icons"]]
            tot = Counter()
            for k in keys:
                tot.update(icon_llr(model, sid, k, seg))
            name = top_agent(dict(tot))
            base = data["ents"][seg]["agent"]
            for k in keys:
                frame_names[data["icons"][k]["frame"]].append((name, base))
        for names in frame_names.values():
            c["frames"] += 1
            for i, tag in ((0, "model"), (1, "base")):
                got = Counter(n[i] for n in names if n[i])
                c[tag] += any(v > 1 for v in got.values())
    return {"frames": c["frames"], "model_dup_share": round(c["model"] / max(1, c["frames"]), 4),
            "base_dup_share": round(c["base"] / max(1, c["frames"]), 4)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("collect", "evaluate"))
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--dup", nargs="*", default=[], help="models to name every held-out segment with")
    a = ap.parse_args()
    if a.command == "collect":
        collect_labels(a.sids or session_ids(), a.work)
    else:
        import json
        out = evaluate(a.work)
        slim = {k: v for k, v in out.items() if not k.startswith("_")}
        print(json.dumps({k: slim[k] for k in ("split", "labels", "baseline")}, indent=1))
        for model in a.dup:
            slim.setdefault("duplicates", {})[model] = duplicate_share(out, model)
            print(model, slim["duplicates"][model], flush=True)
        (a.work / "evaluate.json").write_text(json.dumps(slim, indent=1), encoding="utf-8")
