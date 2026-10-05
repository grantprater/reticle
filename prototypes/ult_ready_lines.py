r"""Score the ult-ready voice lines against the match audio: who announced a ready ultimate?

    .\.venv\Scripts\python.exe prototypes\ult_ready_lines.py score [--sessions SID ...] [--force]
    .\.venv\Scripts\python.exe prototypes\ult_ready_lines.py evaluate [--sessions SID ...] [--record]

Purpose
-------
An agent announces a ready ultimate with a fixed line of its own
[domain:abilities/ult-ready-lines], and the wiki lists it as one reply of the
Ultimate Status radio command [domain:abilities/ult-ready-line-is-a-radio-reply].
The player's review of the ultimate voice-line sheet found one such line
scoring 0.0441 on a cast template, just under the cast threshold. The line is
a false alarm for the cast templates and a witness that the speaker's
ultimate is ready. `docs/ULT_READY_LINES.md` holds the design and results; the
store's `notes/predictions.jsonl` holds the predictions (task
`ult-ready-lines`, R1 to R4).

Method
------
`score` builds one template per take from
`reference/assets/voicelines/ult_ready/index.json` (the harvest of
`voice_line_harvest.py ult-ready`) with the reader's own template cut
(`reticle.ult_lines.build_templates`), and reads each capture with the reader's
own GCC-PHAT (`reticle.ult_lines.read_capture`: `decode_mono`, `phat_tracks`,
`track_peaks`, `nms_peaks`). It keeps every peak at or above its template's
99th percentile, none within one template length of a higher peak of the same
template, and writes the reader's row shape (`ult_lines.observations`) to
`<store>/analysis/ult-ready-lines/0.1.0/peaks/<sid>.jsonl`, one session at a
time, with each session's decode and score seconds in `summary.json`.

`evaluate` reads only stored rows. Two takes of one line may both peak on one
utterance, so an agent's takes merge: a peak falls when a higher peak of the
agent's other take lies within the agent's longer take
(`voice_lines.suppress`). Each agent is classed per session from the identity
arbiter's lineup through `voice_lines.template_class`, asked for both
variants: `own` (the player's agent), `ally_named`, `enemy_named`, `absent`
(impossible as the ally line and as the enemy line: the lineup puts the agent
on neither complete side) and `unknown`. A ready line has no side variant,
and the one the player heard came from an agent the lineup names on the
enemy side, so only `absent` measures false alarms. The operating point is the
cast lines' rule (`voice_lines.operating_tau`): the lowest threshold at which
`absent` detections in live time (`voice_lines.match_time`) run at most
`voice_lines.OP_RATE` per live minute, pooled over the match sessions with a
lineup. The literal ally-side classing (`template_class(agent, "ally")`, which
counts an enemy's line as impossible) gets its own threshold beside it.
Cross-talk: the share of `absent` detections with a higher ready detection of
another agent within `voice_lines.SUPPRESS_S`, one line firing several agents'
templates.

- R2: detections per agent and live minute for named allies, named enemies,
  both together, and absent agents at the operating point, and their ratios.
- R3: the tray stores drops, not fills (`events/tray_drop`), so no fill is
  dated. Each accepted own X cast bounds a fill between the previous own X
  cast (or the first round's start) and itself; the test counts the player's
  own ready detections inside those intervals against the share of the
  timeline they cover, where inside them each falls (the binomial tail of
  the count in the later half, against a uniform place), and how many
  intervals hold one against detections placed at random over the timeline.
  A line voiced at every fill would put one in nearly every interval.
- R4: every ready detection at the operating point against the stored cast
  peaks (`events/ult_line`): a collision is a cast peak at or above the
  adjudicator's threshold (`adjudication.ult_cast.THRESHOLD`) within
  COLLIDE_S; a near miss scores under it. Chance: ready detections placed at
  random, against the share of each session within COLLIDE_S of such a cast
  peak. Each collision is crossed by the ready agent's class and the cast
  template's lineup class.
- The witness: the ready line the player heard (HEARD), and every agent's
  ready score at that onset.

What it does not do
-------------------
It emits no events and writes nothing under `events/` or `labels/`;
`reticle/` does not import it. It decodes no video and writes no audio: each
capture's audio stream is decoded in memory by the reader's `decode_mono`.
"""
from __future__ import annotations

import os
import sys

#: One heavy process at a time: four BLAS threads; `voice_lines` sets Below Normal.
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "4"

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
import voice_lines as vl  # noqa: E402  lineup classing, live time, own casts, the threshold rule
from reticle import ult_lines as ul  # noqa: E402  the reader: template cut, decode, GCC-PHAT, peaks

from reticle.audio_source import audio_source  # noqa: E402  which file holds the audio

STORE = vl.STORE
VERSION = "ult-ready-lines-0.1.0"
TAG = VERSION.rsplit("-", 1)[1]
OUT = STORE / "analysis" / "ult-ready-lines" / TAG
PEAKS = OUT / "peaks"
SUMMARY = OUT / "summary.json"
EVALUATION = OUT / "evaluate.json"
VOICE = STORE / ul.VOICE_DIR
READY_DIR = "ult_ready"
#: A cast peak this close to a ready onset collides with it (s).
COLLIDE_S = 0.5
#: A heard witness is sought this far either side of the heard time (s).
HEARD_WIN = 1.5
#: The ready line the player heard: Skye on `c40d950031bb` at 678.1 s, row 21
#: of the ultimate voice-line sheet [domain:abilities/ult-ready-lines].
HEARD = (("c40d950031bb", 678.1, "Skye", "row 21 of the 0.1.0 voice-line review"),)
CLASSES = ("own", "ally_named", "enemy_named", "absent", "unknown")


# ---------------------------------------------------------------------------
# Sessions and templates
# ---------------------------------------------------------------------------

def audio_sessions() -> list[str]:
    """The sessions `reticle ult-cast --record` read: every capture with audio."""
    from reticle import metrics, quoted
    idx = quoted.latest_pass(metrics.load(STORE / "notes" / "metrics.jsonl"))
    return list(idx[("ult_lines/ult-cast", "all-sessions")]["context"]["session_ids"])


def template_entries() -> list[dict]:
    """One entry per harvested take, in the reader's manifest shape."""
    rows = json.loads((VOICE / READY_DIR / "index.json").read_text(encoding="utf-8"))
    out = []
    for r in sorted(rows, key=lambda r: r["file"]):
        take = r["file"].rsplit("__", 1)[1].split(".")[0]
        agent = vl.norm_agent(r["agent"])
        f = f"{READY_DIR}/{r['file']}"
        out.append({"name": f"{agent}_ready_{take}", "agent": agent, "variant": "ready",
                    "file": f, "sha256": ul.template_digest(VOICE / f)})
    return out


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def cmd_score(sids: list[str], force: bool = False) -> dict:
    """Read each capture's audio once, one session at a time, and store its peaks."""
    xp = ul.array_module()
    entries = template_entries()
    key = ul.templates_key(entries)
    templates = ul.build_templates(VOICE, entries, xp=xp)
    print(f"{len(templates)} templates ({key}), longest "
          f"{max(t['span_s'] for t in templates):.2f} s, on {xp.__name__}")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.is_file() else {}
    summary.update(version=VERSION, templates_key=key, templates=len(templates),
                   spans_s=[t["span_s"] for t in templates])
    runs = summary.setdefault("sessions", {})
    for sid in sids:
        src = vl._manifest(sid)["source"]
        out = PEAKS / f"{sid}.jsonl"
        head = _read_jsonl(out)[0] if out.is_file() else {}
        if (not force and head.get("ult_ready_version") == VERSION
                and head.get("templates_key") == key and head.get("content_key") == src["content_key"]):
            print(f"{sid}: current -- pass --force to reread")
            continue
        got = audio_source(vl._manifest(sid), STORE)
        media = got["path"]
        if media is None:
            runs[sid] = {"refused": f"no audio source: {got['reason']}"}
            print(f"{sid}: {runs[sid]['refused']}")
            _write_json(SUMMARY, summary)
            continue
        try:
            info, peaks = ul.read_capture(str(media), templates, xp=xp)
        except (IndexError, ValueError) as e:
            runs[sid] = {"refused": "no_audio_stream" if isinstance(e, IndexError) else str(e)}
            print(f"{sid}: refused ({runs[sid]['refused']})")
            _write_json(SUMMARY, summary)
            continue
        rows = ul.observations(sid, src["content_key"], VERSION, templates, key, info, peaks)
        for r in rows:
            r["ult_ready_version"] = r.pop("ult_line_version")
        PEAKS.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, out)
        runs[sid] = {k: info[k] for k in ("decode_s", "score_s", "n_frames", "backend",
                                          "filled_fraction")}
        runs[sid].update(peaks=len(rows) - 1, content_key=src["content_key"],
                         at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        _write_json(SUMMARY, summary)
        print(f"{sid}: {len(rows) - 1} peaks over {info['n_frames'] * ul.HOP / 60:.1f} min "
              f"(decode {info['decode_s']} s, score {info['score_s']} s, {info['backend']})")
    return summary


# ---------------------------------------------------------------------------
# Evaluate: stored rows only
# ---------------------------------------------------------------------------

def load_peaks(sid: str) -> tuple[dict, dict]:
    """(coverage row, per-peak arrays) of one session's stored peaks."""
    rows = _read_jsonl(PEAKS / f"{sid}.jsonl")
    head = rows[0]
    if head.get("ult_ready_version") != VERSION:
        raise SystemExit(f"{sid}: peaks are {head.get('ult_ready_version')}, not {VERSION}; rerun score")
    pk = [r for r in rows[1:] if r["kind"] == "peak"]
    return head, {"t": np.array([r["t_s"] for r in pk], float),
                  "template": np.array([r["template"] for r in pk], object),
                  "agent": np.array([r["agent"] for r in pk], object),
                  "score": np.array([r["score"] for r in pk], float)}


def utterances(pk: dict, frames: dict[str, int]) -> dict:
    """One detection per spoken line: per agent, a peak falls when a higher peak
    of the agent's other take lies within the agent's longer take."""
    keep = np.zeros(len(pk["t"]), bool)
    for a in sorted(set(pk["agent"])):
        m = np.flatnonzero(pk["agent"] == a)
        names = sorted(set(pk["template"][m]))
        j = np.array([names.index(n) for n in pk["template"][m]])
        window = max(frames[n] for n in names) * ul.HOP
        k, _by = vl.suppress(pk["t"][m], j, pk["score"][m], window)
        keep[m[k]] = True
    return {k: v[keep] for k, v in pk.items()}


def agent_class(agent: str, sides: dict | None, player: str | None) -> tuple[str, str]:
    """(class, the literal ally-side class) of one agent's ready line in one session."""
    ca = vl.template_class(agent, "ally", sides, player)
    ce = vl.template_class(agent, "enemy", sides, player)
    cls = ("own" if ca == "own" else "ally_named" if ca == "possible"
           else "enemy_named" if ce == "possible"
           else "absent" if ca == ce == "impossible" else "unknown")
    return cls, ca


def session_data(sid: str) -> dict:
    head, pk = load_peaks(sid)
    frames = {n: v["frames"] for n, v in head["per_template"].items()}
    agents = sorted({n.rsplit("_ready_", 1)[0] for n in frames})
    ctx = vl.session_context(sid, head["n_frames"], [f"{a}_ult_ally" for a in agents])
    u = utterances(pk, frames)
    cls = {a: agent_class(a, ctx["sides"], ctx["player"]) for a in agents}
    at = np.clip((u["t"] / vl.STEP).astype(np.int64), 0, len(ctx["live"]) - 1)
    return {"sid": sid, "ctx": ctx, "head": head, "raw": pk, "frames": frames, "agents": agents,
            "t": u["t"], "agent": u["agent"], "score": u["score"], "template": u["template"],
            "cls": np.array([cls[a][0] for a in u["agent"]], object),
            "cls_ally": np.array([cls[a][1] for a in u["agent"]], object),
            "agent_cls": cls, "live": ctx["live"][at],
            "lineup": ctx["sides"] is not None and not ctx["demo"]}


def _r(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def threshold(ds: list[dict], key: str, impossible: str) -> dict:
    """The cast lines' operating point for one classing."""
    live_min = sum(d["ctx"]["live_min"] for d in ds)
    s = np.concatenate([d["score"][d["live"] & (d[key] == impossible)] for d in ds])
    tau = vl.operating_tau(s, live_min)
    floors = [v["floor"] for d in ds for v in d["head"]["per_template"].values()]
    return {"tau": tau, "live_minutes": live_min, "floor_max": max(floors),
            "complete": int(tau >= max(floors)),
            "impossible_n": int((s >= tau).sum()), "impossible_per_min": (s >= tau).sum() / live_min}


def class_rates(ds: list[dict], tau: float, key: str, classes: tuple[str, ...]) -> dict:
    """Live detections at tau per class, per live minute and per agent-minute."""
    n, amin = Counter(), Counter()
    live = 0.0
    for d in ds:
        lm = d["ctx"]["live_min"]
        live += lm
        idx = 0 if key == "cls" else 1
        for a in d["agents"]:
            amin[d["agent_cls"][a][idx]] += lm
        sel = d["live"] & (d["score"] >= tau)
        n.update(d[key][sel].tolist())
    return {c: {"n": n[c], "per_live_min": n[c] / live if live else None,
                "agent_minutes": amin[c],
                "per_agent_min": n[c] / amin[c] if amin[c] else None} for c in classes}


def own_fill_test(ds: list[dict], tau: float) -> dict:
    """R3: the player's own ready detections against the fill intervals that
    the accepted own X casts bound (the tray stores no fill time)."""
    fill_rows = 0
    out = {"sessions": 0, "casts": 0, "det": 0, "inside": 0, "expected": 0.0,
           "intervals_hit": 0, "intervals_hit_expected": 0.0, "u": [], "lead": [], "by_agent": {}}
    for d in ds:
        rows = _read_jsonl(STORE / "events" / "tray_drop" / f"{d['sid']}.jsonl")
        fill_rows += sum(r.get("kind") not in ("coverage", "drop") for r in rows)
        rr = d["ctx"]["rounds"]
        if not rr or d["ctx"]["player"] is None:
            continue
        t0 = min(r["t_start_ms"] for r in rr) / 1000.0
        t1 = max(r.get("t_close_ms") or r["t_end_ms"] for r in rr) / 1000.0
        casts = sorted(c["t"] for c in d["ctx"]["own"] if t0 <= c["t"] <= t1)
        sel = (d["cls"] == "own") & (d["score"] >= tau) & (d["t"] >= t0) & (d["t"] <= t1)
        t = d["t"][sel]
        a = out["by_agent"].setdefault(d["ctx"]["player"], {
            "sessions": 0, "casts": 0, "det": 0, "inside": 0, "expected": 0.0,
            "intervals_hit": 0, "intervals_hit_expected": 0.0})
        chance = (casts[-1] - t0) / (t1 - t0) if casts else 0.0
        bounds = np.array([t0] + casts)
        inside = (t > t0) & (t <= (casts[-1] if casts else t0))
        hit = set()
        for x in t[inside]:
            i = int(np.searchsorted(bounds, x, side="left"))
            prev, nxt = bounds[i - 1], bounds[i]
            hit.add(i)
            out["u"].append((x - prev) / (nxt - prev))
            out["lead"].append(nxt - x)
        span = np.diff(bounds) / (t1 - t0)
        hit_expected = float(np.sum(1.0 - (1.0 - span) ** len(t)))
        for tgt in (out, a):
            tgt["sessions"] += 1
            tgt["casts"] += len(casts)
            tgt["det"] += int(len(t))
            tgt["inside"] += int(inside.sum())
            tgt["expected"] += len(t) * chance
            tgt["intervals_hit"] += len(hit)
            tgt["intervals_hit_expected"] += hit_expected
    u, lead = np.array(out.pop("u")), np.array(out.pop("lead"))
    late = int((u > 0.5).sum())
    out.update(tray_fill_rows=fill_rows, u_late=late,
               u_late_p=_binom_tail(late, len(u)) if len(u) else None,
               u_median=_r(np.median(u)) if len(u) else None,
               u_late_share=_r((u > 0.5).mean()) if len(u) else None,
               lead_median_s=_r(np.median(lead), 1) if len(lead) else None,
               lead_q25_s=_r(np.quantile(lead, 0.25), 1) if len(lead) else None,
               lead_q75_s=_r(np.quantile(lead, 0.75), 1) if len(lead) else None)
    return out


def _binom_tail(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p): the chance share of detections in the
    later half of their intervals if a detection's place in its interval were
    uniform."""
    from math import comb
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def cast_peaks(sid: str) -> dict:
    rows = [r for r in _read_jsonl(STORE / "events" / "ult_line" / f"{sid}.jsonl")
            if r.get("kind") == "peak"]
    o = np.argsort([r["t_s"] for r in rows], kind="stable")
    rows = [rows[i] for i in o]
    return {"t": np.array([r["t_s"] for r in rows], float),
            "score": np.array([r["score"] for r in rows], float),
            "template": np.array([r["template"] for r in rows], object),
            "agent": np.array([r["agent"] for r in rows], object),
            "variant": np.array([r["variant"] for r in rows], object),
            "version": (_read_jsonl(STORE / "events" / "ult_line" / f"{sid}.jsonl")[0]
                        .get("ult_line_version"))}


def _covered(t: np.ndarray, half: float, length: float) -> float:
    """Seconds of [0, length] within `half` of any of `t`."""
    total, end = 0.0, 0.0
    for x in np.sort(t):
        lo, hi = max(x - half, end, 0.0), min(x + half, length)
        total += max(0.0, hi - lo)
        end = max(end, hi)
    return total


def collisions(d: dict, cp: dict, tau: float, cast_tau: float) -> dict:
    """R4 for one session: each ready detection at tau against the cast peaks
    within COLLIDE_S. `expected` is the count that ready detections placed at
    random would collide, from the share of the session within COLLIDE_S of a
    cast peak at the cast threshold. Each pair carries the cast template's
    lineup class, so a pair says which line fired which template."""
    sel = np.flatnonzero(d["score"] >= tau)
    length = d["head"]["n_frames"] * ul.HOP
    cover = _covered(cp["t"][cp["score"] >= cast_tau], COLLIDE_S, length) / length
    out = {"ready": int(len(sel)), "collide": 0, "near": 0, "live_ready": 0, "live_collide": 0,
           "same_agent": 0, "expected": len(sel) * cover, "cover": cover, "pairs": []}
    for i in sel:
        lo = np.searchsorted(cp["t"], d["t"][i] - COLLIDE_S, "left")
        hi = np.searchsorted(cp["t"], d["t"][i] + COLLIDE_S, "right")
        live = bool(d["live"][i])
        out["live_ready"] += live
        if hi <= lo:
            continue
        k = lo + int(np.argmax(cp["score"][lo:hi]))
        if cp["score"][k] >= cast_tau:
            out["collide"] += 1
            out["live_collide"] += live
            out["same_agent"] += cp["agent"][k] == d["agent"][i]
            out["pairs"].append({"t": _r(d["t"][i], 2), "ready": d["agent"][i],
                                 "ready_score": _r(d["score"][i]), "class": d["cls"][i],
                                 "cast": cp["template"][k], "cast_score": _r(cp["score"][k]),
                                 "cast_class": vl.template_class(cp["agent"][k], cp["variant"][k],
                                                                 d["ctx"]["sides"], d["ctx"]["player"]),
                                 "dt": _r(cp["t"][k] - d["t"][i], 2)})
        else:
            out["near"] += 1
    return out


def heard_witness(d: dict, t_heard: float, agent: str, cp: dict, tau: float) -> dict:
    """The best stored peak of the heard agent's takes near the heard time, the
    best cast peak beside it, and every agent's best ready peak at that onset."""
    raw = d["raw"]
    m = (raw["agent"] == agent) & (np.abs(raw["t"] - t_heard) <= HEARD_WIN)
    if not m.any():
        return {"score": None, "detected": 0}
    k = np.flatnonzero(m)[np.argmax(raw["score"][m])]
    t = raw["t"][k]
    w = np.abs(cp["t"] - t) <= COLLIDE_S
    j = np.flatnonzero(w)[np.argmax(cp["score"][w])] if w.any() else None
    near = np.flatnonzero(np.abs(raw["t"] - t) <= COLLIDE_S)
    best: dict[str, float] = {}
    for i in near:
        best[raw["agent"][i]] = max(best.get(raw["agent"][i], -1.0), raw["score"][i])
    ranking = sorted(best.items(), key=lambda kv: -kv[1])
    return {"score": _r(raw["score"][k]), "offset_s": _r(t - t_heard, 2),
            "detected": int(raw["score"][k] >= tau), "template": raw["template"][k],
            "class": d["agent_cls"][agent][0],
            "rank": 1 + [a for a, _s in ranking].index(agent),
            "agents_at_onset": len(ranking),
            "top_agent": ranking[0][0], "top_score": _r(ranking[0][1]),
            "top_class": d["agent_cls"][ranking[0][0]][0],
            "ranking": [{"agent": a, "score": _r(s), "class": d["agent_cls"][a][0]}
                        for a, s in ranking],
            "cast_max": _r(cp["score"][j]) if j is not None else None,
            "cast_template": cp["template"][j] if j is not None else None}


def crosstalk(ds: list[dict], tau: float) -> dict:
    """Live `absent` detections at tau with a higher ready detection of another
    agent within `voice_lines.SUPPRESS_S`, and the class of that detection."""
    n, beside = 0, Counter()
    for d in ds:
        for i in np.flatnonzero(d["live"] & (d["score"] >= tau) & (d["cls"] == "absent")):
            n += 1
            w = ((np.abs(d["t"] - d["t"][i]) <= vl.SUPPRESS_S) & (d["agent"] != d["agent"][i])
                 & (d["score"] > d["score"][i]))
            if w.any():
                beside[d["cls"][np.flatnonzero(w)[np.argmax(d["score"][w])]]] += 1
    return {"absent": n, "beside_higher": sum(beside.values()), "by_class": dict(beside)}


def _stats(v: list[float], name: str) -> dict:
    v = np.asarray(v, float)
    return {f"{name}_min": _r(v.min(), 1), f"{name}_median": _r(np.median(v), 1),
            f"{name}_max": _r(v.max(), 1)}


def cmd_evaluate(sids: list[str] | None = None, record: bool = False) -> dict:
    """R2 to R4 and the witness from the stored rows; records only over every session."""
    from reticle import metrics
    from reticle.adjudication.ult_cast import THRESHOLD as CAST_TAU
    everything = audio_sessions()
    sids = sids or everything
    record = record and sorted(sids) == sorted(everything)
    ds = [session_data(s) for s in sids]
    lin = [d for d in ds if d["lineup"]]
    thr = threshold(lin, "cls", "absent")
    thr_ally = threshold(lin, "cls_ally", "impossible")
    tau = thr["tau"]
    r2 = class_rates(lin, tau, "cls", CLASSES)
    r2_ally = class_rates(lin, thr_ally["tau"], "cls_ally", ("own", "possible", "impossible", "unknown"))
    ratio = lambda a, b: (a["per_agent_min"] / b["per_agent_min"]
                          if a["per_agent_min"] is not None and b["per_agent_min"] else None)
    r3 = own_fill_test(lin, tau)
    xt = crosstalk(lin, tau)
    per = {}
    for d in ds:
        cp = cast_peaks(d["sid"])
        per[d["sid"]] = collisions(d, cp, tau, CAST_TAU)
        per[d["sid"]].update(lineup=d["lineup"], demo=d["ctx"]["demo"], player=d["ctx"]["player"],
                             live_min=_r(d["ctx"]["live_min"], 1), cast_version=cp["version"],
                             n_by_class=dict(Counter(d["cls"][(d["score"] >= tau) & d["live"]].tolist())))
    heard = []
    for sid, t, agent, why in HEARD:
        d = next(x for x in ds if x["sid"] == sid)
        heard.append({"sid": sid, "t": t, "agent": agent, "why": why,
                      **heard_witness(d, t, agent, cast_peaks(sid), tau)})
    runs = json.loads(SUMMARY.read_text(encoding="utf-8"))
    timed = [r for s, r in runs["sessions"].items() if s in sids and "decode_s" in r]
    col = [per[s]["collide"] for s in sids]
    v = {"sessions": len(ds), "sessions_scored": len(timed), "sessions_lineup": len(lin),
         "templates": runs["templates"], "agents": len(ds[0]["agents"]),
         "peaks": sum(r["peaks"] for r in timed),
         **_stats([r["decode_s"] for r in timed], "decode_s"),
         **_stats([r["score_s"] for r in timed], "score_s"),
         "live_minutes": _r(thr["live_minutes"], 1),
         "tau": _r(tau), "tau_complete": thr["complete"], "floor_max": _r(thr["floor_max"]),
         "absent_n": thr["impossible_n"], "absent_per_live_min": _r(thr["impossible_per_min"], 3),
         "tau_ally_side": _r(thr_ally["tau"]), "tau_ally_side_complete": thr_ally["complete"],
         "cast_threshold": CAST_TAU}
    for c in CLASSES:
        v[f"{c}_n"] = r2[c]["n"]
        v[f"{c}_per_live_min"] = _r(r2[c]["per_live_min"], 3)
        v[f"{c}_agent_minutes"] = _r(r2[c]["agent_minutes"], 1)
        v[f"{c}_per_agent_min"] = _r(r2[c]["per_agent_min"], 5)
    v["ratio_ally_to_absent"] = _r(ratio(r2["ally_named"], r2["absent"]), 2)
    v["ratio_enemy_to_absent"] = _r(ratio(r2["enemy_named"], r2["absent"]), 2)
    v["ratio_ally_to_enemy"] = _r(ratio(r2["ally_named"], r2["enemy_named"]), 2)
    named = {"per_agent_min": ((r2["ally_named"]["n"] + r2["enemy_named"]["n"])
                               / (r2["ally_named"]["agent_minutes"] + r2["enemy_named"]["agent_minutes"])
                               if r2["ally_named"]["agent_minutes"] + r2["enemy_named"]["agent_minutes"]
                               else None)}
    v["named_per_agent_min"] = _r(named["per_agent_min"], 5)
    v["ratio_named_to_absent"] = _r(ratio(named, r2["absent"]), 2)
    for c in ("possible", "impossible"):
        v[f"ally_side_{c}_n"] = r2_ally[c]["n"]
        v[f"ally_side_{c}_per_agent_min"] = _r(r2_ally[c]["per_agent_min"], 5)
    v["ally_side_ratio"] = _r(ratio(r2_ally["possible"], r2_ally["impossible"]), 2)
    v["crosstalk_absent"] = xt["absent"]
    v["crosstalk_beside_higher"] = xt["beside_higher"]
    v["crosstalk_share"] = _r(xt["beside_higher"] / xt["absent"], 3) if xt["absent"] else None
    for c, x in xt["by_class"].items():
        v[f"crosstalk_beside_{c}"] = x
    v.update({f"r3_{k}": (_r(x, 2) if isinstance(x, float) else x)
              for k, x in r3.items() if k != "by_agent"})
    v["r3_chance"] = _r(r3["expected"] / r3["det"], 3) if r3["det"] else None
    v["r3_inside_share"] = _r(r3["inside"] / r3["det"], 3) if r3["det"] else None
    v["r3_u_late_p"] = _r(r3["u_late_p"], 4)
    for a, x in r3["by_agent"].items():
        for k in ("sessions", "casts", "det", "inside", "intervals_hit"):
            v[f"r3_{a}_{k}"] = x[k]
        v[f"r3_{a}_expected"] = _r(x["expected"], 2)
        v[f"r3_{a}_intervals_hit_expected"] = _r(x["intervals_hit_expected"], 2)
    pairs = Counter((x["class"], x["cast_class"]) for s in sids for x in per[s]["pairs"])
    for (rc, cc), n in sorted(pairs.items()):
        v[f"r4_pair_{rc}_{cc}"] = n
    v.update(r4_ready=sum(per[s]["ready"] for s in sids), r4_collide=sum(col),
             r4_collide_expected=_r(sum(per[s]["expected"] for s in sids), 2),
             r4_near=sum(per[s]["near"] for s in sids),
             r4_live_ready=sum(per[s]["live_ready"] for s in sids),
             r4_live_collide=sum(per[s]["live_collide"] for s in sids),
             r4_same_agent=sum(per[s]["same_agent"] for s in sids),
             r4_sessions_with_collision=sum(c > 0 for c in col),
             r4_sessions_over_one=sum(c > 1 for c in col), r4_max_per_session=max(col),
             r4_median_per_session=_r(np.median(col), 1))
    for s in sids:
        v[f"r4_{s}_ready"] = per[s]["ready"]
        v[f"r4_{s}_collide"] = per[s]["collide"]
        v[f"r4_{s}_near"] = per[s]["near"]
    for h in heard:
        for k in ("score", "offset_s", "detected", "class", "rank", "agents_at_onset",
                  "top_agent", "top_score", "top_class", "cast_max", "cast_template"):
            v[f"heard_{h['sid']}_{k}"] = h.get(k)
    result = {"version": VERSION, "sessions": sids, "values": v, "threshold": thr,
              "threshold_ally_side": thr_ally, "r2": r2, "r2_ally_side": r2_ally, "r3": r3,
              "crosstalk": xt, "r4": per, "heard": heard}
    _write_json(EVALUATION, vl._jsonable(result))
    print(json.dumps(vl._jsonable(v), indent=0)[:6000])
    if record:
        deps = {"version": VERSION, "templates_key": runs["templates_key"],
                "cast_threshold": CAST_TAU,
                "ult_line": sorted({per[s]["cast_version"] for s in sids}),
                "evaluate": metrics.fingerprint(
                    utterances, agent_class, threshold, class_rates, own_fill_test, collisions,
                    heard_witness, crosstalk, _covered, _binom_tail, vl.template_class, vl.operating_tau, vl.suppress,
                    OP_RATE=vl.OP_RATE, COLLIDE_S=COLLIDE_S, HEARD_WIN=HEARD_WIN,
                    SUPPRESS_S=vl.SUPPRESS_S)}
        ctx = {"session_ids": sids, "sessions_lineup": [d["sid"] for d in lin],
               "evaluation": str(EVALUATION), "provenance": {
                   d["sid"]: vl._jsonable(d["ctx"]["provenance"]) for d in lin}}
        metrics.record("ult_ready_lines", part=f"evaluate-{TAG}", session="all-matches",
                       values=vl._jsonable(v), deps=deps, context=ctx,
                       note="ult-ready lines scored with the reader's GCC-PHAT; R2-R4")
        print(f"recorded ult_ready_lines/evaluate-{TAG}@all-matches")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("score", "evaluate"))
    ap.add_argument("--sessions", nargs="*", help="these sessions (default: all 25)")
    ap.add_argument("--force", action="store_true", help="score: reread current sessions")
    ap.add_argument("--record", action="store_true", help="evaluate: record the run")
    a = ap.parse_args(argv)
    if a.cmd == "score":
        cmd_score(a.sessions or audio_sessions(), force=a.force)
    else:
        cmd_evaluate(a.sessions, record=a.record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
