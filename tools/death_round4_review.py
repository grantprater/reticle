"""Frozen, conservative stored-data death review for a06f04a0059f round 4.

Uses stored HUD/roster observations. The old identity harness's oracle lineup,
synthetic Skye claim, human label crops, and fixture locations are excluded.
Links observation times to original media. With explicit approval, exports seven
annotated, downscaled review composites; it never copies raw video.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.adjudication.death import adjudicate_round_deaths, death_verdict_to_events
from reticle.events import validate_event_rows
from reticle.killfeed import killfeed_roi
from reticle.profiles import get_profile
from reticle.store import Store
from prototypes.round_identity_eval import extract_round_killfeed_entries, load_round_bounds

SESSION = "a06f04a0059f"
DATE = "2026-08-26"
ROUND = 4
START_MS = 232000.0
END_MS = 351000.0


def _write_once(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(f"refusing to overwrite evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def export_review_frames(source: Path, profile_name: str, entries: list[dict],
                         fps: float, output: Path) -> list[str]:
    """Save seven labeled composites for source review, never unmarked frames."""
    roi = killfeed_roi(get_profile(profile_name))
    if roi is None:
        raise ValueError(f"profile {profile_name} has no killfeed ROI")
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open source {source}")
    paths = []
    try:
        for i, entry in enumerate(entries, 1):
            observation_ms = float(entry["t_ms"])
            frame_index = round((observation_ms + 100.0) * fps / 1000.0)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"cannot read source frame {frame_index}")
            x0, y0, x1, y1 = roi.pixels(frame.shape[1], frame.shape[0])
            marked = frame.copy()
            cv2.rectangle(marked, (x0, y0), (x1, y1), (0, 255, 255), 3)
            full = cv2.resize(marked, (960, 540), interpolation=cv2.INTER_AREA)
            crop = frame[y0:y1, x0:x1]
            detail = cv2.resize(crop, (640, 540), interpolation=cv2.INTER_CUBIC)
            canvas = np.full((610, 1600, 3), (28, 30, 34), dtype=np.uint8)
            canvas[70:610, :960] = full
            canvas[70:610, 960:] = detail
            label = (f"{SESSION} round {ROUND}  entry {i}/7  "
                     f"observed {observation_ms:.0f} ms  frame {frame_index}")
            cv2.putText(canvas, label, (20, 45), cv2.FONT_HERSHEY_SIMPLEX,
                        0.85, (0, 255, 255), 2, cv2.LINE_AA)
            success, encoded = cv2.imencode(".jpg", canvas,
                                            [cv2.IMWRITE_JPEG_QUALITY, 87])
            if not success:
                raise RuntimeError("review composite encoding failed")
            path = output / f"review-frame-{i}.jpg"
            _write_once(path, encoded.tobytes())
            paths.append(str(path))
    finally:
        cap.release()
    return paths


def build(store: Store, output: Path, export_frames: bool = False,
          minimum_named: int = 1) -> dict:
    start, end, _ = load_round_bounds(store, SESSION, DATE, ROUND)
    if (start, end) != (START_MS, END_MS):
        raise ValueError(f"frozen round bounds changed: {(start, end)}")
    manifest = json.loads(store.manifest_path(SESSION).read_text(encoding="utf-8"))
    source = Path(manifest["source"]["path"])
    if not source.is_file():
        raise FileNotFoundError(source)
    hud_table = store.read_hud(SESSION, DATE)
    hud = hud_table.to_pydict()
    entries = extract_round_killfeed_entries(hud, start, end)
    # The prototype helper injects a hard-coded Skye claim at 295500 ms when
    # no media/fixture is passed. Only its L1 timing and side fields are usable.
    for entry in entries:
        entry["claim"] = None
        entry["v_comps"] = None
        entry["k_comps"] = None
        entry["location"] = None
        entry["killer_location"] = None
    # A count change is an upstream observation change; review before accepting it.
    if len(entries) != 7:
        raise ValueError(f"expected 7 observed killfeed entries, got {len(entries)}")
    frame_paths = (export_review_frames(source, manifest["source_profile"], entries,
                                        float(manifest["source"]["fps"]), output)
                   if export_frames else [])

    lineup = json.loads((store.root / "lineups" / f"{SESSION}.json").read_text(encoding="utf-8"))
    player = lineup.get("player", {})
    if player.get("reason") or player.get("agent") != "Phoenix":
        raise ValueError("frozen player identity no longer has the reviewed Phoenix witness")
    roster_table = store.read_roster(SESSION, DATE)
    roster = roster_table.to_pylist()
    window_roster = [row for row in roster if start <= row["t_ms"] <= end]
    versions = {
        "hud": hud_table.schema.metadata[b"hud_version"].decode(),
        "roster": roster_table.schema.metadata[b"roster_version"].decode(),
        "lineup": lineup["version"],
    }
    verdicts = adjudicate_round_deaths(
        SESSION, entries, window_roster, player_agent=player["agent"],
    )
    named_count = sum(v.victim is not None for v in verdicts)
    if named_count < minimum_named:
        raise ValueError(f"only {named_count} named death(s); need {minimum_named}")
    events = []
    for verdict in verdicts:
        source_ref = {"session_id": SESSION, "t_ms": verdict.t_ms,
                      "frame_index": round(verdict.t_ms * manifest["source"]["fps"] / 1000),
                      "source_path": str(source)}
        for event in death_verdict_to_events(verdict, SESSION):
            event["metadata"]["source_ref"] = source_ref
            event["metadata"]["input_versions"] = versions
            event["metadata"]["time_basis"] = "observed killfeed entry"
            event["metadata"]["location_reason"] = (
                None if verdict.location is not None else "no verified death-location observation"
            )
            events.append(event)
    errors = validate_event_rows(events)
    if errors:
        raise ValueError(f"invalid death events: {errors}")
    if len(verdicts) != 7 or not any(v.victim == "Phoenix" for v in verdicts):
        raise ValueError("frozen event count or player death changed")
    report = {
        "session_id": SESSION, "round_no": ROUND, "window_ms": [start, end],
        "source_path": str(source), "source_profile": manifest["source_profile"],
        "input_tables": ["l1/hud", "l1/roster", "lineups"],
        "input_versions": versions, "content_key": manifest["source"]["content_key"],
        "limitations": ["Stored killfeed portrait observations are absent for this session.",
                        "No oracle lineup, synthetic claims, or human-label fixture locations were used.",
                        "The seven-entry count is an L1 result; source review must check misses and extras."],
        "summary": {"observed": len(verdicts),
                    "named": sum(v.victim is not None for v in verdicts),
                    "unresolved": sum(v.victim is None for v in verdicts),
                    "located": sum(v.location is not None for v in verdicts)},
        "verdicts": [v.to_dict() for v in verdicts], "events": events,
    }
    _write_once(output / "events.json", (json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    cards = []
    for verdict in verdicts:
        title = f"{verdict.t_ms:.0f} ms | {verdict.side} | {verdict.victim or 'unresolved'} | {verdict.status}"
        cards.append(f'<article><h2>{html.escape(title)}</h2><p>{html.escape(verdict.reason or "No identity refusal")}; location: {html.escape(str(verdict.location or "unresolved"))}</p><button onclick="seek({verdict.t_ms / 1000})">Open source time</button></article>')
    page = ('<!doctype html><meta charset="utf-8"><title>Round 4 death review</title>'
            '<style>body{font:16px system-ui;background:#171b22;color:#eee;margin:2rem}article{margin:2rem 0}video{max-width:100%}</style>'
            '<h1>Round 4 death review</h1><p>Review each source window for misses, extras and identity.</p>'
            f'<video id="source" controls src="{html.escape(source.as_uri(), quote=True)}"></video>'
            + "".join(cards) + '<script>function seek(t){let v=document.querySelector("video");v.currentTime=t;v.play()}</script>')
    _write_once(output / "review.html", page.encode("utf-8"))
    return {"summary": report["summary"], "events": str(output / "events.json"),
            "review": str(output / "review.html"), "review_frames": frame_paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-review-frames", action="store_true",
                        help="save seven approved annotated source composites")
    parser.add_argument("--minimum-named", type=int, default=1)
    args = parser.parse_args()
    if args.minimum_named < 1:
        parser.error("--minimum-named must be positive")
    print(json.dumps(build(Store(), args.output, export_frames=args.export_review_frames,
                           minimum_named=args.minimum_named), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
