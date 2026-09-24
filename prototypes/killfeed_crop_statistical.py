"""Killfeed portrait adjudication under spatial crop uncertainty.

This prototype formulates killer portrait identification as an alignment search:
    score(agent) = max_{Delta_x} [ corr(crop(x0 + Delta_x), template(agent)) - lambda * (Delta_x)^2 ]
over horizontal shift Delta_x in [-10, +10] px with quadratic penalty lambda * (Delta_x)^2.

Addresses the defect in `docs/IDENTITY_EXEMPLAR_LOOP.md#open`:
At 284500 ms in session a06f04a0059f (victim Jett), Breach is the true killer.
A rigid heuristic crop is contaminated by assist icons to the left of the killer
portrait, corrupting normalized correlation and causing Breach to fail the 0.07 margin gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.appearance import hsv_composition, detail
from reticle.cli import _date_of
from reticle.killfeed import _plate_masks, killfeed_roi, analyse_killfeed
from reticle.lineup import load_lineup
from reticle.adjudication.identity import load_identity_gallery, _official_scores
from reticle.profiles import get_profile
from reticle.store import Store
from prototypes.round_identity_eval import extract_round_killfeed_entries, load_round_bounds

ROUND4_KILLER_TRUTH = {
    281500: ("Deadlock", "Killjoy", "enemy"),
    283500: ("Reyna", "Omen", "enemy"),
    284500: ("Jett", "Breach", "ally"),
    295000: ("Miks", "Killjoy", "enemy"),
    295500: ("Skye", "Phoenix", "ally"),
    301000: ("Phoenix", "Omen", "enemy"),
    332500: ("Iso", "Breach", "ally"),
}

DEFAULT_LAMBDA = 0.0015
DEFAULT_BUDGET = 10
MARGIN_GATE = 0.07


def evaluate_crop_at_offset(band: np.ndarray, furniture: np.ndarray, x0: int, dx: int,
                            wide: int, agent: str, gallery: dict) -> float:
    """Compute gallery correlation score for an agent at crop offset x0 + dx."""
    x = x0 + dx
    if x < 0 or x + wide > band.shape[1]:
        return 0.0
    art = band[:, x:x+wide]
    keep = ~furniture[:, x:x+wide]
    comp = hsv_composition(art, keep)
    if not comp.size:
        return 0.0
    scores = _official_scores(comp, [agent], gallery)
    return scores.get(agent, 0.0)


def optimize_killer_alignment(band: np.ndarray, furniture: np.ndarray, x0_nom: int,
                              candidates: list[str], gallery: dict,
                              shift_budget: int = DEFAULT_BUDGET,
                              lambda_reg: float = DEFAULT_LAMBDA) -> dict:
    """Search for optimal spatial shift Delta_x per candidate agent.

    Returns dict mapping agent to (score, best_dx, raw_corr).
    """
    bh = band.shape[0]
    wide = int(round(2.0 * bh))
    results = {}
    for agent in candidates:
        best_val = -1e9
        best_dx = 0
        best_raw = 0.0
        for dx in range(-shift_budget, shift_budget + 1):
            raw = evaluate_crop_at_offset(band, furniture, x0_nom, dx, wide, agent, gallery)
            val = raw - lambda_reg * (dx ** 2)
            if val > best_val:
                best_val = val
                best_dx = dx
                best_raw = raw
        results[agent] = {
            "score": round(float(best_val), 4),
            "dx": int(best_dx),
            "raw_corr": round(float(best_raw), 4),
        }
    return results


def run_killfeed_crop_experiment(session_id: str = "a06f04a0059f",
                                 shift_budget: int = DEFAULT_BUDGET,
                                 lambda_reg: float = DEFAULT_LAMBDA) -> dict:
    """Run alignment search experiment on 284500 ms views and round 4 controls."""
    store = Store()
    manifest = store.read_manifest(session_id)
    date = _date_of(manifest)
    hud = store.read_hud(session_id, date).to_pydict()
    start, end, _ = load_round_bounds(store, session_id, date, 4)
    entries = extract_round_killfeed_entries(hud, start, end)
    lineup = load_lineup(session_id, store.root)
    gallery = load_identity_gallery(store.root)

    profile = get_profile(manifest.get("source_profile", "valorant-16x9-bigmap"))
    roi = killfeed_roi(profile)
    vpath = manifest["source"]["path"]
    cap = cv2.VideoCapture(vpath)

    # 1. Evaluate the 4 entry views of the 284500 ms kill (victim Jett, killer Breach)
    views_284500 = [
        {"t_ms": 284500.0, "raw_x0": 103},
        {"t_ms": 285000.0, "raw_x0": 152},
        {"t_ms": 285500.0, "raw_x0": 146},
        {"t_ms": 286000.0, "raw_x0": 142},
    ]

    ally_candidates = lineup["board"]["ally"]["agents"]
    view_results = []

    for vinfo in views_284500:
        t = vinfo["t_ms"]
        cap.set(cv2.CAP_PROP_POS_MSEC, t)
        ok, frame = cap.read()
        if not ok:
            continue
        views = analyse_killfeed(frame, roi, 1920, 1080, profile_name="valorant-16x9-bigmap")
        view = next((v for v in views if v.slot == 2 and v.killer_run), None)
        if not view:
            continue

        x0, y0, x1, y1 = roi.pixels(1920, 1080)
        crop_roi = frame[y0:y1, x0:x1]
        band = crop_roi[view.y0:view.y1, :]
        bh = band.shape[0]
        wide = int(round(2.0 * bh))
        mask = np.ones(band.shape[:2], dtype=bool)
        green, red, white = _plate_masks(band, mask)
        furniture = green | red | (white > 0)

        # Baseline fixed raw crop
        rx = vinfo["raw_x0"]
        art_raw = band[:, rx:rx+wide]
        keep_raw = ~furniture[:, rx:rx+wide]
        comp_raw = hsv_composition(art_raw, keep_raw)
        raw_scores = _official_scores(comp_raw, ally_candidates, gallery)
        ord_raw = sorted(raw_scores.items(), key=lambda kv: -kv[1])
        top_raw, raw_top_score = ord_raw[0]
        raw_runner, raw_runner_score = ord_raw[1] if len(ord_raw) > 1 else (None, 0.0)
        raw_margin = raw_top_score - raw_runner_score

        # Nominal x0 from killer run edge
        x0_nom = view.killer_run[0] - 1 - wide

        # Optimized alignment search
        opt = optimize_killer_alignment(band, furniture, x0_nom, ally_candidates,
                                        gallery, shift_budget, lambda_reg)
        ord_opt = sorted(opt.items(), key=lambda kv: -kv[1]["score"])
        top_opt = ord_opt[0][0]
        top_opt_data = ord_opt[0][1]
        runner_opt = ord_opt[1][0]
        runner_opt_data = ord_opt[1][1]
        opt_margin = top_opt_data["score"] - runner_opt_data["score"]

        view_results.append({
            "t_ms": t,
            "raw_x0": rx,
            "nom_x0": x0_nom,
            "fixed": {
                "top": top_raw,
                "score": round(float(raw_top_score), 4),
                "runner": raw_runner,
                "runner_score": round(float(raw_runner_score), 4),
                "margin": round(float(raw_margin), 4),
                "breach_score": round(float(raw_scores.get("Breach", 0.0)), 4),
                "breach_rank": [k for k, _ in ord_raw].index("Breach") + 1,
                "accepted": (top_raw == "Breach" and raw_margin >= MARGIN_GATE),
            },
            "optimized": {
                "top": top_opt,
                "score": top_opt_data["score"],
                "dx": top_opt_data["dx"],
                "raw_corr": top_opt_data["raw_corr"],
                "runner": runner_opt,
                "runner_score": runner_opt_data["score"],
                "margin": round(float(opt_margin), 4),
                "breach_score": opt["Breach"]["score"],
                "breach_rank": [k for k, _ in ord_opt].index("Breach") + 1,
                "accepted": (top_opt == "Breach" and opt_margin >= MARGIN_GATE),
                "all_scores": {k: v["score"] for k, v in ord_opt},
            },
        })

    # 2. Test negative controls across all Round 4 deaths
    controls_results = []
    for e in entries:
        t0 = float(e["t_ms"])
        if int(t0) not in ROUND4_KILLER_TRUTH:
            continue
        victim_truth, killer_truth, killer_side = ROUND4_KILLER_TRUTH[int(t0)]
        candidates = lineup["board"][killer_side]["agents"]

        cap.set(cv2.CAP_PROP_POS_MSEC, t0)
        ok, frame = cap.read()
        if not ok:
            continue
        views = analyse_killfeed(frame, roi, 1920, 1080, profile_name="valorant-16x9-bigmap")
        view = next((v for v in views if v.slot == e.get("slot") and v.killer_run), None)
        if not view:
            continue

        x0, y0, x1, y1 = roi.pixels(1920, 1080)
        crop_roi = frame[y0:y1, x0:x1]
        band = crop_roi[view.y0:view.y1, :]
        bh = band.shape[0]
        wide = int(round(2.0 * bh))
        mask = np.ones(band.shape[:2], dtype=bool)
        green, red, white = _plate_masks(band, mask)
        furniture = green | red | (white > 0)
        x0_nom = view.killer_run[0] - 1 - wide

        opt = optimize_killer_alignment(band, furniture, x0_nom, candidates,
                                        gallery, shift_budget, lambda_reg)
        ord_opt = sorted(opt.items(), key=lambda kv: -kv[1]["score"])
        top_name = ord_opt[0][0]
        runner_name = ord_opt[1][0]
        margin = ord_opt[0][1]["score"] - ord_opt[1][1]["score"]

        controls_results.append({
            "t_ms": t0,
            "victim": victim_truth,
            "killer_truth": killer_truth,
            "side": killer_side,
            "predicted": top_name,
            "score": ord_opt[0][1]["score"],
            "dx": ord_opt[0][1]["dx"],
            "runner": runner_name,
            "runner_score": ord_opt[1][1]["score"],
            "margin": round(float(margin), 4),
            "correct": (top_name == killer_truth),
        })

    cap.release()

    return {
        "session_id": session_id,
        "shift_budget": shift_budget,
        "lambda_reg": lambda_reg,
        "views_284500": view_results,
        "round4_controls": controls_results,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Statistical crop alignment for killfeed portraits")
    ap.add_argument("--session", default="a06f04a0059f")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ap.add_argument("--lambda-reg", type=float, default=DEFAULT_LAMBDA)
    args = ap.parse_args(argv)

    print(f"Running killfeed crop statistical alignment on session {args.session}...")
    res = run_killfeed_crop_experiment(args.session, args.budget, args.lambda_reg)

    print("\n" + "=" * 70)
    print(f"KILLFEED VIEWS AT 284500 MS (True Killer: Breach, Victim: Jett)")
    print("=" * 70)
    print(f"{'Time (ms)':<10} | {'Fixed Top':<10} {'Margin':<8} {'Status':<8} | {'Opt Top':<10} {'dx':<5} {'Score':<8} {'Margin':<8} {'Status':<8}")
    print("-" * 70)
    for v in res["views_284500"]:
        t = int(v["t_ms"])
        f_top = v["fixed"]["top"]
        f_m = v["fixed"]["margin"]
        f_st = "PASS" if v["fixed"]["accepted"] else "FAIL"
        o_top = v["optimized"]["top"]
        o_dx = f"{v['optimized']['dx']:+d}"
        o_sc = v["optimized"]["score"]
        o_m = v["optimized"]["margin"]
        o_st = "PASS" if v["optimized"]["accepted"] else "FAIL"
        print(f"{t:<10} | {f_top:<10} {f_m:<8.4f} {f_st:<8} | {o_top:<10} {o_dx:<5} {o_sc:<8.4f} {o_m:<8.4f} {o_st:<8}")

    print("\nDetailed scores under optimization:")
    for v in res["views_284500"]:
        print(f"  t={int(v['t_ms'])}: {v['optimized']['all_scores']}")

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROLS ACROSS ROUND 4")
    print("=" * 70)
    print(f"{'Time (ms)':<10} | {'Victim':<10} | {'True Killer':<12} | {'Predicted':<12} {'dx':<5} {'Margin':<8} {'Result':<6}")
    print("-" * 70)
    correct_count = 0
    for c in res["round4_controls"]:
        t = int(c["t_ms"])
        vic = c["victim"]
        tru = c["killer_truth"]
        pred = c["predicted"]
        dx = f"{c['dx']:+d}"
        m = c["margin"]
        ok = "PASS" if c["correct"] else "FAIL"
        if c["correct"]:
            correct_count += 1
        print(f"{t:<10} | {vic:<10} | {tru:<12} | {pred:<12} {dx:<5} {m:<8.4f} {ok:<6}")

    print("-" * 70)
    print(f"Accuracy: {correct_count}/{len(res['round4_controls'])} ({correct_count/len(res['round4_controls']):.1%})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
