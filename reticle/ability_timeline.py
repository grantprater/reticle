"""Build ability-use claims from independent stored evidence.

Milestone B of ``docs/ABILITY_ENTITY_INFERENCE_DESIGN.md``.  Tray drops are
bounded observations of a state transition, not unconditional casts.  This
module preserves the possible transition meanings and never requires a minimap
candidate.  Optional materialization drives the existing prototype reader over
demo sources, then consumes its version-stamped caches.

Owns [owns:ability-cast].
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import tray
from .ability_coverage import build_inventory
from .rounds import in_round_window
from .store import DEFAULT_STORE


ABILITY_TIMELINE_VERSION = "ability-timeline-0.1.0"
_STEP = re.compile(r"\.step(\d+(?:\.\d+)?)\.")
TRANSITION_ALTERNATIVES = ("commit", "activation", "mode_transition", "end")


def _step_ms(source_path: str) -> float | None:
    match = _STEP.search(Path(source_path).name)
    if not match:
        return None
    try:
        step = float(match.group(1)) * 1000.0
    except ValueError:
        return None
    return step if step > 0 else None


def _audio_references(root: Path) -> list[dict]:
    out = []
    folder = root / "reference" / "assets" / "ability_sfx"
    # The established filename contract ends in __SESSION_TIMEs.ext.  Earlier
    # name portions are descriptive only and cannot override reference identity.
    pattern = re.compile(r"__(?P<session>[0-9a-f]+)_(?P<time>[0-9.]+)s\.[^.]+$")
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        if not path.is_file():
            continue
        match = pattern.search(path.name)
        if not match:
            continue
        out.append({
            "path": path.relative_to(root).as_posix(),
            "session_id": match.group("session"),
            "t_ms": float(match.group("time")) * 1000.0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return out


#: A drop this long before the death that ends the player's kit already
#: belongs to it: the death verdict's time is the killfeed entry, which trails
#: the death screen that blanks the tray.
DEATH_LEAD_MS = 1000.0
#: The phases whose drops can be the player's casts (`gametime`'s names).
CAST_PHASES = ("round_live", "post_plant")
#: The ultimate's slot; `tray` reads slot 3 as the ultimate.
ULT_SLOT = tray.SLOT_KEYS[3]
#: The least `from` fill of an X slot that the gate reads as full; an X drop
#: from less is `partial_charge`. `player_tray_casts` gives the measurement.
FULL_MIN = 0.8


def _kit_end(window: tuple, ends: set, deaths_ms, agent: str | None,
             second_lives_ms, revives_ms, report_deaths: dict | None
             ) -> tuple[float | None, list[list]]:
    """(the first of the player's deaths in the round `window` that ends the
    player's kit, or None; the deaths before it that the game undid, each as
    [t_ms, why]). `player_tray_casts` says how a death is undone."""
    a, z, close = window
    inside = lambda xs: sorted(e["t_first"] for e in in_round_window(
        [{"t_first": float(x)} for x in xs], a, z, close, ends))
    deaths = inside(deaths_ms)
    undone = {}
    if agent == "Phoenix":
        lives = set(inside(second_lives_ms))
        counted = (report_deaths or {}).get(a)
        if counted is None or counted <= sum(t not in lives for t in deaths):
            undone.update({t: "run_it_back" for t in deaths if t in lives})
    if agent == "Clove":
        revives = inside(revives_ms)
        for t, nxt in zip(deaths, deaths[1:] + [float("inf")]):
            if any(t <= r < nxt for r in revives):
                undone[t] = "not_dead_yet"
    end = next((t for t in deaths if t not in undone), None)
    return end, [[t, undone[t]] for t in deaths if t in undone and (end is None or t < end)]


def player_tray_casts(drops: list[dict], phase_of, rounds: list[dict],
                      player_deaths_ms: list[float], *, agent: str | None = None,
                      second_lives_ms=(), revives_ms=(),
                      report_deaths: dict | None = None) -> list[dict]:
    """Which of a session's tray drops (`tray.drops`) are the local player's casts.

    The tray shows the player's kit only while the player lives; afterwards it
    shows a spectated teammate's, and the switch empties several slots at once.
    So a drop is the player's cast when it falls in a live phase, before the
    death that ends the player's kit in its round less DEATH_LEAD_MS, and is
    not suspect once `tray.flag_suspect` is recomputed among the drops that
    pass, so a cast is not tainted by the spectator switch after it (measured
    and labelled in `prototypes/tray_suspect_reasons.py` and
    `prototypes/label_tray_objects.py`).

    `phase_of(t_ms)` is the game phase; `rounds` are the stored round rows, and
    `rounds.in_round_window` decides the round of a drop and of a death, so a
    death on the instant two rounds touch belongs to the round it ends.
    `player_deaths_ms` are the player's killfeed deaths
    (`rounds.player_death_times`), and `agent` is the player's agent as the
    arbiter names it. A death ends the kit unless the game undid it, and among
    the player's agents it undoes one for two only
    [domain:rounds/resurrection-mechanics]:

    * **Phoenix.** A death the killfeed badge calls a second life
      (`second_lives_ms`, `rounds.player_second_life_times`) is a Run It Back
      death, after which Phoenix returns alive. His X pips do not fall while
      the ult runs [domain:abilities/phoenix-run-it-back-expiry-flash] and
      fall at its end [domain:abilities/caster-hears-own-ult-line], so that
      drop is his cast. The combat report flags KILLED YOU on the real death
      only [domain:rounds/run-it-back-in-report]; where the round's report
      (`report_deaths`, its KILLED YOU count keyed by the round's start)
      counts more deaths than the killfeed's real ones, the killfeed missed a
      real death, no instant after the second life is known to be Phoenix's,
      and the second life still ends the kit.
    * **Clove.** Not Dead Yet needs Clove's death
      [domain:abilities/clove-c-and-x-need-a-target], and its killfeed entry
      is the revive itself [domain:killfeed/revive-entries]. A death followed
      by the player's own revive entry (`revives_ms`) before her next death in
      the round does not end her kit, so a drop between the death and the
      revive meets the remaining tests like any other.

    A drop that passes those tests can still fail one more, and only in the X
    slot. The X slot's pips are the ultimate charge: the ultimate is cast only
    when every pip is lit, and the cast empties them
    [domain:abilities/ult-charge-pips]. So an X drop from a slot that was not
    full is refused as `partial_charge`. The test runs after the co-occurrence
    test, so a part-filled X drop still counts as a transition of the tray
    beside another slot's drop, and the rule changes no other slot's verdict.

    *Full* is read from the drop's own `from`: the slot's teal count on the
    last clean sample before the drop over the slot's p90 clean count in the
    session (`tray.fills`), so no per-agent constant enters. The reading has
    two states. A full slot also lights the bar under its pips and reads about
    1; a slot short of full lights only its lit pips. On six sessions' stored
    crops, [metric:tray/x-fill-states@six-sessions#not_full=9685] of
    [metric:tray/x-fill-states@six-sessions#clean_samples=11747] clean samples
    read 0.2 or less (99th percentile at most
    [metric:tray/x-fill-states@six-sessions#not_full_p99_max=0.164]),
    [metric:tray/x-fill-states@six-sessions#full=1998] read 0.8 to 1.1, and
    [metric:tray/x-fill-states@six-sessions#between=39] fell between. The slot
    was full when `from` reaches FULL_MIN, 0.80. The
    [metric:ult_lines/x-fill-full@all-sessions#x_casts_with_line=46] in-round
    X casts with an own ult line on the 19 lineup sessions fell from
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_min=0.9] to
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_max=1.18],
    median [metric:ult_lines/x-fill-full@all-sessions#with_line_from_median=0.98]
    with a median absolute deviation of
    [metric:ult_lines/x-fill-full@all-sessions#with_line_from_mad=0.03].
    FULL_MIN sits [metric:ult_lines/x-fill-full@all-sessions#margin_below_lowest_with_line=0.1]
    under the lowest of them, more than three deviations, and far above a
    part-charged slot's reading. No X drop the other tests pass on those
    sessions fell from between 0.58 and 0.90, so any value in that gap gives
    the same verdicts; the value is not fitted to the four drops it refuses
    ([metric:ult_lines/x-fill-full@all-sessions#partial_from_min=0.36] to
    [metric:ult_lines/x-fill-full@all-sessions#partial_from_max=0.58]).

    Those four drops, and every fill above 1, are teal added to the bar's box
    for one sample by something drawn behind or over the tray, which is
    semi-transparent. On `ff636d173b07` in round 1, every X pip unlit, the
    map's teal trim crossed the box at 47.55 s: the slot read
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_before=0.08],
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_from=0.36] and
    [metric:tray/x-fill-states@six-sessions#ff636d173b07_48_x_at=0.0], and the
    trim's leaving read as a drop. On `c40d950031bb` at 769.0 s Sova's glowing
    bow lifted a part-lit slot from
    [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_before=0.07]
    to [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_from=0.58]
    and it fell back to
    [metric:tray/x-fill-states@six-sessions#c40d950031bb_769_x_at=0.12].
    Nothing emptied either slot. The lined cast's 1.18 (`75a55a296d3b`
    1010.5 s) is a teal glow behind the X icon on the last sample before the
    cast, over a slot that read a median of
    [metric:tray/x-fill-states@six-sessions#75a55a296d3b_1011_x_prior10_median=0.96]
    on the ten samples before. A fill above 1 is a full slot plus added teal,
    never more charge, and the teal can lift a part-charged slot past FULL_MIN
    only by adding most of a full bar in one sample; none of the four did.

    The gate does not test the rule's other half, that the cast empties the
    pips. `3694746e4e54` at 1062.0 s passes as a cast: the bow's glow lifted a
    full slot to [metric:tray/x-fill-states@six-sessions#3694746e4e54_1062_x_from=1.33],
    and the slot still read
    [metric:tray/x-fill-states@six-sessions#3694746e4e54_1062_x_at=1.08] after
    the "drop".

    Every drop comes back with `player_cast`, the first `reason` that refused
    it, the round's `first_player_death_ms`, the `kit_end_ms` the gate used,
    and the `undone_deaths` before it.
    """
    ends = {r["t_end_ms"] for r in rounds}
    windows = [(r["t_start_ms"], r["t_end_ms"], r["t_close_ms"]) for r in rounds]
    deaths = [{"t_first": x} for x in player_deaths_ms]
    kit = {w: _kit_end(w, ends, player_deaths_ms, agent, second_lives_ms, revives_ms,
                       report_deaths) for w in windows}
    rows = []
    for d in drops:
        t = d["t_ms"]
        rnd = next((w for w in windows if in_round_window([{"t_first": t}], *w, ends)), None)
        first = (min((e["t_first"] for e in in_round_window(deaths, *rnd, ends)), default=None)
                 if rnd else None)
        end, undone = kit[rnd] if rnd else (None, [])
        phase = phase_of(t)
        reason = ("no_round" if rnd is None
                  else "after_player_death" if end is not None and t >= end - DEATH_LEAD_MS
                  else None if phase in CAST_PHASES else f"phase:{phase}")
        rows.append({**d, "phase": phase,
                     "round_ms": None if rnd is None else [float(rnd[0]), float(rnd[2])],
                     "first_player_death_ms": first, "kit_end_ms": end,
                     "undone_deaths": undone, "reason": reason})
    keep = [r for r in rows if r["reason"] is None]
    for r, (*_x, sus) in zip(keep, tray.flag_suspect(
            [(r["t_ms"] / 1000.0, r["slot"], r["from"], r["to"], r["forced"]) for r in keep])):
        if sus:
            r["reason"] = "forced" if r["forced"] else "cooccur_among_casts"
    # After the co-occurrence test, so a part-filled X drop still counts as a
    # transition of the tray beside another slot's drop.
    for r in keep:
        if r["reason"] is None and r["slot"] == ULT_SLOT and r["from"] < FULL_MIN:
            r["reason"] = "partial_charge"
    for r in rows:
        r["player_cast"] = r["reason"] is None
    return rows


def stored_gate_inputs(store, session_id: str, date: str, rounds: list[dict],
                       agent: str | None) -> tuple[dict, dict]:
    """(the keyword inputs of `player_tray_casts` beyond the drops and rounds,
    read from storage; their stamps). Decodes nothing.

    The phase is `gametime`'s over the stored HUD, and the deaths are the HUD's
    killfeed tracks. Second lives come from the stored badge reads, which only
    a current `killfeed_portrait` stream carries
    (`adjudication.death.stored_second_life`). Revives are the player's own
    revive entries among the stored `death` verdicts. The report's death
    counts are the stored `combat_report_round` rows where a report was read.
    """
    from . import gametime, stalls
    from .adjudication.death import stored_second_life
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .rounds import player_death_times, player_second_life_times
    from .version import PLAYER_CAST_VERSION

    hud = store.read_hud(session_id, date)
    gt = gametime.build_session_gametime(session_id, hud, rounds,
                                         stall_list=stalls.for_session(store, session_id, date))
    badges = stored_second_life(store.read_events_kind(
        "killfeed_portrait", session_id, "second_life_observation"), KILLFEED_PORTRAIT_VERSION)
    verdicts = [r for r in store.read_events("death", session_id)
                if r.get("kind") == "death_verdict"]
    report = [r for r in store.read_events("combat_report_round", session_id)
              if r.get("kind") == "round"]
    inputs = {
        "phase_of": lambda t: gt.game_time_at(t).phase,
        "player_deaths_ms": player_death_times(hud),
        "agent": agent,
        "second_lives_ms": player_second_life_times(hud, badges),
        "revives_ms": sorted(float(r["t_ms"]) for r in verdicts
                             if r.get("is_revive") and r.get("kf_player_kill")),
        "report_deaths": {float(r["t_start_ms"]): int(r["deaths"]) for r in report
                          if r.get("verdict_source") == "combat_report"
                          and r.get("deaths") is not None},
    }
    head = lambda rows, key: rows[0].get(key) if rows else None
    stamps = {"player_cast": PLAYER_CAST_VERSION,
              "hud": (hud.schema.metadata or {}).get(b"hud_version", b"").decode() or "unstamped",
              "gametime": gametime.GAMETIME_VERSION,
              "killfeed_portrait": KILLFEED_PORTRAIT_VERSION if badges is not None else None,
              "death": head(verdicts, "death_adjudication_version"),
              "combat_report_round": head(report, "combat_report_round_version")}
    return inputs, stamps


def build_timeline(root: str | Path) -> dict:
    """Return deterministic use claims from the current evidence inventory."""
    root = Path(root).resolve()
    inventory = build_inventory(root)
    source_hashes = {r["path"]: r["sha256"]
                     for r in inventory["manifest"]["source_files"]}
    audio = _audio_references(root)
    spectated = {row["session_id"] for row in inventory["sessions"]
                 if "spectator" in (row.get("tags") or [])}
    labels_by_ability = defaultdict(list)
    for row in inventory["source_windows"]:
        if row["source_kind"] == "human_ability_label" and row.get("ability_id"):
            labels_by_ability[(row["session_id"], row["ability_id"])].append(row)

    claims = []
    for row in inventory["source_windows"]:
        if row["source_kind"] != "tray_cast_candidate":
            continue
        t_ms = float(row["t_observed_ms"])
        step_ms = _step_ms(row["source_path"])
        occurrence_start = max(0.0, t_ms - step_ms) if step_ms else None
        label_candidates = [
            r["window_id"] for r in labels_by_ability.get(
                (row["session_id"], row.get("ability_id")), [])
            if t_ms - 2000.0 <= r["t_observed_ms"] <= t_ms + 15000.0
        ] if row.get("ability_id") else []
        audio_candidates = [
            a for a in audio if a["session_id"] == row["session_id"]
            and abs(a["t_ms"] - t_ms) <= max(step_ms or 0.0, 100.0)
        ]
        source_ref = {
            "path": row["source_path"],
            "record": row["source_record"],
            "sha256": source_hashes.get(row["source_path"]),
        }
        claims.append({
            "use_claim_id": f"use:{row['session_id']}:{Path(row['source_path']).name}:"
                            f"{row['source_record']}",
            "session_id": row["session_id"],
            "agent": row.get("agent"),
            "ability_id": row.get("ability_id"),
            "ability": row.get("ability"),
            "slot": row.get("key"),
            # A spectator clip reads the OBSERVED player's tray, so the caster is
            # whoever the camera is on, not whoever is holding the mouse.
            "owner": (None if not row.get("agent")
                      else "observed_player" if row["session_id"] in spectated
                      else "local_player"),
            "observed_t_ms": t_ms,
            "available_t_ms": t_ms,
            "occurrence_interval_ms": [occurrence_start, t_ms],
            "sampling_step_ms": step_ms,
            "transition": None,
            "transition_alternatives": list(TRANSITION_ALTERNATIVES),
            "status": "suspect" if row.get("suspect") else "candidate",
            "status_reason": ("reader_flagged_drop" if row.get("suspect")
                              else "single_slot_drop"),
            "identity_status": ("setup_agent_and_reference_slot" if row.get("ability_id")
                                else "unresolved"),
            "source_evidence": [source_ref],
            "audio_reference_candidates": audio_candidates,
            "human_label_candidates": sorted(label_candidates),
            "minimap_required": False,
            "raw": row.get("raw"),
        })

    # A reader change creates a new cache beside the old one.  Equivalent rows
    # are two provenance roots for one observation, not two game events.
    equivalent = defaultdict(list)
    for claim in claims:
        key = (claim["session_id"], claim["observed_t_ms"], claim["slot"],
               json.dumps(claim.get("raw"), sort_keys=True))
        equivalent[key].append(claim)
    merged_claims = []
    for key, same in equivalent.items():
        claim = dict(same[0])
        claim["source_evidence"] = sorted(
            (e for row in same for e in row["source_evidence"]),
            key=lambda e: (e["path"], e["record"]),
        )
        raw_key = hashlib.sha256(key[3].encode()).hexdigest()[:8]
        claim["use_claim_id"] = (f"use:{key[0]}:{key[1]:g}:{key[2]}:{raw_key}")
        merged_claims.append(claim)
    claims = merged_claims

    conflicts = list(inventory["conflicts"])
    grouped = defaultdict(list)
    for claim in claims:
        grouped[(claim["session_id"], claim["observed_t_ms"], claim["slot"])].append(claim)
    for key, alternatives in grouped.items():
        raw_values = {json.dumps(c.get("raw"), sort_keys=True) for c in alternatives}
        if len(raw_values) > 1:
            conflicts.append({
                "reason": "multiple_cast_cache_interpretations",
                "session_id": key[0], "observed_t_ms": key[1], "slot": key[2],
                "use_claim_ids": sorted(c["use_claim_id"] for c in alternatives),
            })

    claims.sort(key=lambda r: (r["session_id"], r["observed_t_ms"], r["use_claim_id"]))
    summary = {
        "use_claims": len(claims),
        "equivalent_cache_rows_collapsed": sum(len(v) - 1 for v in equivalent.values()),
        "sessions_with_claims": len({r["session_id"] for r in claims}),
        "clean_candidates": sum(r["status"] == "candidate" for r in claims),
        "suspect_candidates": sum(r["status"] == "suspect" for r in claims),
        "identified_candidates": sum(r["ability_id"] is not None for r in claims),
        "audio_reference_candidates": sum(bool(r["audio_reference_candidates"]) for r in claims),
        "label_candidate_links": sum(len(r["human_label_candidates"]) for r in claims),
        "by_slot": dict(sorted(Counter(r["slot"] for r in claims).items())),
        "conflicts": len(conflicts),
    }
    return {
        "manifest": {
            "schema_version": 1,
            "producer_version": ABILITY_TIMELINE_VERSION,
            "store_root": str(root),
            "coverage_producer_version": inventory["manifest"]["producer_version"],
            "source_files": inventory["manifest"]["source_files"],
            "audio_reference_files": audio,
            "summary": summary,
            "limits": [
                "Tray drops are use candidates, not resolved cast semantics.",
                "Source-linked audio cuts are references, not independent detections.",
                "Human label links are temporal candidates, not parent-child adjudications.",
            ],
        },
        "use_claims": claims,
        "conflicts": sorted(conflicts, key=lambda r: json.dumps(r, sort_keys=True)),
    }


def write_timeline(bundle: dict, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("use_claims", "conflicts"):
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in bundle[name]),
            encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(bundle["manifest"], indent=2, sort_keys=True), encoding="utf-8")
    return out


def materialize_demo_casts(root: str | Path, step_s: float = 0.5) -> dict:
    """Drive the existing tray reader over every tagged demo source.

    This is the only media-reading part of milestone B.  It writes new,
    reader-hash-keyed cache files and never replaces labels or old caches.
    """
    if step_s <= 0:
        raise ValueError("step must be positive")
    root = Path(root).resolve()
    # The reader still owns prototype-specific calibration.  Bind its existing
    # path parameters explicitly so a non-default test store cannot leak into
    # the user's store.
    from prototypes import ability_cast as cast
    from prototypes import ability_hud as hud

    cast.STORE = hud.STORE = root
    cast.LAB = root / "labels" / "ability"
    cast.CACHE = root / "casts"
    cast.CAND = root / "labels" / "ability_candidates"
    cast.EVENTS = root / "events" / "ability"
    manifests = []
    for path in sorted((root / "manifests").glob("*.json")):
        man = json.loads(path.read_text(encoding="utf-8"))
        if "ability-demo" in man.get("tags", []):
            manifests.append(man)
    result = []
    for man in manifests:
        sid = man["session_id"]
        before = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        rows, agent = cast.tray_casts(sid, step_s=step_s, use_cache=True)
        after = set((root / "casts").glob(f"{sid}.step{step_s}.*.json"))
        result.append({
            "session_id": sid, "agent": agent, "n_candidates": len(rows),
            "cache_paths": sorted(p.relative_to(root).as_posix() for p in after),
            "created": sorted(p.relative_to(root).as_posix() for p in after - before),
        })
    return {"sessions": result, "candidates": sum(r["n_candidates"] for r in result)}


def run(root: str | Path = DEFAULT_STORE, out: str | Path | None = None,
        *, materialize: bool = False, step_s: float = 0.5) -> tuple[dict, dict | None]:
    materialized = materialize_demo_casts(root, step_s) if materialize else None
    bundle = build_timeline(root)
    target = Path(out) if out else Path(root) / "analysis" / "ability-timeline"
    write_timeline(bundle, target)
    return bundle, materialized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--out")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args(argv)
    bundle, materialized = run(args.store, args.out, materialize=args.materialize,
                               step_s=args.step)
    if materialized:
        print(f"materialized {materialized['candidates']} candidates across "
              f"{len(materialized['sessions'])} demos")
    summary = bundle["manifest"]["summary"]
    print(f"{summary['use_claims']} use claims across {summary['sessions_with_claims']} sessions; "
          f"{summary['suspect_candidates']} suspect; {summary['conflicts']} conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
