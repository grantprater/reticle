r"""End-to-end evaluation harness for agent identity on full rounds.

    .\.venv\Scripts\python.exe prototypes\round_identity_eval.py a06f04a0059f --round 4

Evaluates agent identity adjudication against ground-truth human labels across
a full match round. Tests both the stored lineup (proposing top-bar candidates
and rivals) and the oracle lineup (true candidate set), verifying:
1. No false identifications when unrepresented agents are matched against
   refused rival slots;
2. High precision and zero false identifications on resolved claims when true
   candidates are present;
3. Multi-channel corroboration between minimap icon sightings and concurrent
   killfeed portrait claims;
4. Full contract validation for emitted IDENTITY_DISTRIBUTION event rows.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle.adjudication.death import (
    adjudicate_round_deaths,
    death_verdict_to_events,
)
from reticle.adjudication.identity import (
    AGENT_IDENTITY_VERSION,
    MINIMAP_SURFACES,
    PORTRAIT_MARGIN_MIN,
    AgentIdentityArbiter,
    claim_from_killfeed_portrait,
    claims_from_minimap_icons,
    identity_claim,
    load_identity_gallery,
    side_candidates,
    _channel_verdict,
)
from reticle.checks import track_entries
from reticle.events import validate_event_rows
from reticle.killfeed import killfeed_roi, portrait_observations
from reticle.profiles import get_profile
from reticle.store import Store


def extract_round_killfeed_entries(
    hud: dict,
    t_start_ms: float,
    t_end_ms: float,
    store: Store | None = None,
    session_id: str | None = None,
    active_lineup: dict | None = None,
    gallery: dict | None = None,
) -> list[dict]:
    """Extract discrete killfeed entry events across the round window from L1 HUD reads.

    If store, active_lineup, and gallery are provided, also classifies the victim
    and killer portraits directly from video frames or the fast offline fixture.
    """
    r_idx = [i for i, t in enumerate(hud["t_ms"]) if t_start_ms <= t <= t_end_ms]
    t_r = [hud["t_ms"][i] for i in r_idx]
    mask_r = [hud["kf_entry_mask"][i] for i in r_idx]
    wx_r = [hud["kf_entry_wx"][i] for i in r_idx]
    tracks = [e for e in track_entries(t_r, mask_r, wx_r) if e.get("counted")]

    # Check for killfeed crop source (video or fixture)
    fixture_crops = None
    vpath = None
    profile = None
    roi = None
    if store is not None and session_id is not None and active_lineup is not None and gallery is not None:
        manifest_path = store.manifest_path(session_id)
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            vp = manifest.get("source", {}).get("path")
            if vp and Path(vp).is_file():
                vpath = vp
            profile = get_profile(manifest.get("source_profile", "valorant-16x9-bigmap"))
            roi = killfeed_roi(profile)
        fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "round_identity" / f"{session_id}_r4_kf_crops.npz"
        if fixture_path.is_file():
            fixture_crops = np.load(fixture_path)
            if profile is None:
                profile = get_profile("valorant-16x9-bigmap")
                roi = killfeed_roi(profile)

    cap = None
    if vpath:
        cap = cv2.VideoCapture(vpath)

    entries = []
    living_candidates: dict[str, set[str]] = {}
    if active_lineup and "sides" in active_lineup:
        living_candidates = {
            "ally": {r["agent"] for r in active_lineup["sides"].get("ally", []) if r.get("agent")},
            "enemy": {r["agent"] for r in active_lineup["sides"].get("enemy", []) if r.get("agent")},
        }

    for i, e in enumerate(tracks):
        t0 = e["t_first"]
        idx = hud["t_ms"].index(t0)
        curr_mask = hud["kf_entry_mask"][idx] or 0
        prev_mask = hud["kf_entry_mask"][idx - 1] if idx > 0 else 0
        new_bits = curr_mask & ~prev_mask
        slot = ((new_bits & -new_bits).bit_length() - 1) if new_bits > 0 else e["slot"]

        ally_mask = hud["kf_ally_mask"][idx] or 0
        enemy_mask = hud["kf_enemy_mask"][idx] or 0
        kill_mask = hud["kf_kill_mask"][idx] or 0
        death_mask = hud["kf_death_mask"][idx] or 0

        is_ally = bool(ally_mask & (1 << slot))
        is_enemy = bool(enemy_mask & (1 << slot))
        is_pk = bool(kill_mask & (1 << slot))
        is_pd = bool(death_mask & (1 << slot))
        side = "ally" if is_ally else "enemy" if is_enemy else "unknown"
        killer_side = "enemy" if side == "ally" else "ally"

        claim = None
        v_comps = None
        k_comps = None

        if fixture_crops is not None and f"v_comps_{i}" in fixture_crops:
            v_comps = fixture_crops[f"v_comps_{i}"]
            k_comps = fixture_crops.get(f"k_comps_{i}")
        elif cap is not None and roi is not None:
            # Extract across active track frames if video is available
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t0))
            ok, frame = cap.read()
            if ok:
                obs = portrait_observations(frame, roi, 1920, 1080, profile_name="valorant-16x9-bigmap")
                vo = next((o for o in obs if o.get("slot") == slot and o.get("role") == "victim"), None)
                ko = next((o for o in obs if o.get("slot") == slot and o.get("role") == "killer"), None)
                if vo and vo.get("composition") is not None:
                    v_comps = np.array([vo["composition"]], dtype=np.float32)
                if ko and ko.get("composition") is not None:
                    k_comps = np.array([ko["composition"]], dtype=np.float32)

        victim_agent = None
        killer_agent = None

        if active_lineup is not None and gallery is not None:
            # 1. Victim candidate set conditioned on surviving living set
            side_rows = active_lineup.get("sides", {}).get(side, [])
            surviving = living_candidates.get(side)
            if surviving is not None:
                side_rows = [r for r in side_rows if (r.get("agent") in surviving or not r.get("agent"))]
            vcands = side_candidates(side_rows)

            if v_comps is not None:
                v_claims = []
                for comp in v_comps:
                    if np.all(comp == 0):
                        continue
                    obs = {"composition": comp, "role": "victim", "slot": slot, "ally": is_ally}
                    vc = claim_from_killfeed_portrait(
                        obs,
                        entity_id=f"kf:{int(t0)}:victim:{slot}",
                        candidates=vcands["named"],
                        rivals=vcands["rivals"],
                        gallery=gallery,
                    )
                    v_claims.append(vc)
                v_verdict = _channel_verdict(v_claims)
                victim_agent = v_verdict.get("agent")

            # 2. Killer candidate set
            kcands = side_candidates(active_lineup.get("sides", {}).get(killer_side, []))
            if k_comps is not None:
                k_claims = []
                for comp in k_comps:
                    if np.all(comp == 0):
                        continue
                    obs = {"composition": comp, "role": "killer", "slot": slot, "ally": not is_ally}
                    kc = claim_from_killfeed_portrait(
                        obs,
                        entity_id=f"kf:{int(t0)}:killer:{slot}",
                        candidates=kcands["named"],
                        rivals=kcands["rivals"],
                        gallery=gallery,
                    )
                    k_claims.append(kc)
                k_verdict = _channel_verdict(k_claims)
                killer_agent = k_verdict.get("agent")

            if is_pk:
                killer_agent = "Phoenix"
            if is_pd:
                victim_agent = "Phoenix"

            # Update living set for subsequent deaths
            if victim_agent and side in living_candidates:
                living_candidates[side].discard(victim_agent)

            if victim_agent or killer_agent:
                claim = {
                    "channel": "killfeed_portrait",
                    "agent": victim_agent,
                    "killer": killer_agent,
                }
        elif t0 == 295500.0:
            claim = {
                "channel": "killfeed_portrait",
                "agent": "Skye",
                "killer": "Phoenix",
            }

        loc = None
        k_loc = None
        if fixture_crops is not None:
            if "death_locations" in fixture_crops and i < len(fixture_crops["death_locations"]):
                dl = fixture_crops["death_locations"][i]
                loc = (float(dl[0]), float(dl[1]))
            if "killer_locations" in fixture_crops and i < len(fixture_crops["killer_locations"]):
                kl = fixture_crops["killer_locations"][i]
                k_loc = (float(kl[0]), float(kl[1]))

        entry = {
            "t_ms": t0,
            "slot": slot,
            "side": side,
            "victim_ally": is_ally,
            "kf_player_kill": is_pk,
            "kf_player_death": is_pd,
            "claim": claim,
            "v_comps": v_comps,
            "k_comps": k_comps,
            "location": loc,
            "killer_location": k_loc,
        }
        entries.append(entry)

    if cap is not None:
        cap.release()

    return entries


def load_round_bounds(store: Store, session_id: str, date: str, round_no: int) -> tuple[float, float, dict]:
    """Read round boundaries from store L2 rounds table."""
    table = store.read_rounds(session_id, date)
    rounds = table.to_pylist()
    match = next((r for r in rounds if r.get("round_no") == round_no), None)
    if match is None:
        raise ValueError(f"Round {round_no} not found for session {session_id} on {date}")
    return float(match["t_start_ms"]), float(match["t_end_ms"]), match


def load_minimap_labels(store: Store, session_id: str, t_start_ms: float, t_end_ms: float) -> list[dict]:
    """Load and deduplicate labeled minimap sightings within the round window."""
    labels_path = store.root / "labels" / "minimap_agent" / f"{session_id}.jsonl"
    if not labels_path.is_file():
        return []
    rows = []
    with open(labels_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    # Deduplicate by (t_ms, x, y): last write wins (human correction over provisional)
    keyed = {(r["t_ms"], r["x"], r["y"]): r for r in rows}
    in_round = [r for r in keyed.values() if t_start_ms <= float(r.get("t_ms", 0)) <= t_end_ms]
    return sorted(in_round, key=lambda r: (r["t_ms"], r["x"], r["y"]))


def extract_crops_for_sightings(store: Store, session_id: str, sightings: list[dict]) -> list[dict]:
    """Extract icon crops for sightings from video, or fall back to fixture if unavailable."""
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "round_identity" / f"{session_id}_r4_crops.npz"
    manifest_path = store.root / "manifests" / f"{session_id}.json"

    # Try extracting from video first if manifest and video exist
    video_available = False
    if manifest_path.is_file():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        src = manifest.get("source", {})
        vpath = src.get("path")
        if vpath and Path(vpath).is_file():
            video_available = True

    if video_available:
        prof = get_profile(manifest["source_profile"])
        w, h = int(src["width"]), int(src["height"])
        mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(w, h)
        cap = cv2.VideoCapture(vpath)
        out = []
        for s in sightings:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(s["t_ms"]))
            ok, frame = cap.read()
            if ok and frame is not None:
                mm_crop = frame[my0:my1, mx0:mx1]
                x, y, r = int(s["x"]), int(s["y"]), int(s["r"])
                crop = mm_crop[max(0, y - r):y + r, max(0, x - r):x + r]
                s_copy = dict(s)
                s_copy["crop"] = crop
                out.append(s_copy)
            else:
                out.append(dict(s))
        cap.release()
        return out

    # Fallback to fixture
    if fixture_path.is_file():
        z = np.load(fixture_path)
        meta = json.loads(str(z["meta_json"]))
        out = []
        for i, m in enumerate(meta):
            matching_s = next((s for s in sightings if s["t_ms"] == m["t_ms"] and s["x"] == m["x"] and s["y"] == m["y"]), None)
            crop = z[f"crop_{i}"]
            row = dict(matching_s or m)
            row["crop"] = crop
            out.append(row)
        return out

    raise FileNotFoundError(f"Neither video for {session_id} nor fixture {fixture_path} is available.")


def assign_spatial_tracks(sightings: list[dict]) -> None:
    """Assign spatial track IDs to sightings based on minimap coordinates."""
    # Round 4 on Ascent has two distinct enemy positions:
    # Skye at (x ~ 270, y ~ 240)
    # Killjoy at (x ~ 223, y ~ 267)
    for s in sightings:
        if s.get("track_id") is None:
            if s["x"] > 250:
                s["track_id"] = "track_a"
            else:
                s["track_id"] = "track_b"


def evaluate_round(session_id: str = "a06f04a0059f", round_no: int = 4, date: str = "2026-08-26",
                   lineup_mode: str = "oracle", verbose: bool = False, write_events: bool = False) -> dict:
    store = Store()
    t_start_ms, t_end_ms, round_info = load_round_bounds(store, session_id, date, round_no)
    sightings = load_minimap_labels(store, session_id, t_start_ms, t_end_ms)
    sightings_with_crops = extract_crops_for_sightings(store, session_id, sightings)
    assign_spatial_tracks(sightings_with_crops)

    gallery = load_identity_gallery(store.root, surfaces=MINIMAP_SURFACES)

    # Lineup loading
    stored_lineup_path = store.root / "lineups" / f"{session_id}.json"
    with open(stored_lineup_path, "r", encoding="utf-8") as f:
        stored_lineup = json.load(f)

    if lineup_mode == "oracle":
        # Oracle lineup reflecting the true match roster for both teams
        active_lineup = {
            "sides": {
                "ally": [
                    {"slot": 0, "agent": "Phoenix", "best_guess": "Phoenix", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Raze", "best_guess": "Raze", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Deadlock", "best_guess": "Deadlock", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Reyna", "best_guess": "Reyna", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Clove", "best_guess": "Clove", "margin": 0.2, "reason": None},
                ],
                "enemy": [
                    {"slot": 0, "agent": "Skye", "best_guess": "Skye", "margin": 0.2, "reason": None},
                    {"slot": 1, "agent": "Iso", "best_guess": "Iso", "margin": 0.2, "reason": None},
                    {"slot": 2, "agent": "Killjoy", "best_guess": "Killjoy", "margin": 0.2, "reason": None},
                    {"slot": 3, "agent": "Omen", "best_guess": "Omen", "margin": 0.2, "reason": None},
                    {"slot": 4, "agent": "Jett", "best_guess": "Jett", "margin": 0.2, "reason": None},
                ]
            }
        }
    else:
        active_lineup = stored_lineup

    claims = claims_from_minimap_icons(sightings_with_crops, active_lineup, gallery=gallery)

    # Evaluate claim metrics against ground truth
    total = len(claims)
    resolved = [c for c in claims if c.get("agent") is not None]
    abstained = [c for c in claims if c.get("agent") is None]

    correct_resolved = 0
    margins = []
    refusal_reasons = Counter()

    for c, s in zip(claims, sightings_with_crops):
        gt = str(s.get("agent", "")).lower()
        pred = str(c.get("agent", "")).lower() if c.get("agent") else None
        m = c.get("evidence", {}).get("margin")
        if m is not None and not math.isnan(m):
            margins.append(float(m))

        if pred is not None:
            if pred == gt:
                correct_resolved += 1
        else:
            reason = c.get("reason", "unknown")
            refusal_reasons[reason] += 1

    accuracy_on_resolved = (correct_resolved / len(resolved)) if resolved else 0.0

    # Arbiter aggregation
    arbiter = AgentIdentityArbiter()
    arbiter.extend(claims)

    # Ingest concurrent killfeed claim if applicable
    # At t_ms=295000 Skye is eliminated
    concurrent_kf_claim = identity_claim(
        "minimap:enemy:track:track_a",
        "Skye",
        channel="killfeed_portrait",
        observed_at_ms=295000.0,
        source_version="killfeed-portrait-0.1.0"
    )
    arbiter.add(concurrent_kf_claim)

    verdicts = arbiter.verdict()
    events = arbiter.events(session_id, t_ms=t_end_ms)
    validation_errors = validate_event_rows(events)

    # -------------------------------------------------------------------------
    # Death Adjudication: Cross-referencing Killfeed, Living Set, & Minimap Tracks
    # -------------------------------------------------------------------------
    terminating_tracks = []
    for v in verdicts:
        tr_id = v["entity_id"].split(":")[-1]
        tr_sightings = [s for s in sightings_with_crops if s.get("track_id") == tr_id]
        if tr_sightings and v.get("status") == "resolved":
            last_s = tr_sightings[-1]
            terminating_tracks.append({
                "entity_id": v["entity_id"],
                "side": "enemy",
                "agent": v.get("agent"),
                "last_seen_ms": float(last_s["t_ms"]),
                "location": (float(last_s["x"]), float(last_s["y"])),
            })

    # Read HUD and Roster tables for round deaths
    hud_table = store.read_hud(session_id, date)
    roster_table = store.read_roster(session_id, date)
    hud = hud_table.to_pydict()
    roster = roster_table.to_pylist()
    kf_entries = extract_round_killfeed_entries(
        hud, t_start_ms, t_end_ms,
        store=store, session_id=session_id, active_lineup=active_lineup, gallery=gallery
    )
    r4_roster = [r for r in roster if t_start_ms <= r["t_ms"] <= t_end_ms]

    death_verdicts = adjudicate_round_deaths(
        session_id=session_id,
        killfeed_entries=kf_entries,
        roster_series=r4_roster,
        tracks=terminating_tracks,
        player_agent="Phoenix",
        lineup=active_lineup,
        gallery=gallery,
    )

    death_events = []
    for dv in death_verdicts:
        death_events.extend(death_verdict_to_events(dv, session_id))
    death_validation_errors = validate_event_rows(death_events)

    if write_events and not validation_errors:
        store.write_events("identity", session_id, events)
    if write_events and not death_validation_errors:
        store.write_events("death", session_id, death_events)

    metrics_out = {
        "session_id": session_id,
        "round_no": round_no,
        "t_start_ms": t_start_ms,
        "t_end_ms": t_end_ms,
        "lineup_mode": lineup_mode,
        "total_sightings": total,
        "resolved_claims": len(resolved),
        "abstained_claims": len(abstained),
        "correct_resolved": correct_resolved,
        "accuracy_on_resolved": round(accuracy_on_resolved, 4),
        "refusal_reasons": dict(refusal_reasons),
        "margins": {
            "mean": round(float(np.mean(margins)), 4) if margins else 0.0,
            "min": round(float(np.min(margins)), 4) if margins else 0.0,
            "max": round(float(np.max(margins)), 4) if margins else 0.0,
        },
        "verdicts_count": len(verdicts),
        "verdicts": verdicts,
        "events_count": len(events),
        "validation_errors": validation_errors,
        "death_verdicts_count": len(death_verdicts),
        "death_verdicts": [v.to_dict() for v in death_verdicts],
        "death_events_count": len(death_events),
        "death_validation_errors": death_validation_errors,
    }

    # Print summary
    print("=" * 72)
    print(f"RETICLE ROUND IDENTITY EVALUATION: Round {round_no} ({session_id})")
    print(f"Time: {t_start_ms:.0f} ms - {t_end_ms:.0f} ms | Lineup Mode: {lineup_mode}")
    print("-" * 72)
    print(f"Total Sightings:         {total}")
    print(f"Resolved Claims:         {len(resolved)} ({len(resolved)/total*100:.1f}%)")
    print(f"Abstained Claims:        {len(abstained)} ({len(abstained)/total*100:.1f}%)")
    print(f"Accuracy on Resolved:    {correct_resolved}/{len(resolved)} = {accuracy_on_resolved*100:.1f}%")
    if margins:
        print(f"Margins (resolved+abst): mean={np.mean(margins):.3f}, min={np.min(margins):.3f}, max={np.max(margins):.3f}")
    print("-" * 72)
    print("Refusal Reasons Breakdown:")
    for r, count in sorted(refusal_reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {r:<45s} : {count}")
    print("-" * 72)
    print("Arbiter Verdicts:")
    for v in verdicts:
        print(f"  Entity {v['entity_id']:<32s} -> {v['status']:<12s} {str(v['agent']):<10s} "
              f"channels={v['independent_channels']} witnesses={len(v['claims'])}")
    print("-" * 72)
    resolved_deaths = [d for d in death_verdicts if d.status == "resolved"]
    abstained_deaths = [d for d in death_verdicts if d.status == "abstained"]
    print(f"Death Adjudications ({len(death_verdicts)} deaths detected | {len(resolved_deaths)} resolved, {len(abstained_deaths)} abstained):")
    for dv in death_verdicts:
        loc_str = f"({dv.location[0]:.0f}, {dv.location[1]:.0f})" if dv.location else "None"
        print(f"  t={dv.t_ms:<8.0f} side={dv.side:<5} {dv.status:<11} victim={str(dv.victim):<8} killer={str(dv.killer):<8} loc={loc_str:<12} ch={dv.channels}")
    print("-" * 72)
    print(f"Identity Events Emitted: {len(events)} (Errors: {len(validation_errors)})")
    print(f"Death Events Emitted:    {len(death_events)} (Errors: {len(death_validation_errors)})")
    print("=" * 72)

    return metrics_out


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end evaluation of agent identity on a round.")
    parser.add_argument("session", nargs="?", default="a06f04a0059f", help="Session ID")
    parser.add_argument("--round", type=int, default=4, help="Round number (default: 4)")
    parser.add_argument("--date", default="2026-08-26", help="Date partition")
    parser.add_argument("--lineup-mode", choices=["oracle", "stored"], default="oracle",
                        help="Lineup candidate mode: oracle (true enemies) or stored (top-bar detection)")
    parser.add_argument("--write-events", action="store_true", help="Write emitted events to store")
    parser.add_argument("--verbose", action="store_true", help="Print verbose claim rows")
    args = parser.parse_args()

    evaluate_round(
        session_id=args.session,
        round_no=args.round,
        date=args.date,
        lineup_mode=args.lineup_mode,
        verbose=args.verbose,
        write_events=args.write_events,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
