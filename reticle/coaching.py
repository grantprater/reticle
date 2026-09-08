"""Exploratory, offline coaching from stored observations; never decodes video.

Events are killfeed observations, not verified scoreboard deaths. Model states
are restricted to observed ticking-clock play with both teams still alive.
There is deliberately no inferred plant, POV, economy, side or causal credit.
All tuning constants are fixed here; session holdouts are not a tuning set.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from .checks import track_entries
from .rounds import build_rounds
from .roster import resolve as roster_resolve
from .review import REVIEW_VERSION, select_review_windows, render_review
from .version import (COACH_VERSION, HUD_VERSION, ROSTER_VERSION,
                      ROSTER_SPLIT_VERSION, ROUND_VERSION)

MAX_STATE_GAP_MS = 1500
EVENT_WINDOW_MS = 3000
LANDMARK_MS = 10000
MIN_TRAIN_ROUNDS = 30
MIN_TRAIN_SESSIONS = 2
RIDGE = 1.0


def _coach_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _coach_columns(table):
    if table is None:
        return {}
    data = table.to_pydict()
    t = np.asarray(data["t_ms"], dtype=float)
    if not np.all(np.isfinite(t)) or np.any(np.diff(t) <= 0):
        raise ValueError("timestamps must be finite and strictly increasing")
    return data


def observed_states(hud, roster, rounds, session_id):
    """Causal as-of join; never fills a missing read or borrows a future row.

    Clock continuity rejects frozen menus/buy clocks. A >60s clock observed
    within this round must first establish play. The first partial interval
    and the final 5 seconds before a delayed score boundary are excluded.
    This conservative gate is not a replacement for a validated phase reader.
    """
    h, v = _coach_columns(hud), _coach_columns(roster)
    if not v:
        return [], {"missing_roster": len(h["t_ms"])}
    # Same adjudication the audit uses. Terminal states are excluded below
    # either way, so this changes coverage rather than any eligible state --
    # but the two must not disagree about what the roster said.
    v = dict(v)
    v["alive_ally"], v["alive_enemy"] = roster_resolve(hud, roster)
    result, rejected = [], Counter(round_boundary_or_unresolved=len(h["t_ms"]))
    rt = v["t_ms"]
    for r in rounds[1:]:
        a, z = r["t_start_ms"], r["t_end_ms"]
        lo, hi = bisect_left(h["t_ms"], a), bisect_left(h["t_ms"], z - 5000)
        live_seen = False
        for i in range(lo, hi):
            rejected["round_boundary_or_unresolved"] -= 1
            t, clock = h["t_ms"][i], h["clock_ms"][i]
            if clock is not None and 60000 < clock <= 100000:
                live_seen = True
            prev_clock = h["clock_ms"][i - 1] if i > lo else None
            dt = t - h["t_ms"][i - 1] if i > lo else 0
            if (not live_seen or clock is None or not 5000 <= clock <= 95000
                    or prev_clock is None or not 0 < dt <= MAX_STATE_GAP_MS
                    or not 0 < prev_clock - clock <= dt + 1100):
                rejected["clock_or_phase_unknown"] += 1
                continue
            j = bisect_right(rt, t) - 1
            if j < 1 or rt[j - 1] < a or t - rt[j - 1] > MAX_STATE_GAP_MS:
                rejected["roster_missing_or_old"] += 1
                continue
            ally, enemy = v["alive_ally"][j], v["alive_enemy"][j]
            if (ally is None or enemy is None or not 1 <= ally <= 5
                    or not 1 <= enemy <= 5):
                rejected["roster_unknown_or_terminal"] += 1
                continue
            if (ally, enemy) != (v["alive_ally"][j - 1], v["alive_enemy"][j - 1]):
                rejected["roster_unconfirmed"] += 1
                continue
            result.append(dict(session_id=session_id, round_no=r["round_no"],
                               t_ms=t, alive_ally=ally, alive_enemy=enemy,
                               clock_ms=clock, won=r["won"]))
    return result, dict(rejected)


def player_observations(hud, rounds, manifest):
    """Deduplicated killfeed tracks with stable source keys and review bounds."""
    h = _coach_columns(hud)
    sid = manifest["session_id"]
    starts = [r["t_start_ms"] for r in rounds]
    events = []
    for kind in ("kill", "death"):
        tracks = track_entries(h["t_ms"], h[f"kf_{kind}_mask"],
                               h.get(f"kf_{kind}_wx"))
        for ordinal, tr in enumerate(tracks):
            if not tr["counted"]:
                continue
            t = tr["t_first"]
            j = bisect_right(starts, t) - 1
            r = rounds[j] if j >= 0 and t < rounds[j]["t_end_ms"] else None
            flags = ["killfeed_observation", "timing_not_refined"]
            if r is None:
                flags.append("round_unresolved")
            elif j == 0 or min(t - r["t_start_ms"], r["t_end_ms"] - t) < 5000:
                flags.append("round_boundary_uncertain")
            duration = manifest["source"].get("duration_ms")
            end = tr["t_first"] + 6000
            if duration is not None:
                end = min(end, duration)
            key = f"{sid}:{kind}:{t:.3f}:{ordinal}"
            events.append(dict(event_id=hashlib.sha256(key.encode()).hexdigest()[:20],
                               session_id=sid, kind=f"player_{kind}",
                               t_ms=t, last_seen_ms=tr["t_last"],
                               n_observations=tr["n_obs"],
                               round_no=r["round_no"] if r else None,
                               won=r["won"] if r else None,
                               quality_flags=flags, coach_version=COACH_VERSION,
                               source_path=manifest["source"].get("path"),
                               clip_start_ms=max(0, t - 8000), clip_end_ms=end))
    return sorted(events, key=lambda e: (e["t_ms"], e["kind"], e["event_id"]))


def _coach_landmarks(states):
    # One sample per clock bucket per round, independent of event occurrence.
    seen, out = set(), []
    for s in states:
        key = (s["session_id"], s["round_no"], int(s["clock_ms"] // LANDMARK_MS))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _coach_features(states):
    return np.asarray([[1, (s["alive_ally"] - 3) / 2,
                        (s["alive_enemy"] - 3) / 2,
                        (s["clock_ms"] / 1000 - 50) / 50] for s in states], dtype=float)


def _coach_weights(states):
    counts = Counter((s["session_id"], s["round_no"]) for s in states)
    return np.asarray([1 / counts[s["session_id"], s["round_no"]] for s in states])


def _coach_sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -35, 35)))


def fit_state_baseline(states):
    """Round-weighted ridge logistic regression with a weak intercept penalty."""
    x = _coach_features(states)
    y = np.asarray([s["won"] for s in states], dtype=float)
    w = _coach_weights(states)
    penalty = np.diag([0.01, RIDGE, RIDGE, RIDGE])
    beta = np.zeros(x.shape[1])
    for _ in range(100):
        p = _coach_sigmoid(x @ beta)
        gradient = x.T @ (w * (p - y)) + penalty @ beta
        hessian = x.T @ ((w * p * (1 - p))[:, None] * x) + penalty
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            return beta
    raise ValueError("probability fit did not converge")


def evaluate_states(states):
    """Each prediction is fitted without any observation from its session."""
    landmarks = _coach_landmarks(states)
    sessions = sorted({s["session_id"] for s in landmarks})
    predictions, models, folds = [], {}, []
    for sid in sessions:
        train = [s for s in landmarks if s["session_id"] != sid]
        test = [s for s in landmarks if s["session_id"] == sid]
        units = {(s["session_id"], s["round_no"]): s["won"] for s in train}
        training_sessions = sorted({s["session_id"] for s in train})
        fold = dict(held_out=sid, training_sessions=training_sessions,
                    training_rounds=len(units))
        if (len(training_sessions) < MIN_TRAIN_SESSIONS or len(units) < MIN_TRAIN_ROUNDS
                or len(set(units.values())) < 2):
            fold["status"] = "insufficient_training_data"
            folds.append(fold)
            continue
        beta = fit_state_baseline(train)
        models[sid] = beta
        base = (sum(units.values()) + 1) / (len(units) + 2)
        ps = _coach_sigmoid(_coach_features(test) @ beta)
        predictions.extend(dict(s, probability=float(p), baseline=base)
                           for s, p in zip(test, ps))
        fold.update(status="evaluated", coefficients=beta.tolist(), baseline=base)
        folds.append(fold)
    report = dict(status="insufficient_data", n_sessions=len(sessions),
                  brier_difference_cluster_interval=None,
                  n_rounds=len({(s["session_id"], s["round_no"]) for s in landmarks}),
                  n_landmarks=len(landmarks), folds=folds, calibration=[])
    if predictions:
        w = _coach_weights(predictions)
        y = np.asarray([s["won"] for s in predictions], dtype=float)
        p = np.asarray([s["probability"] for s in predictions])
        b = np.asarray([s["baseline"] for s in predictions])
        avg = lambda v: float(np.average(v, weights=w))
        report.update(status="exploratory", evaluated_landmarks=len(predictions),
                      brier=avg((p - y) ** 2), baseline_brier=avg((b - y) ** 2),
                      log_loss=avg(-y * np.log(p) - (1-y) * np.log1p(-p)))
        for low in np.arange(0, 1, 0.2):
            mask = (p >= low) & (p < low + 0.2)
            if mask.any():
                report["calibration"].append(dict(lower=float(low),
                    landmarks=int(mask.sum()), round_weight=float(w[mask].sum()),
                    predicted=float(np.average(p[mask], weights=w[mask])),
                    observed=float(np.average(y[mask], weights=w[mask]))))
        # Descriptive session-cluster bootstrap over held-out prediction losses.
        # Does not account for training-set overlap; do not call this a model CI.
        grouped = []
        for sid in sorted(models):
            mask = np.asarray([s["session_id"] == sid for s in predictions])
            grouped.append((float(np.sum(w[mask] * ((p[mask]-y[mask])**2
                            - (b[mask]-y[mask])**2))), float(w[mask].sum())))
        if len(grouped) >= 5:
            g = np.asarray(grouped)
            draws = np.random.default_rng(0).integers(0, len(g), (2000, len(g)))
            totals = g[draws].sum(axis=1)
            report["brier_difference_cluster_interval"] = np.quantile(
                totals[:, 0] / totals[:, 1], [0.025, 0.975]).tolist()
    return report, models, predictions


def attach_event_estimates(events, states, models):
    grouped = {}
    for s in states:
        grouped.setdefault((s["session_id"], s["round_no"]), []).append(s)
    for e in events:
        e.update(probability_before=None, probability_after=None,
                 state_delta=None, estimate_reason="no_held_out_model")
        if "round_boundary_uncertain" in e["quality_flags"]:
            e["estimate_reason"] = "round_boundary_uncertain"
            continue
        beta = models.get(e["session_id"])
        if beta is None:
            continue
        nearby = grouped.get((e["session_id"], e["round_no"]), [])
        ts = [s["t_ms"] for s in nearby]
        before = bisect_left(ts, e["t_ms"]) - 1
        after = bisect_right(ts, e["t_ms"])
        if (before < 0 or after >= len(ts) or e["t_ms"] - ts[before] > EVENT_WINDOW_MS
                or ts[after] - e["t_ms"] > EVENT_WINDOW_MS):
            e["estimate_reason"] = "missing_bracketing_states"
            continue
        selected = [nearby[before], nearby[after]]
        p, q = _coach_sigmoid(_coach_features(selected) @ beta)
        e.update(probability_before=float(p), probability_after=float(q),
                 state_delta=float(q-p), state_before=selected[0], state_after=selected[1],
                 estimate_reason="observational_state_change_not_personal_credit")


def run_coaching(store, manifests, out):
    """Write a reproducible bundle. Existing L1 and round tables are untouched."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    events, states, inputs, skipped, audits = [], [], [], [], []
    review_contexts = {}
    content_seen = set()
    for man in manifests:
        sid, date = man["session_id"], man["ingested_at"][:10]
        hp = store.hud_path(sid, date)
        if not hp.is_file():
            skipped.append(dict(session_id=sid, reason="missing_hud"))
            continue
        hud = pq.ParquetFile(hp).read()
        metadata = hud.schema.metadata or {}
        if metadata.get(b"hud_version", b"").decode() != HUD_VERSION:
            skipped.append(dict(session_id=sid, reason="stale_hud"))
            continue
        if metadata.get(b"session_id", b"").decode() != sid:
            skipped.append(dict(session_id=sid, reason="hud_identity_mismatch"))
            continue
        key = man["source"].get("content_key", sid)
        if key in content_seen:
            skipped.append(dict(session_id=sid, reason="duplicate_content"))
            continue
        content_seen.add(key)
        rounds = build_rounds(hud)
        review_contexts[sid] = dict(source_path=man["source"].get("path"),
                                    duration_ms=man["source"].get("duration_ms"),
                                    rounds=rounds)
        source = dict(session_id=sid, hud_sha256=_coach_digest(hp),
                      manifest_sha256=_coach_digest(store.manifest_path(sid)),
                      hud_version=HUD_VERSION, round_version=ROUND_VERSION)
        es = player_observations(hud, rounds, man)
        rp = store.roster_path(sid, date)
        roster = None
        roster_status = "missing"
        if rp.is_file():
            candidate = pq.ParquetFile(rp).read()
            source["roster_sha256"] = _coach_digest(rp)
            roster_status = "stale"
            rm = candidate.schema.metadata or {}
            identity_matches = (rm.get(b"session_id") == metadata.get(b"session_id")
                                and rm.get(b"content_key") == metadata.get(b"content_key"))
            if not identity_matches:
                roster_status = "identity_mismatch"
            if identity_matches and rm.get(b"roster_version", b"").decode() == ROSTER_VERSION:
                roster, roster_status = candidate, "current"
                source["roster_version"] = ROSTER_VERSION
                source["roster_split_version"] = ROSTER_SPLIT_VERSION
        ss, rejected = observed_states(hud, roster, rounds, sid)
        for e in es:
            e["provenance"] = source
        events.extend(es)
        states.extend(ss)
        inputs.append(source)
        audits.append(dict(session_id=sid, rounds=len(rounds), events=len(es),
                           states=len(ss), roster=roster_status, rejected=rejected))
    report, models, predictions = evaluate_states(states)
    attach_event_estimates(events, states, models)
    review = select_review_windows(events, states, review_contexts)
    # Fingerprint code as well as explicit versions: an unbumped edit is visible.
    code = {name: _coach_digest(Path(__file__).with_name(name)) for name in
            ("coaching.py", "review.py", "rounds.py", "roster.py", "checks.py", "version.py")}
    report.update(coach_version=COACH_VERSION, inputs=inputs, code_sha256=code,
                  review_version=REVIEW_VERSION, n_review_windows=len(review),
                  sessions=audits, skipped=skipped, n_events=len(events),
                  limits=["Pre-plant clock-observed states only; phase gate is provisional.",
                          "Round boundaries and killfeed observations remain imperfect.",
                          "No economy, attack/defence, POV or match-group metadata.",
                          "Session holdouts are retrospective, not prospective validation.",
                          "State deltas are not causal effects or player credit."])
    for name, rows in (("events", events), ("states", states), ("predictions", predictions),
                       ("review", review)):
        target = out / f"{name}.jsonl"
        temporary = target.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n"
                                     for r in rows), encoding="utf-8")
        temporary.replace(target)
    target = out / "report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    temporary.replace(target)
    (out / "review.md").write_text(render_review(review, report["status"]), encoding="utf-8")
    return report
