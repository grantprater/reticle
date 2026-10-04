r"""Score the spike carrier against Riot's match records.

    .\.venv\Scripts\python.exe prototypes\spike_riot_truth.py SESSION [...] --snapshot SNAP.pkl
        [--stored] [--save-rows ROWS.pkl] [--json OUT.json]

Riot's round results name each plant's planter (`bombPlanter`) and its kills
time every death; `riot_ground_truth` scores the plants' presence and time
but not who carried. This scorer measures three bindings of the `spike`
reader (`reticle.spike`) and its cross-check (`adjudication.spike_carrier`):

* **Planter slot.** On a round our team planted, `spike_carrier` stores the
  roster marker's last slot before the plant (`planter_slot`). The slot is
  the bar's PACKED position: allies pack right, so with n alive the
  survivors hold slots 5-n..4 in lineup order. The expected slot is the
  planter's place among the allies Riot's kills leave alive at the marker's
  time, in the stored lineup's order (`lineups/<sid>.json`, ally slots by
  agent; Riot names the planter's agent). Right, wrong or unread.
* **Planter channel.** The minimap's last carried glyph before the plant
  sits under the self icon or an ally icon (`carrier_channel`); it is right
  when `self` exactly where Riot's planter is the capturing player.
* **Carrier deaths.** A `carrier_lost` row the roster's alive count calls a
  death is right when Riot kills one of our allies within DEATH_TOL_MS of the
  loss and that ally held the lost slot just before dying.

Riot times map to capture time by `riot_ground_truth.fit_alignment` against
the stored deaths. By default the reader runs in memory over the crop
caches (`cli._spike_session`, then `spike_carrier.check`): no decode, nothing
written. `--snapshot` freezes the stored inputs (rounds, roster alive
counts, lineup, alignment) in a file, so two runs of different reader code
score against one stored state while a corpus rerun writes the store.
`--stored` scores the stored `spike_carrier` rows instead.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))

SPIKE_RIOT_VERSION = "spike-riot-0.1.0"
STORE = Path.home() / "reticle-store"
#: How near a Riot ally death must fall to a stored carrier loss.
DEATH_TOL_MS = 1500.0


def _below_normal() -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:                                   # noqa: BLE001 -- best effort
        pass


def snapshot(store, sid: str, rec: dict, ident: dict, ref) -> dict:
    """The stored inputs one session's scoring reads, frozen."""
    from reticle.cli import _stored_alive
    from riot_ground_truth import fit_alignment, split_deaths, stored_deaths
    man = store.read_manifest(sid)
    rs = store.read_rounds(sid, man["ingested_at"][:10])
    rt, ra = _stored_alive(store, sid, man)
    kill_like, _ = split_deaths(stored_deaths(store.root, sid))
    m = rec["match"]
    al = fit_alignment([k["gameTime"] for k in m["kills"]], [float(r["t_ms"]) for r in kill_like])
    lp = store.root / "lineups" / f"{sid}.json"
    lineup = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else None
    return {"session": sid, "rounds": None if rs is None else rs.to_pylist(),
            "roster_t": list(rt), "roster_alive": list(ra),
            "a_ms": None if al is None else al["a_ms"],
            "lineup_allies": None if lineup is None else
            [s.get("agent") for s in sorted(lineup["sides"]["ally"], key=lambda s: s["slot"])],
            "lineup_version": None if lineup is None else lineup.get("version"),
            "me": ident.get("subject"), "player_basis": ident.get("basis"),
            "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def packed_slot(order: list[str], dead: set[str], who: str) -> int | None:
    """`who`'s packed roster slot: survivors in lineup order at the right."""
    alive = [s for s in order if s not in dead]
    if who not in alive:
        return None
    return 5 - len(alive) + alive.index(who)


def orders(named: list[str | None], team: list[str]) -> list[list[str]]:
    """Every roster order the stored lineup allows: its slots named with one
    of Riot's five keep that subject; a refused slot, or one naming an agent
    Riot does not list on the team, takes any subject left over."""
    from itertools import permutations
    fixed = [x if x in team else None for x in named]
    left = [s for s in team if s not in fixed]
    free = [i for i, x in enumerate(fixed) if x is None]
    out = []
    for p in permutations(left):
        o = list(fixed)
        for i, s in zip(free, p):
            o[i] = s
        out.append(o)
    return out


def expected_slot(cands: list[list[str]], dead: set[str], who: str):
    """The packed slot every allowed order agrees on, or "order_ambiguous"."""
    got = {packed_slot(o, dead, who) for o in cands}
    return got.pop() if len(got) == 1 else "order_ambiguous"


def score(sid: str, rec: dict, snap: dict, carrier_rows: list[dict], ref) -> dict:
    from riot_ground_truth import canon
    m = rec["match"]
    a = snap["a_ms"]
    out = {"session": sid, "planter_slot": Counter(), "planter_channel": Counter(),
           "carrier_death": Counter(), "rows": []}
    if a is None:
        out["refused"] = "no_alignment"
        return out
    who = {p["subject"]: p for p in m["players"]}
    me = snap["me"]
    if me not in who:
        out["refused"] = "player_unidentified"
        return out
    my_team = who[me]["teamId"]
    agent_subject = {canon(ref.agent(p["characterId"])): s for s, p in who.items()
                     if p["teamId"] == my_team}
    named = [agent_subject.get(canon(x)) if x else None for x in (snap["lineup_allies"] or [])]
    cands = orders(named, sorted(agent_subject.values())) if len(named) == 5 else []
    out["lineup_orders"] = len(cands)
    ally_deaths = sorted((k["gameTime"], k["victim"]) for k in m["kills"]
                         if who.get(k["victim"], {}).get("teamId") == my_team)
    rstart = {}
    for k in m["kills"]:
        rstart.setdefault(k["round"], k["gameTime"] - k["roundTime"])

    def dead_at(g: float, rnd: int) -> set:
        r0 = rstart.get(rnd)
        return {v for t, v in ally_deaths if r0 is not None and r0 <= t <= g}

    def round_of(g: float) -> int | None:
        best = None
        for n, r0 in rstart.items():
            if r0 <= g and (best is None or r0 > rstart[best]):
                best = n
        return best

    rounds = {r.get("round_no"): r for r in carrier_rows if r.get("kind") == "round"}
    frames_last = {}
    for rr in sorted(m["roundResults"], key=lambda r: r["roundNum"]):
        pl = rr.get("bombPlanter")
        if not pl or not rr.get("plantRoundTime") or who.get(pl, {}).get("teamId") != my_team:
            continue
        n = rr["roundNum"]
        if n not in rstart:
            continue
        tp = a + rstart[n] + rr["plantRoundTime"]
        mine = [r for r in rounds.values() if r.get("plant_t_ms") is not None
                and abs(r["plant_t_ms"] - tp) <= 3000.0]
        row = {"riot_round": n + 1, "planter_is_me": pl == me, "plant_t_ms": round(tp)}
        if not mine:
            out["planter_slot"]["round_unpaired"] += 1
            out["planter_channel"]["round_unpaired"] += 1
            row["slot"] = "round_unpaired"
            out["rows"].append(row)
            continue
        cr = mine[0]
        ps = cr.get("planter_slot")
        if ps is None:
            out["planter_slot"]["unread"] += 1
            row["slot"] = "unread"
        else:
            want = expected_slot(cands, dead_at(ps["t_ms"] - a, n), pl) if cands else "no_lineup"
            if isinstance(want, str):
                out["planter_slot"][want] += 1
                row["slot"] = want
            else:
                ok = want == ps["slot"]
                out["planter_slot"]["right" if ok else "wrong"] += 1
                row.update(slot="right" if ok else "wrong", read_slot=ps["slot"], want_slot=want)
        ch = cr.get("planter_channel")
        if ch is None:
            out["planter_channel"]["unread"] += 1
            row["channel"] = "unread"
        else:
            ok = (ch == "self") == (pl == me)
            out["planter_channel"]["right" if ok else "wrong"] += 1
            row["channel"] = ("right" if ok else "wrong") + f":{ch}"
        out["rows"].append(row)
    used = set()
    for loss in (r for r in carrier_rows if r.get("kind") == "carrier_lost"):
        if not loss.get("death"):
            continue
        lo, hi = loss["last_marked_ms"] - a - DEATH_TOL_MS, loss["t_ms"] - a + DEATH_TOL_MS
        near = [(t, v) for t, v in ally_deaths if lo <= t <= hi]
        if not near:
            out["carrier_death"]["no_riot_death"] += 1
            continue
        if not cands:
            out["carrier_death"]["no_lineup"] += 1
            continue
        wants = [expected_slot(cands, dead_at(t - 1, round_of(t)), v) for t, v in near]
        hits = [tv for tv, w in zip(near, wants) if w == loss["slot"]]
        if hits and all(tv in used for tv in hits):
            # A marker that flickers back and is lost again binds one death twice.
            out["carrier_death"]["duplicate"] += 1
        elif hits:
            used.add(next(tv for tv in hits if tv not in used))
            out["carrier_death"]["right"] += 1
        elif "order_ambiguous" in wants:
            out["carrier_death"]["order_ambiguous"] += 1
        else:
            out["carrier_death"]["wrong"] += 1
    return out


def planter_channel(rows: list[dict], carrier: list[dict]) -> list[dict]:
    """Add each planted round's minimap carrier channel: the icon under the
    last carried glyph read within PRE_PLANT_MS before the plant."""
    from reticle.adjudication.spike_carrier import PRE_PLANT_MS, frame_state
    sc = float(rows[0].get("widget_scale") or 1.0)
    states = [frame_state(r, sc) for r in rows[1:] if r.get("kind") == "frame"]
    for r in carrier:
        if r.get("kind") != "round" or not r.get("spike_planted") or r.get("plant_t_ms") is None:
            continue
        p = r["plant_t_ms"]
        car = [s for s in states if p - PRE_PLANT_MS <= s["t_ms"] <= p and s["glyph"] == "carried"
               and s["carrier_channel"] is not None]
        r["planter_channel"] = car[-1]["carrier_channel"] if car else None
    return carrier


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--snapshot", required=True, help="frozen stored inputs (built when absent)")
    ap.add_argument("--stored", action="store_true", help="score the stored spike rows")
    ap.add_argument("--save-rows", default=None, help="pickle the reader's rows per session")
    ap.add_argument("--rows", default=None, help="score rows a --save-rows run pickled")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    _below_normal()
    from reticle.adjudication.spike_carrier import check
    from reticle.cli import _spike_session
    from reticle.store import Store
    from reticle.version import SPIKE_CARRIER_VERSION, SPIKE_VERSION
    from riot_ground_truth import Reference, identify_player, resolve_lineup_player, riot_records

    root = Path(args.store)
    store = Store(root)
    ref = Reference(root / "external" / "valorant-api", fetch=False)
    recs = riot_records(root)
    idents = identify_player(recs, root)
    snp = Path(args.snapshot)
    snaps = pickle.loads(snp.read_bytes()) if snp.is_file() else {}
    saved, results = {}, []
    for sid in args.sessions:
        if sid not in recs:
            print(f"{sid}: no Riot record")
            continue
        if sid not in snaps:
            snaps[sid] = snapshot(store, sid, recs[sid],
                                  resolve_lineup_player(recs[sid], idents[sid], ref), ref)
            snp.write_bytes(pickle.dumps(snaps))
        s = snaps[sid]
        t0 = time.perf_counter()
        if args.rows:
            rows = pickle.loads(Path(args.rows).read_bytes()).get(sid)
            if rows is None:
                print(f"{sid}: not in {args.rows}")
                continue
        elif args.stored:
            rows = store.read_events("spike", sid)
        else:
            res = _spike_session(store, sid, 1.0)
            if "skipped" in res:
                print(f"{sid}: {res['skipped']}")
                continue
            rows = res["rows"]
        carrier = check(rows, s["rounds"], s["roster_t"], s["roster_alive"])
        carrier = planter_channel(rows, carrier)
        saved[sid] = rows
        r = score(sid, recs[sid], s, carrier, ref)
        head = rows[0]
        r.update(spike_version=head.get("spike_version"), wall_s=round(time.perf_counter() - t0, 1),
                 glyph_frames=head.get("glyph_frames"), marker_frames=head.get("marker_frames"),
                 coverage={k: carrier[0].get(k) for k in ("both_read", "agree", "disagreements",
                                                         "rounds_carrier_seen", "losses",
                                                         "losses_by_witness")},
                 snapshot_taken_at=s["taken_at"], lineup_version=s["lineup_version"])
        for k in ("planter_slot", "planter_channel", "carrier_death"):
            r[k] = dict(r[k])
        results.append(r)
        print(f"{sid} [{r['spike_version']}, {r['wall_s']} s] planter slot {r['planter_slot']} "
              f"channel {r['planter_channel']} carrier deaths {r['carrier_death']} "
              f"glyph {r['glyph_frames']} marker {r['marker_frames']} "
              f"disagreements {r['coverage']['disagreements']}")
    pool = {k: dict(sum((Counter(r[k]) for r in results), Counter()))
            for k in ("planter_slot", "planter_channel", "carrier_death")}
    print("pooled", pool)
    meta = {"scorer": SPIKE_RIOT_VERSION, "spike_version": SPIKE_VERSION,
            "spike_carrier_version": SPIKE_CARRIER_VERSION, "stored": args.stored,
            "pool": pool, "sessions": results}
    if args.json:
        Path(args.json).write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    if args.save_rows:
        Path(args.save_rows).write_bytes(pickle.dumps(saved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
