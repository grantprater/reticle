"""Independent evaluation engine and cross-channel event auditor for Lane A.

Implements 1-to-1 event alignment with temporal tolerances, property scoring,
duplicate-plus-miss cancellation detection, and witness ablation.

References:
- docs/BOOTSTRAP_PARALLEL_RUN.md
- docs/EXPERIMENT_PROGRAM.md (E1, E8)
- reticle.adjudication.death
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import sys
from pathlib import Path
from typing import Any, Optional

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from reticle.adjudication.death import adjudicate_death, MAX_DEATH_ALIGNMENT_DT_MS

EVAL_SPEC_VERSION = "reticle-eval-0.1.0"


@dataclass
class DeathEvent:
    death_id: str
    session_id: str
    round_no: int
    t_ms: float
    side: str
    victim: Optional[str] = None
    killer: Optional[str] = None
    death_cause: str = "gun"
    weapon: Optional[str] = None
    is_second_life: bool = False
    status: str = "resolved"
    refusal_reason: Optional[str] = None
    witnesses: list[dict] = field(default_factory=list)

    @classmethod
    def from_store_row(cls, row: dict) -> "DeathEvent":
        return cls(
            death_id=row.get("death_id", ""),
            session_id=row.get("session_id", ""),
            round_no=int(row.get("round_no", 0)),
            t_ms=float(row.get("t_ms", 0.0)),
            side=row.get("side", "unknown"),
            victim=row.get("victim"),
            killer=row.get("killer"),
            death_cause=row.get("death_cause", "gun"),
            weapon=row.get("weapon"),
            is_second_life=bool(row.get("is_second_life", False)),
            status=row.get("status", "resolved"),
            refusal_reason=row.get("reason"),
            witnesses=row.get("witnesses", []),
        )


@dataclass
class EvaluationSpec:
    spec_version: str = EVAL_SPEC_VERSION
    dt_max_ms: float = MAX_DEATH_ALIGNMENT_DT_MS
    match_keys: tuple[str, ...] = ("session_id", "round_no", "side")
    scored_properties: tuple[str, ...] = ("victim", "killer", "death_cause", "is_second_life")
    match_strategy: str = "greedy_min_dt"


@dataclass
class MatchPair:
    reference: DeathEvent
    candidate: DeathEvent
    dt_ms: float
    property_matches: dict[str, Optional[bool]]
    is_whole_event_correct: bool


@dataclass
class EvaluationReport:
    spec_version: str
    n_reference: int
    n_candidate: int
    n_matched: int
    n_missed: int  # False Negatives
    n_extra: int   # False Positives
    precision: float
    recall: float
    f1: float
    count_match: bool
    duplicate_miss_cancellation: bool
    property_metrics: dict[str, dict[str, Any]]
    whole_event_correct: int
    whole_event_accuracy: float
    matched_pairs: list[MatchPair] = field(default_factory=list)
    missed_events: list[DeathEvent] = field(default_factory=list)
    extra_events: list[DeathEvent] = field(default_factory=list)


def align_events(
    ref_events: list[DeathEvent],
    cand_events: list[DeathEvent],
    spec: Optional[EvaluationSpec] = None,
) -> EvaluationReport:
    """Align reference and candidate events 1-to-1 within temporal tolerance.

    Enforces that matching total counts do not masquerade as event correspondence.
    Detects duplicate-plus-miss cancellation where count_match is True but
    individual events diverge.
    """
    spec = spec or EvaluationSpec()

    # Partition by match_keys
    def partition_key(e: DeathEvent) -> tuple:
        return tuple(getattr(e, k) for k in spec.match_keys)

    ref_groups: dict[tuple, list[DeathEvent]] = {}
    for r in ref_events:
        ref_groups.setdefault(partition_key(r), []).append(r)

    cand_groups: dict[tuple, list[DeathEvent]] = {}
    for c in cand_events:
        cand_groups.setdefault(partition_key(c), []).append(c)

    all_keys = set(ref_groups.keys()) | set(cand_groups.keys())

    matched_pairs: list[MatchPair] = []
    missed_events: list[DeathEvent] = []
    extra_events: list[DeathEvent] = []

    for k in sorted(all_keys):
        refs = ref_groups.get(k, [])
        cands = list(cand_groups.get(k, []))

        # Build candidate pairs within dt_max_ms
        possible_pairs = []
        for r_idx, r in enumerate(refs):
            for c_idx, c in enumerate(cands):
                dt = abs(r.t_ms - c.t_ms)
                if dt <= spec.dt_max_ms:
                    possible_pairs.append((dt, r_idx, c_idx))

        # Greedily pair with minimum dt
        possible_pairs.sort(key=lambda x: x[0])
        used_r = set()
        used_c = set()

        for dt, r_idx, c_idx in possible_pairs:
            if r_idx in used_r or c_idx in used_c:
                continue
            used_r.add(r_idx)
            used_c.add(c_idx)

            r = refs[r_idx]
            c = cands[c_idx]

            # Property matches
            prop_matches: dict[str, Optional[bool]] = {}
            whole_correct = True

            for p in spec.scored_properties:
                r_val = getattr(r, p)
                c_val = getattr(c, p)

                if r_val is None:
                    # Unspecified in ground truth -> None
                    prop_matches[p] = None
                elif c_val is None:
                    # Candidate abstained
                    prop_matches[p] = False
                    whole_correct = False
                elif str(r_val).lower() == str(c_val).lower():
                    prop_matches[p] = True
                else:
                    prop_matches[p] = False
                    whole_correct = False

            matched_pairs.append(
                MatchPair(
                    reference=r,
                    candidate=c,
                    dt_ms=dt,
                    property_matches=prop_matches,
                    is_whole_event_correct=whole_correct,
                )
            )

        for r_idx, r in enumerate(refs):
            if r_idx not in used_r:
                missed_events.append(r)

        for c_idx, c in enumerate(cands):
            if c_idx not in used_c:
                extra_events.append(c)

    n_ref = len(ref_events)
    n_cand = len(cand_events)
    n_matched = len(matched_pairs)
    n_missed = len(missed_events)
    n_extra = len(extra_events)

    precision = n_matched / (n_matched + n_extra) if (n_matched + n_extra) > 0 else 0.0
    recall = n_matched / (n_matched + n_missed) if (n_matched + n_missed) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    count_match = (n_ref == n_cand)
    duplicate_miss_cancellation = count_match and (n_missed > 0 or n_extra > 0)

    # Compute property metrics over matched pairs
    property_metrics: dict[str, dict[str, Any]] = {}
    for p in spec.scored_properties:
        n_evaluable = sum(1 for m in matched_pairs if getattr(m.reference, p) is not None)
        n_correct = sum(1 for m in matched_pairs if m.property_matches.get(p) is True)
        n_cand_null = sum(
            1 for m in matched_pairs
            if getattr(m.reference, p) is not None and getattr(m.candidate, p) is None
        )
        n_conflict = sum(
            1 for m in matched_pairs
            if getattr(m.reference, p) is not None
            and getattr(m.candidate, p) is not None
            and m.property_matches.get(p) is False
        )
        acc = n_correct / n_evaluable if n_evaluable > 0 else 0.0

        property_metrics[p] = {
            "n_evaluable": n_evaluable,
            "n_correct": n_correct,
            "n_cand_null": n_cand_null,
            "n_conflict": n_conflict,
            "accuracy": acc,
        }

    whole_correct_count = sum(1 for m in matched_pairs if m.is_whole_event_correct)
    whole_accuracy = whole_correct_count / n_ref if n_ref > 0 else 0.0

    return EvaluationReport(
        spec_version=spec.spec_version,
        n_reference=n_ref,
        n_candidate=n_cand,
        n_matched=n_matched,
        n_missed=n_missed,
        n_extra=n_extra,
        precision=precision,
        recall=recall,
        f1=f1,
        count_match=count_match,
        duplicate_miss_cancellation=duplicate_miss_cancellation,
        property_metrics=property_metrics,
        whole_event_correct=whole_correct_count,
        whole_event_accuracy=whole_accuracy,
        matched_pairs=matched_pairs,
        missed_events=missed_events,
        extra_events=extra_events,
    )


def ablate_death_events(
    stored_rows: list[dict],
    withhold_channel: Optional[str] = None,
) -> list[DeathEvent]:
    """Re-adjudicate stored deaths through adjudicate_death with an ablated witness."""
    ablated_events = []
    for r in stored_rows:
        witnesses = r.get("witnesses", [])
        kf_claim = next((w for w in witnesses if w.get("channel") == "killfeed_portrait"), None)
        sb_claim = next((w for w in witnesses if w.get("channel") == "scoreboard_dim"), None)
        roster_shrink = next((w for w in witnesses if w.get("channel") == "roster_diff"), None)

        if withhold_channel == "scoreboard":
            sb_claim = None
        elif withhold_channel == "killfeed":
            kf_claim = None
        elif withhold_channel == "roster":
            roster_shrink = None

        verdict = adjudicate_death(
            death_id=r.get("death_id", ""),
            t_ms=float(r.get("t_ms", 0.0)),
            side=r.get("side", "unknown"),
            killfeed_claim=kf_claim,
            scoreboard_claim=sb_claim,
            roster_shrink=roster_shrink,
            death_cause=r.get("death_cause", "gun"),
            weapon=r.get("weapon"),
            is_second_life=bool(r.get("is_second_life", False)),
        )

        ablated_events.append(
            DeathEvent(
                death_id=verdict.death_id,
                session_id=r.get("session_id", ""),
                round_no=int(r.get("round_no", 0)),
                t_ms=verdict.t_ms,
                side=verdict.side,
                victim=verdict.victim,
                killer=verdict.killer,
                death_cause=verdict.death_cause,
                weapon=verdict.weapon,
                is_second_life=verdict.is_second_life,
                status=verdict.status,
                refusal_reason=verdict.reason,
                witnesses=verdict.witnesses,
            )
        )
    return ablated_events


def audit_development_slice(
    store_root: Path,
    session_id: str = "a06f04a0059f",
    rounds: tuple[int, ...] = (3, 4, 5, 6),
) -> dict[str, Any]:
    """Audit the development slice against killfeed, scoreboard, and combat report."""
    death_file = store_root / "events" / "death" / f"{session_id}.jsonl"
    cr_file = store_root / "events" / "combat_report_round" / f"{session_id}.jsonl"

    all_deaths = [json.loads(l) for l in death_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    all_cr = [json.loads(l) for l in cr_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    # Filter slice
    slice_deaths = [d for d in all_deaths if d.get("round_no") in rounds]
    slice_cr = [c for c in all_cr if c.get("round_no") in rounds]

    baseline_events = [DeathEvent.from_store_row(d) for d in slice_deaths]
    no_sb_events = ablate_death_events(slice_deaths, withhold_channel="scoreboard")
    no_kf_events = ablate_death_events(slice_deaths, withhold_channel="killfeed")

    # Evaluate ablations against baseline
    eval_no_sb = align_events(baseline_events, no_sb_events)
    eval_no_kf = align_events(baseline_events, no_kf_events)

    # Detailed event categorization
    events_agreed = []
    events_kf_rescue_sb = []
    events_sb_rescue_kf = []
    events_abstained = []

    for d in baseline_events:
        kf_w = next((w for w in d.witnesses if w.get("channel") == "killfeed_portrait"), None)
        sb_w = next((w for w in d.witnesses if w.get("channel") == "scoreboard_dim"), None)

        kf_agent = kf_w.get("agent") if kf_w else None
        sb_agent = sb_w.get("agent") if sb_w else None

        kf_reason = kf_w.get("reason") if kf_w else "missing"
        sb_reason = sb_w.get("reason") if sb_w else "missing"

        event_info = {
            "death_id": d.death_id,
            "round_no": d.round_no,
            "t_ms": d.t_ms,
            "side": d.side,
            "victim": d.victim,
            "killer": d.killer,
            "status": d.status,
            "kf_agent": kf_agent,
            "kf_reason": kf_reason,
            "sb_agent": sb_agent,
            "sb_reason": sb_reason,
        }

        if kf_agent and sb_agent and kf_agent == sb_agent:
            events_agreed.append(event_info)
        elif kf_agent and not sb_agent:
            events_kf_rescue_sb.append(event_info)
        elif sb_agent and not kf_agent:
            events_sb_rescue_kf.append(event_info)
        elif not kf_agent and not sb_agent:
            events_abstained.append(event_info)

    # Combat report corroboration on player deaths
    player_deaths_audit = []
    for r_no in rounds:
        cr_rounds = [c for c in slice_cr if c.get("round_no") == r_no]
        cr_p_deaths = sum(1 for c in cr_rounds if c.get("kind") == "death" and c.get("at_death"))
        kf_p_deaths = [d for d in baseline_events if d.round_no == r_no and d.victim == "Phoenix"]
        second_life_deaths = [d for d in baseline_events if d.round_no == r_no and d.is_second_life]

        player_deaths_audit.append({
            "round_no": r_no,
            "cr_player_deaths": cr_p_deaths,
            "kf_player_deaths": len(kf_p_deaths),
            "second_life_deaths": len(second_life_deaths),
            "kf_details": [{"t_ms": d.t_ms, "killer": d.killer, "second_life": d.is_second_life} for d in kf_p_deaths],
        })

    return {
        "session_id": session_id,
        "rounds": list(rounds),
        "total_deaths": len(baseline_events),
        "agreed_count": len(events_agreed),
        "kf_rescues_sb_count": len(events_kf_rescue_sb),
        "sb_rescues_kf_count": len(events_sb_rescue_kf),
        "abstained_count": len(events_abstained),
        "events_agreed": events_agreed,
        "events_kf_rescue_sb": events_kf_rescue_sb,
        "events_sb_rescue_kf": events_sb_rescue_kf,
        "events_abstained": events_abstained,
        "ablation_no_scoreboard": {
            "victim_accuracy": eval_no_sb.property_metrics["victim"]["accuracy"],
            "lost_victims": eval_no_sb.property_metrics["victim"]["n_cand_null"],
            "report": asdict(eval_no_sb),
        },
        "ablation_no_killfeed": {
            "victim_accuracy": eval_no_kf.property_metrics["victim"]["accuracy"],
            "lost_victims": eval_no_kf.property_metrics["victim"]["n_cand_null"],
            "report": asdict(eval_no_kf),
        },
        "player_deaths_combat_report_corroboration": player_deaths_audit,
    }


def generate_markdown_audit_report(audit_data: dict[str, Any]) -> str:
    """Generate Markdown audit report from audit data."""
    md = []
    md.append(f"# E1 Event Correspondence Audit: {audit_data['session_id']} Rounds {audit_data['rounds']}")
    md.append("")
    md.append("## Executive Summary")
    md.append("")
    md.append(f"- **Total death opportunities audited**: {audit_data['total_deaths']}")
    md.append(f"- **Fully agreed deaths (Killfeed + Scoreboard)**: {audit_data['agreed_count']} ({audit_data['agreed_count'] / audit_data['total_deaths']:.1%})")
    md.append(f"- **Single-channel rescues**: {audit_data['kf_rescues_sb_count'] + audit_data['sb_rescues_kf_count']} ({ (audit_data['kf_rescues_sb_count'] + audit_data['sb_rescues_kf_count']) / audit_data['total_deaths']:.1%})")
    md.append(f"  - Killfeed rescues Scoreboard refusal: {audit_data['kf_rescues_sb_count']}")
    md.append(f"  - Scoreboard rescues Killfeed refusal: {audit_data['sb_rescues_kf_count']}")
    md.append(f"- **Explicit abstentions (both channels refused)**: {audit_data['abstained_count']} ({audit_data['abstained_count'] / audit_data['total_deaths']:.1%})")
    md.append("")

    md.append("## 1. Cross-Channel Ablation Findings")
    md.append("")
    no_sb = audit_data["ablation_no_scoreboard"]
    no_kf = audit_data["ablation_no_killfeed"]
    md.append("| Withheld Channel | Resolved Victim Accuracy | Lost Victims (Became Abstained) | Remaining Matches |")
    md.append("|---|---|---|---|")
    md.append(f"| Scoreboard (`scoreboard_dim`) | {no_sb['victim_accuracy']:.1%} | {no_sb['lost_victims']} | {no_sb['report']['n_matched']} / {audit_data['total_deaths']} |")
    md.append(f"| Killfeed (`killfeed_portrait`) | {no_kf['victim_accuracy']:.1%} | {no_kf['lost_victims']} | {no_kf['report']['n_matched']} / {audit_data['total_deaths']} |")
    md.append("")
    md.append("### Scoreboard Rescue Details (Deaths lost when scoreboard is withheld)")
    for e in audit_data["events_sb_rescue_kf"]:
        md.append(f"- **Round {e['round_no']} at {e['t_ms']/1000.0:.1f}s**: Victim **{e['victim']}** (side: {e['side']}). Scoreboard resolved {e['sb_agent']}; Killfeed refused: `{e['kf_reason']}`.")
    md.append("")

    md.append("## 2. Refusal and Abstention Diagnosis")
    md.append("")
    md.append("When both channels refuse, Reticle explicitly preserves `status = 'abstained'` with concrete reasons rather than guessing:")
    md.append("")
    for e in audit_data["events_abstained"]:
        md.append(f"- **Round {e['round_no']} at {e['t_ms']/1000.0:.1f}s** (side: {e['side']}):")
        md.append(f"  - Killfeed refusal: `{e['kf_reason']}`")
        md.append(f"  - Scoreboard refusal: `{e['sb_reason']}`")
    md.append("")

    md.append("## 3. Combat Report Corroboration on Player Deaths")
    md.append("")
    md.append("| Round | Combat Report Player Deaths | Killfeed Player Deaths | Second Life Deaths | Corroboration Verdict |")
    md.append("|---|---|---|---|---|")
    for r in audit_data["player_deaths_combat_report_corroboration"]:
        details = ", ".join(f"{d['killer']} ({'second-life' if d['second_life'] else 'death'})" for d in r["kf_details"])
        corr = "Exact agreement" if r["cr_player_deaths"] == r["kf_player_deaths"] else "Discrepancy"
        md.append(f"| Round {r['round_no']} | {r['cr_player_deaths']} | {r['kf_player_deaths']} | {r['second_life_deaths']} | {corr} ({details or 'Survived'}) |")
    md.append("")
    md.append("## Conclusion")
    md.append("Total round counts alone conceal intermediate single-channel rescues and abstentions. Exact 1-to-1 event alignment with temporal tolerances exposes these dependencies.")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap Lane A Evaluator and Auditor")
    parser.add_argument("--audit", action="store_true", help="Run audit on development slice")
    parser.add_argument("--store", default="C:/Users/grant/reticle-store", help="Path to reticle store")
    parser.add_argument("--session", default="a06f04a0059f", help="Session ID")
    parser.add_argument("--slice", default="a06f04a0059f:3-6", help="Slice specification session:start-end")
    parser.add_argument("--output", help="Output markdown or json file")
    parser.add_argument("--validate-spec", help="Validate evaluation spec file")
    args = parser.parse_args()

    if args.validate_spec:
        spec_path = Path(args.validate_spec)
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        assert "spec_version" in data, "Missing spec_version"
        assert "dt_max_ms" in data or "dt_max_ms" in data.get("matching_criteria", {}), "Missing dt_max_ms"
        assert "property_denominators" in data, "Missing property_denominators"
        assert "observability_criteria" in data, "Missing observability_criteria"
        print(f"Validation successful: {spec_path} conforms to {data.get('spec_version')}")
        return

    if args.audit:
        store_path = Path(args.store)
        rounds = (3, 4, 5, 6)
        if ":" in args.slice:
            parts = args.slice.split(":")
            args.session = parts[0]
            if "-" in parts[1]:
                r_start, r_end = parts[1].split("-")
                rounds = tuple(range(int(r_start), int(r_end) + 1))

        audit_data = audit_development_slice(store_path, session_id=args.session, rounds=rounds)
        report_md = generate_markdown_audit_report(audit_data)

        if args.output:
            out_p = Path(args.output)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(report_md, encoding="utf-8")
            print(f"Audit report written to {out_p}")
        else:
            print(report_md)


if __name__ == "__main__":
    main()
