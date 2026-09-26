r"""Pre-wiring measurements for mined minimap ally references.

    .\.venv\Scripts\python.exe prototypes\minimap_mined_references.py coverage|stability|temperature|joint

Purpose. `minimap_identity_calibration.py` found that per-agent mean minimap
icons, mined from death-labelled segments of other sessions, name teammates
far better than official art (held out: 0.776 per icon with same-session
exemplars; 101 of 134 segments at death). Before that becomes a reference
source, four questions, each on the same fixed split and the same cached
labels (`collect` there; entities built with deaths=None):

- `coverage`: which lineup agents have references, from how many labelled
  segments, and how held-out accuracy grows with a per-agent cap on the
  segments a reference may use.
- `stability`: references and per-agent tables refitted leaving one
  calibration session out; how far each agent's mean moves against its
  distance to the nearest other agent, and the held-out accuracy spread.
- `temperature`: one temperature for summed segment log ratios and one per
  icon, fitted on calibration segments only (their features use references
  that leave their own session out); held-out reliability before and after.
- `joint`: per frame, the icons take distinct teammates
  [domain:rounds/agent-uniqueness] by `track.assign` on negative log
  posteriors (per-icon temperature), refusing an icon whose assigned
  posterior is below `--tau`; per-icon and segment-at-death accuracy and the
  share of frames naming one agent twice.

Nothing is written but a JSON summary in the calibration cache directory.
Predictions and outcome: `minimap-mined-references` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.track import assign  # noqa: E402

import minimap_identity_calibration as mic  # noqa: E402

FAMILIES = ("mined", "exemplar")
CAPS = (1, 2, 4, 8, 16)
TEMPS = tuple(float(x) for x in np.round(np.exp(np.linspace(np.log(0.25), np.log(64), 57)), 4))


def load_split():
    cal, test = mic.split_sessions(mic.session_ids())
    sessions = mic.load_sessions(cal + test, mic.WORK)
    counts = Counter()
    units = {s: mic.label_units(sessions[s], counts) for s in sessions}
    return cal, test, sessions, units


class MinedModel:
    """Per-agent LLR tables for `families`, fitted on `fit_units`, with mined
    references built from `ref_units` less the scored session."""

    def __init__(self, sessions, units, fit_units, ref_units, families=FAMILIES):
        self.sessions, self.families = sessions, families
        cache = {}

        def templates_for(sid):
            if sid not in cache:
                cache[sid] = mic.mean_templates(sessions, [u for u in ref_units if u["sid"] != sid])
            return cache[sid]

        self.templates_for = templates_for
        self.feats = mic.Features(sessions, units, templates_for)
        self.tables = {}
        for fam in families:
            samples = []
            for u in fit_units:
                w = 1.0 / len(u["keys_last"])
                for k in u["keys_last"]:
                    for a, v in self.feats.values(fam, u["sid"], k, u["segment"]).items():
                        samples.append((a, v, a == u["victim"], w))
            self.tables[fam] = mic.fit_table(samples, True)

    def llr(self, sid, key, own) -> dict:
        out = {a: 0.0 for a in self.sessions[sid]["candidates"]}
        for fam in self.families:
            for a, v in self.feats.values(fam, sid, key, own).items():
                out[a] += mic.table_llr(self.tables[fam], a, v)
        return out


def score_units(model, units) -> dict:
    """Per-icon and last-2-s segment accuracy, and per-victim tallies."""
    c, by_agent = Counter(), defaultdict(Counter)
    for u in units:
        tot = Counter()
        for k in u["keys_last"]:
            llr = model.llr(u["sid"], k, u["segment"])
            tot.update(llr)
            ok = mic.top_agent(llr) == u["victim"]
            c["icons"] += 1
            c["icon_right"] += ok
            by_agent[u["victim"]]["icons"] += 1
            by_agent[u["victim"]]["icon_right"] += ok
        ok = mic.top_agent(dict(tot)) == u["victim"]
        c["segments"] += 1
        c["seg_right"] += ok
        by_agent[u["victim"]]["segments"] += 1
        by_agent[u["victim"]]["seg_right"] += ok
    return {"icon": round(c["icon_right"] / max(1, c["icons"]), 3),
            "segment": f"{c['seg_right']}/{c['segments']}", "by_agent": by_agent}


def cap_units(units, cap, seed):
    rng = random.Random(seed)
    pool = list(units)
    rng.shuffle(pool)
    seen, out = Counter(), []
    for u in pool:
        if seen[u["victim"]] < cap:
            seen[u["victim"]] += 1
            out.append(u)
    return out


def run_coverage(cal, test, sessions, units) -> dict:
    cal_units = [u for s in cal for u in units[s]]
    test_units = [u for s in test for u in units[s]]
    lineup_agents = Counter(a for s in sessions for a in sessions[s]["candidates"])
    segs = Counter(u["victim"] for u in cal_units)
    icons = Counter()
    for u in cal_units:
        icons[u["victim"]] += len(u["keys_last"])
    table = {a: {"lineups": lineup_agents[a], "cal_segments": segs[a], "cal_icons": icons[a]}
             for a in sorted(lineup_agents)}
    full = score_units(MinedModel(sessions, units, cal_units, cal_units, ("mined",)), test_units)
    for a, t in full["by_agent"].items():
        table[a]["test_icons"] = t["icons"]
        table[a]["test_icon_acc"] = round(t["icon_right"] / t["icons"], 3)
        table[a]["test_segments"] = f"{t['seg_right']}/{t['segments']}"
    bands = defaultdict(Counter)
    for a, t in full["by_agent"].items():
        n = segs[a]
        band = "0" if n == 0 else "1-3" if n < 4 else "4-7" if n < 8 else "8-15" if n < 16 else "16+"
        bands[band].update(t)
    out = {"agents": table, "no_reference": sorted(a for a in lineup_agents if not segs[a]),
           "mined_full": {"icon": full["icon"], "segment": full["segment"]},
           "by_reference_band": {b: {"icons": t["icons"],
                                     "icon_acc": round(t["icon_right"] / t["icons"], 3),
                                     "segments": f"{t['seg_right']}/{t['segments']}"}
                                 for b, t in sorted(bands.items())},
           "caps": {}}
    for cap in CAPS:
        runs = [score_units(MinedModel(sessions, units, cal_units, cap_units(cal_units, cap, seed),
                                       ("mined",)), test_units) for seed in range(3)]
        out["caps"][cap] = {"icon": [r["icon"] for r in runs], "segment": [r["segment"] for r in runs]}
        print("cap", cap, out["caps"][cap], flush=True)
    return out


def run_stability(cal, test, sessions, units) -> dict:
    cal_units = [u for s in cal for u in units[s]]
    test_units = [u for s in test for u in units[s]]
    full_t = mic.mean_templates(sessions, cal_units)
    full_m = MinedModel(sessions, units, cal_units, cal_units, ("mined",))
    nearest = {a: min(float(np.abs(full_t[a] - full_t[b]).sum()) for b in full_t if b != a)
               for a in full_t}
    segs = Counter(u["victim"] for u in cal_units)
    moves, slopes, accs = defaultdict(list), defaultdict(list), []

    def slope(table, a):
        ms, md = table.get(a, table["*"])
        return (ms - md) / table["var"]

    for s in cal:
        keep = [u for u in cal_units if u["sid"] != s]
        t = mic.mean_templates(sessions, keep)
        for a in full_t:
            if a in t:
                moves[a].append(float(np.abs(t[a] - full_t[a]).sum()))
        m = MinedModel(sessions, units, keep, keep, ("mined",))
        for a in full_t:
            slopes[a].append(slope(m.tables["mined"], a))
        r = score_units(m, test_units)
        accs.append((s, r["icon"], r["segment"]))
        print("leave out", s, r["icon"], r["segment"], flush=True)
    agents = {a: {"cal_segments": segs[a], "nearest_other_l1": round(nearest[a], 3),
                  "max_move_l1": round(max(moves[a]), 3) if moves[a] else None,
                  "move_over_nearest": round(max(moves[a]) / nearest[a], 3) if moves[a] else None,
                  "slope_full": round(slope(full_m.tables["mined"], a), 2),
                  "slope_range": [round(min(slopes[a]), 2), round(max(slopes[a]), 2)]}
              for a in sorted(full_t)}
    icons = [x[1] for x in accs]
    return {"agents": agents, "loso": accs,
            "icon_range": [min(icons), max(icons)], "icon_full": score_units(full_m, test_units)["icon"]}


def softmax_post(llr: dict, temp: float) -> dict:
    top = max(llr.values())
    w = {a: math.exp((v - top) / temp) for a, v in llr.items()}
    z = sum(w.values())
    return {a: x / z for a, x in w.items()}


def fit_temperature(rows) -> float:
    """rows: (llr dict, label). The temperature minimising the label's NLL."""
    def nll(temp):
        return -sum(math.log(max(softmax_post(llr, temp)[y], 1e-12)) for llr, y in rows)
    return min(TEMPS, key=nll)


def run_temperature(cal, test, sessions, units, model=None) -> dict:
    cal_units = [u for s in cal for u in units[s]]
    test_units = [u for s in test for u in units[s]]
    model = model or MinedModel(sessions, units, cal_units, cal_units)

    def rows(us):
        seg, icon = [], []
        for u in us:
            tot = Counter()
            for k in u["keys_last"]:
                llr = model.llr(u["sid"], k, u["segment"])
                tot.update(llr)
                icon.append((llr, u["victim"]))
            seg.append(({a: tot.get(a, 0.0) for a in sessions[u["sid"]]["candidates"]}, u["victim"]))
        return seg, icon

    cal_seg, cal_icon = rows(cal_units)
    test_seg, test_icon = rows(test_units)
    t_seg, t_icon = fit_temperature(cal_seg), fit_temperature(cal_icon)

    def rel(rs, temp):
        pairs = []
        for llr, y in rs:
            p = softmax_post(llr, temp)
            a = max(sorted(p), key=p.get)
            pairs.append((p[a], a == y))
        bins = mic.reliability(pairs)
        ece = sum(n * abs(p - r) for _, n, p, r in bins) / len(pairs)
        return {"bins": bins, "ece": round(ece, 3)}

    out = {"t_segment": t_seg, "t_icon": t_icon,
           "segment_raw": rel(test_seg, 1.0), "segment_scaled": rel(test_seg, t_seg),
           "icon_raw": rel(test_icon, 1.0), "icon_scaled": rel(test_icon, t_icon),
           "segment_scaled_on_calibration": rel(cal_seg, t_seg)}
    print("temperatures", t_seg, t_icon, flush=True)
    return out


def run_joint(cal, test, sessions, units, taus=(0.0, 0.5, 0.7)) -> dict:
    cal_units = [u for s in cal for u in units[s]]
    model = MinedModel(sessions, units, cal_units, cal_units)
    temp = run_temperature(cal, test, sessions, units, model)
    t_icon = temp["t_icon"]
    labelled = {(u["sid"], u["segment"]): u for s in test for u in units[s]}
    res = {"t_icon": t_icon, "t_segment": temp["t_segment"]}
    posts = {}
    frames = defaultdict(list)
    seg_of = {}
    for sid in test:
        data = sessions[sid]
        for seg, obs in data["obs"].items():
            for _, k in obs:
                if k in data["icons"]:
                    seg_of[(sid, k)] = seg
        for k, icon in data["icons"].items():
            llr = model.llr(sid, k, seg_of.get((sid, k)))
            posts[(sid, k)] = (llr, softmax_post(llr, t_icon))
            frames[(sid, icon["frame"])].append(k)
    for tau in taus:
        name = {}
        for (sid, _f), keys in frames.items():
            cands = sessions[sid]["candidates"]
            cost = [[-math.log(max(posts[(sid, k)][1][a], 1e-12)) for a in cands] for k in keys]
            for k, col in zip(keys, assign(cost)):
                p = posts[(sid, k)][1][cands[col]] if col >= 0 else 0.0
                name[(sid, k)] = cands[col] if col >= 0 and p >= tau else None
        c = Counter()
        for (sid, seg), u in labelled.items():
            votes, tot = Counter(), Counter()
            for k in u["keys_last"]:
                got = name[(sid, k)]
                c["icons"] += 1
                c["named"] += got is not None
                c["right"] += got == u["victim"]
                if got:
                    votes[got] += 1
                tot.update(posts[(sid, k)][0])
            best = max(votes.values()) if votes else 0
            tied = [a for a, v in votes.items() if v == best]
            seg_name = max(tied, key=lambda a: tot[a]) if tied else None
            c["segments"] += 1
            c["seg_right"] += seg_name == u["victim"]
        # segment names voted over whole segments, and frames naming one agent twice
        seg_names = {}
        for sid in test:
            for seg, obs in sessions[sid]["obs"].items():
                v = Counter(name[(sid, k)] for _, k in obs if name.get((sid, k)))
                seg_names[(sid, seg)] = v.most_common(1)[0][0] if v else None
        dup_icon = dup_seg = 0
        for (sid, _f), keys in frames.items():
            icon_names = Counter(name[(sid, k)] for k in keys if name[(sid, k)])
            dup_icon += any(v > 1 for v in icon_names.values())
            segn = Counter(seg_names.get((sid, seg_of.get((sid, k)))) for k in keys
                           if seg_of.get((sid, k)) and seg_names.get((sid, seg_of[(sid, k)])))
            dup_seg += any(v > 1 for v in segn.values())
        res[str(tau)] = {"icon_named_share": round(c["named"] / c["icons"], 3),
                         "icon_acc_all": round(c["right"] / c["icons"], 3),
                         "icon_acc_named": round(c["right"] / max(1, c["named"]), 3),
                         "segment_vote_last2s": f"{c['seg_right']}/{c['segments']}",
                         "dup_share_icon_names": round(dup_icon / len(frames), 4),
                         "dup_share_segment_names": round(dup_seg / len(frames), 4),
                         "frames": len(frames)}
        print("tau", tau, res[str(tau)], flush=True)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("coverage", "stability", "temperature", "joint"))
    a = ap.parse_args()
    split = load_split()
    fn = {"coverage": run_coverage, "stability": run_stability,
          "temperature": run_temperature, "joint": run_joint}[a.step]
    out = fn(*split)
    path = mic.WORK / f"mined_{a.step}.json"
    path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("wrote", path)
