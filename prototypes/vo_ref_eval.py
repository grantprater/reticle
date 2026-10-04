r"""Compare the wiki ult-line references with the game's own English voice lines.

    .\.venv\Scripts\python.exe prototypes\vo_ref_eval.py equivalence
    .\.venv\Scripts\python.exe prototypes\vo_ref_eval.py compare [--sessions SID ...]
    .\.venv\Scripts\python.exe prototypes\vo_ref_eval.py lines <Agent> --tau T

Purpose
-------
`ult_lines` read 56 wiki MP3s (and Gekko's two harvested takes) as the
templates of every agent's ultimate voice line. The game's own lines,
extracted headlessly into `reference/game-files/vo` (`vo-ref-0.1.0`), replace
them. This prototype measures the change twice, decoding no capture:

`equivalence` scores each wiki line against each game X-cast line of the
same agent with the production scorer, GCC-PHAT on the waveform
(`ult_lines.phat_tracks`'s whitening and band), clip against clip. A score
near 1 says the two are one recording; the production reader would then
find the same peaks with either.

`compare` scores both template sets on the stored audio-gate log-mel of the
match sessions with Riot records (formulation F-A of `voice_lines.py`: the
template less its band means at unit norm against the session less its band
medians), since F-B, the production scorer, needs the capture's audio
decoded and this run decodes none. Each set gets its own operating
threshold, the lowest at which lineup-impossible detections fall to
`voice_lines.OP_RATE` per live minute, then:

* own recall: the player's X casts the tray owner accepts
  (`voice_lines.own_x_casts`, alive by construction) with an `own` detection
  in the agent's cast window (`ult_cast.cast_window`);
* naming: at each such cast, whether the best selected detection in the
  window names the player's agent;
* Riot: per player, the clusters of selected detections of the player's
  agent on the player's side (`ally` or `enemy` line, relative to the
  capturing player) against Riot's `ultimateCasts`; recall is the matched
  share of Riot's casts, over-count the excess per live minute;
* false fires: impossible detections per live minute, and, at the other
  set's threshold, what each set's impossible rate would be.

The candidate set is the full roster of each template set: F-A's threshold
is defined by the impossible class, which needs templates of agents outside
the match. `ult_cast` names the match's agents when it classes peaks.

Store: `analysis/vo-ref-eval/0.1.0/` (JSON results). Metrics recorded under
series `vo_ref_eval`. Predictions: the store's `notes/predictions.jsonl`,
task `game-vo-20261003`.
"""
from __future__ import annotations

import os
import sys

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import voice_lines as vl  # noqa: E402  sessions, context, F-A tracks, operating point
    import riot_ground_truth as rgt  # noqa: E402  Riot records and the capturing player
from reticle import ult_lines  # noqa: E402
from reticle.adjudication.ult_cast import cast_window  # noqa: E402

VERSION = "vo-ref-eval-0.1.0"
STORE = vl.STORE
OUT = STORE / "analysis" / "vo-ref-eval" / "0.1.0"
#: Selected detections of one agent and side closer than this are one cast (s).
CLUSTER_S = 5.0


def _below_normal() -> None:
    vl._below_normal()


# ---------------------------------------------------------------------------
# Template sets
# ---------------------------------------------------------------------------

def wiki_set() -> list[dict]:
    """The wiki set as `ult_lines` declared it before vo-ref: name, agent, variant, path."""
    m = json.loads((ROOT / "prototypes" / "data" / "ult_lines_wiki.json").read_text(encoding="utf-8"))
    vd = STORE / ult_lines.VOICE_DIR
    return [{**e, "path": vd / e["file"]} for e in m["templates"]]


def game_set() -> list[dict]:
    """The game set `ult_lines` declares now (`templates/ult_lines.json`)."""
    m = ult_lines.load_manifest()
    vd = STORE / ult_lines.manifest_dir(m)
    return [{**e, "path": vd / e["file"]} for e in m["templates"]]


def logmel_template(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(the floored log-mel span, the waveform span) of one line, as `ult_lines` cuts it."""
    y = ult_lines.decode_template(path)
    L, ok, _ = ult_lines.log_mel(y, np.ones(len(y), bool), ult_lines.RATE, xp=np)
    T, k0, k1 = ult_lines.trim_floor(L, ok)
    return T, y[k0 * ult_lines.HOP_N:k1 * ult_lines.HOP_N]


def phat_pair(a: np.ndarray, b: np.ndarray, rate: int = ult_lines.RATE,
              band=ult_lines.PHAT_BAND) -> tuple[float, float]:
    """(best GCC-PHAT score of b against a over every lag, that lag in s), with
    `ult_lines.phat_tracks`'s band and scale: a perfect match reads 1."""
    n = 1 << int(math.ceil(math.log2(len(a) + len(b))))
    f = np.arange(n // 2 + 1) * rate / n
    mask = ((f >= band[0]) & (f <= band[1])).astype(np.float64)
    G = np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n))
    G = G / (np.abs(G) + 1e-20) * mask
    r = np.fft.irfft(G, n) * (n / (2.0 * mask.sum()))
    k = int(np.argmax(r))
    lag = k if k < n // 2 else k - n
    return float(r[k]), lag / rate


def game_x_lines() -> list[dict]:
    """Every X-slot line of vo-ref, whichever event plays it: name, agent, variant, path."""
    d = STORE / ult_lines.VO_DIR
    rows = [json.loads(x) for x in (d / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return [{"name": f"{r['event']}__{r['media']}", "agent": vl.norm_agent(r["agent"]),
             "variant": r["heard_by"] or "any", "event": r["event"], "path": d / r["flac"]}
            for r in rows if r["slot"] == "X"]


def cmd_equivalence() -> dict:
    """Per wiki line, the best game X line of its agent by PHAT."""
    wiki, game = wiki_set(), game_x_lines()
    wv = {t["name"]: logmel_template(t["path"])[1] for t in wiki}
    gv = {t["name"]: logmel_template(t["path"])[1] for t in game}
    rows = []
    for w in wiki:
        cands = [g for g in game if g["agent"] == w["agent"]]
        sc = [(phat_pair(wv[w["name"]], gv[g["name"]]), g) for g in cands]
        sc.sort(key=lambda x: -x[0][0])
        best = sc[0] if sc else None
        rows.append({"wiki": w["name"], "agent": w["agent"], "variant": w["variant"],
                     "best_game": best[1]["name"] if best else None,
                     "best_game_variant": best[1]["variant"] if best else None,
                     "score": round(best[0][0], 4) if best else None,
                     "lag_s": round(best[0][1], 3) if best else None,
                     "runner_up": round(sc[1][0][0], 4) if len(sc) > 1 else None,
                     "self_ref": round(phat_pair(wv[w["name"]], wv[w["name"]])[0], 4)})
    same_variant = sum(r["best_game_variant"] in (r["variant"], "any") for r in rows if r["best_game"])
    vals = {"wiki_lines": len(rows), "with_game_line": sum(r["best_game"] is not None for r in rows),
            "score_median": float(np.median([r["score"] for r in rows if r["score"] is not None])),
            "score_min": min(r["score"] for r in rows if r["score"] is not None),
            "score_ge_0_5": sum((r["score"] or 0) >= 0.5 for r in rows),
            "best_is_same_variant": same_variant}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "equivalence.json").write_text(json.dumps({"version": VERSION, "summary": vals, "rows": rows},
                                                     indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['wiki']:24s} -> {str(r['best_game']):34s} {r['score']}  lag {r['lag_s']}  "
              f"runner-up {r['runner_up']}")
    print(json.dumps(vals))
    return vals


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def riot_sessions() -> dict[str, dict]:
    """Session -> Riot record, for the match sessions with stored audio features."""
    recs = rgt.riot_records(STORE)
    return {s: d for s, d in recs.items() if vl._has_features(s)
            and (STORE / "events" / "tray_drop" / f"{s}.jsonl").is_file()}


def riot_players(sid: str, d: dict, ident: dict, ref) -> list[dict] | None:
    """Each Riot player's agent (asset spelling), side relative to the capturing
    player, and ultimate casts; None when the capturing player is unknown."""
    ident = rgt.resolve_lineup_player(d, ident, ref)
    me = ident.get("subject")
    if me is None:
        return None
    ps = d["match"]["players"]
    team = next(p["teamId"] for p in ps if p["subject"] == me)
    return [{"agent": vl.norm_agent(ref.agent(p["characterId"])),
             "side": "ally" if p["teamId"] == team else "enemy",
             "me": p["subject"] == me,
             "ult_casts": int(((p.get("stats") or {}).get("abilityCasts") or {}).get("ultimateCasts") or 0)}
            for p in ps]


def set_templates(temps: list[dict]) -> list[dict]:
    out = []
    for t in temps:
        T, _ = logmel_template(t["path"])
        out.append({**t, "T": vl.prepare(T), "frames": len(T)})
    return out


def detections(sid: str, f: dict, temps: list[dict], ctx: dict) -> dict:
    """F-A peaks of one set in one session, with class, liveness and time."""
    W = vl.session_matrix(f, "F-A")
    tracks = vl.ncc_tracks(W, [t["T"] for t in temps], xp=np)
    pk = ult_lines.track_peaks(tracks, [t["frames"] for t in temps])
    del tracks
    t = pk["frame"].astype(np.float64) * ult_lines.HOP
    j = pk["tpl"].astype(np.int64)
    cls = np.array([class_of(temps[k], ctx) for k in range(len(temps))], object)[j] \
        if len(j) else np.zeros(0, object)
    at = np.clip((t / vl.STEP).astype(np.int64), 0, len(ctx["live"]) - 1)
    return {"t": t, "j": j, "score": pk["score"].astype(np.float64), "cls": cls,
            "live": ctx["live"][at],
            "agent": np.array([temps[k]["agent"] for k in j], object),
            "variant": np.array([temps[k]["variant"] for k in j], object)}


def class_of(t: dict, ctx: dict) -> str:
    """`voice_lines.template_class` for one template; a line heard by both teams
    (`any`) is own for the player's agent, possible where either side names
    its agent, impossible where neither side could hold it."""
    if t["variant"] != "any":
        return vl.template_class(t["agent"], t["variant"], ctx["sides"], ctx["player"])
    if ctx["player"] is not None and t["agent"] == ctx["player"]:
        return "own"
    c = [vl.template_class(t["agent"], v, ctx["sides"], None) for v in vl.VARIANTS]
    if "possible" in c:
        return "possible"
    return "impossible" if all(x == "impossible" for x in c) else "unknown"


def clusters(ts: np.ndarray, gap: float = CLUSTER_S) -> int:
    """How many groups `ts` form, splitting where consecutive times differ by more than gap."""
    if len(ts) == 0:
        return 0
    ts = np.sort(ts)
    return 1 + int((np.diff(ts) > gap).sum())


def score_session(d: dict, ctx: dict, tau: float, players: list[dict] | None) -> dict:
    sel = (d["score"] >= tau) & d["live"]
    out = {"impossible": int((sel & (d["cls"] == "impossible")).sum()),
           "possible": int((sel & (d["cls"] == "possible")).sum()),
           "own": int((sel & (d["cls"] == "own")).sum()), "live_min": ctx["live_min"]}
    casts = ctx["own"]
    win = cast_window(ctx["player"])
    hit = named = 0
    for c in casts:
        dt = d["t"] - c["t"]
        w = sel & (dt >= win[0]) & (dt <= win[1])
        if (w & (d["cls"] == "own")).any():
            hit += 1
        if w.any():
            k = np.flatnonzero(w)[np.argmax(d["score"][w])]
            named += int(d["agent"][k] == ctx["player"])
    out.update(own_casts=len(casts), own_hits=hit, own_named=named)
    if players is not None:
        rm = ro = rc = 0
        for p in players:
            if sum(q["agent"] == p["agent"] for q in players) > 1:
                continue              # a mirror agent: the line cannot tell the two apart
            m = sel & (d["agent"] == p["agent"]) & np.isin(d["variant"], [p["side"], "any"])
            n = clusters(d["t"][m])
            rc += p["ult_casts"]
            rm += min(n, p["ult_casts"])
            ro += max(n - p["ult_casts"], 0)
        out.update(riot_casts=rc, riot_matched=rm, riot_over=ro)
    return out


def pool(rows: list[dict]) -> dict:
    s = lambda k: sum(r.get(k, 0) for r in rows)
    live = s("live_min")
    return {"sessions": len(rows), "live_min": round(live, 1),
            "impossible_per_min": round(s("impossible") / live, 4),
            "possible_per_min": round(s("possible") / live, 4),
            "own_casts": s("own_casts"), "own_recall": round(s("own_hits") / max(s("own_casts"), 1), 4),
            "own_named": round(s("own_named") / max(s("own_casts"), 1), 4),
            "riot_casts": s("riot_casts"),
            "riot_recall": round(s("riot_matched") / max(s("riot_casts"), 1), 4),
            "riot_over_per_min": round(s("riot_over") / live, 4)}


def cmd_compare(sids: list[str] | None) -> dict:
    _below_normal()
    t0 = time.time()
    recs = riot_sessions()
    sids = sorted(sids or recs)
    ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    idents = rgt.identify_player(rgt.riot_records(STORE), STORE)
    sets = {"wiki": set_templates(wiki_set()), "game": set_templates(game_set())}
    per = {k: {} for k in sets}
    ctxs, players, stamps = {}, {}, {}
    for sid in sids:
        f = vl.session_features(sid)
        n = len(f["L"])
        ctx = vl.session_context(sid, n, [])
        ctxs[sid] = ctx
        players[sid] = riot_players(sid, recs[sid], idents[sid], ref)
        stamps[sid] = {"audio_features": str(f.get("version", "")), **ctx["provenance"]}
        for k, temps in sets.items():
            per[k][sid] = detections(sid, f, temps, ctx)
        print(f"{sid}: scored ({time.time() - t0:.0f}s)", flush=True)
    live = sum(c["live_min"] for c in ctxs.values() if c["sides"] is not None)
    taus = {k: vl.operating_tau(np.concatenate([d["score"][(d["cls"] == "impossible") & d["live"]]
                                                for s, d in per[k].items() if ctxs[s]["sides"] is not None]),
                                live) for k in sets}
    res = {"version": VERSION, "sessions": sids, "taus": taus, "stamps": stamps,
           "templates": {k: len(v) for k, v in sets.items()}, "results": {}}
    for k in sets:
        for tname, tau in (("own_tau", taus[k]), ("wiki_tau", taus["wiki"])):
            rows = [score_session(per[k][s], ctxs[s], tau, players[s]) for s in sids
                    if ctxs[s]["sides"] is not None]
            res["results"][f"{k}@{tname}"] = {"tau": tau, **pool(rows)}
        res["results"][f"{k}@own_tau"]["per_agent_own"] = per_agent(per[k], ctxs, taus[k], sids)
    res["elapsed_s"] = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "compare.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    for k, v in res["results"].items():
        print(k, json.dumps({a: b for a, b in v.items() if a != "per_agent_own"}))
    return res


def cmd_agent_lines(agent: str, tau: float) -> dict:
    """Every X line vo-ref holds for one agent, scored by F-A at `tau` on the
    Riot sessions whose match holds the agent: per line, the clusters of
    selected live detections against Riot's casts of the agent on each side,
    and own hits where the capturing player is the agent. It decides which of
    the agent's X events the game plays at the cast."""
    _below_normal()
    recs = riot_sessions()
    ref = rgt.Reference(STORE / "external" / "valorant-api", fetch=False)
    idents = rgt.identify_player(rgt.riot_records(STORE), STORE)
    temps = set_templates([t for t in game_x_lines() if t["agent"] == agent])
    out = {t["name"]: Counter() for t in temps}
    for sid in sorted(recs):
        players = riot_players(sid, recs[sid], idents[sid], ref)
        if not players or not any(p["agent"] == agent for p in players):
            continue
        f = vl.session_features(sid)
        ctx = vl.session_context(sid, len(f["L"]), [])
        d = detections(sid, f, temps, ctx)
        sel = (d["score"] >= tau) & d["live"]
        win = cast_window(agent)
        for j, t in enumerate(temps):
            m = sel & (d["j"] == j)
            c = out[t["name"]]
            c["sessions"] += 1
            c["clusters"] += clusters(d["t"][m])
            for p in players:
                if p["agent"] == agent:
                    c[f"riot_{p['side']}"] += p["ult_casts"]
            if ctx["player"] == agent:
                for oc in ctx["own"]:
                    dt = d["t"][m] - oc["t"]
                    c["own_casts"] += 1
                    c["own_hits"] += int(((dt >= win[0]) & (dt <= win[1])).any())
        print(sid, {k: dict(v) for k, v in out.items()}, flush=True)
    res = {"agent": agent, "tau": tau, "lines": {k: dict(v) for k, v in out.items()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"lines-{agent}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def per_agent(ds: dict, ctxs: dict, tau: float, sids: list[str]) -> dict:
    out = defaultdict(lambda: [0, 0])
    for s in sids:
        c = ctxs[s]
        if c["sides"] is None:
            continue
        r = score_session(ds[s], c, tau, None)
        out[c["player"]][0] += r["own_hits"]
        out[c["player"]][1] += r["own_casts"]
    return {a: f"{h}/{n}" for a, (h, n) in sorted(out.items(), key=lambda x: str(x[0]))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("equivalence")
    c = sub.add_parser("compare")
    c.add_argument("--sessions", nargs="*")
    g = sub.add_parser("lines")
    g.add_argument("agent")
    g.add_argument("--tau", type=float, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "equivalence":
        cmd_equivalence()
    elif a.cmd == "lines":
        cmd_agent_lines(a.agent, a.tau)
    else:
        cmd_compare(a.sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
