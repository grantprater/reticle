"""Build a player question from stored round-4 scoreboard and death evidence.

This is a review artifact, not an identity reader. The displayed answer is never
fed back into adjudication. Source images must already be annotated composites.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.store import Store


SESSION = "a06f04a0059f"
DEATH_MS = 281500.0
BOARD_MS = 282500.0


def build(store: Store, output: Path) -> dict:
    previous = json.loads(Path("teststore/death-round4-refusals/events.json").read_text(encoding="utf-8"))
    death = next(v for v in previous["verdicts"] if v["t_ms"] == DEATH_MS)
    if death["victim"] is not None:
        raise ValueError("the selected death is no longer a machine refusal")
    portrait = next(r for r in store.read_events("killfeed_portrait", SESSION)
                    if r.get("observation_key") == f"{SESSION}:16890:0:victim")
    rows = sorted((r for r in store.read_events("scoreboard", SESSION)
                   if r.get("kind") == "row_observation" and r.get("t_ms") == BOARD_MS),
                  key=lambda r: r["display_row"])
    if len(rows) != 10 or any(r.get("portrait_composition") is None for r in rows):
        raise ValueError("expected ten stored scoreboard portraits at the selected opening")
    victim = np.asarray(portrait["composition"], dtype=float)
    comparisons = [{
        "display_row": r["display_row"], "team": r["team"],
        "scoreboard_observation_key": r["observation_key"],
        "distance": round(float(np.linalg.norm(victim - np.asarray(r["portrait_composition"], dtype=float))), 4),
        "agent": None, "player_name": None,
    } for r in rows]
    result = {
        "session_id": SESSION, "death_ms": DEATH_MS, "scoreboard_ms": BOARD_MS,
        "death_id": death["death_id"],
        "killfeed_observation_key": portrait["observation_key"],
        "scoreboard_version": rows[0]["scoreboard_version"],
        "killfeed_portrait_version": portrait["killfeed_portrait_version"],
        "comparisons": comparisons,
        "binding": None,
        "reason": "no_unique_cross_surface_portrait_match_and_no_stored_scoreboard_name",
        "human_answer_use": "review_only_never_adjudication_input",
    }
    output.mkdir(parents=True, exist_ok=True)
    data = output / "binding-question.json"
    if data.exists() and json.loads(data.read_text(encoding="utf-8")) != result:
        raise FileExistsError(data)
    if not data.exists():
        data.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    items = "".join(
        f'<li>Row {r["display_row"]}: {html.escape(r["team"])}; '
        f'descriptor distance {r["distance"]:.4f}</li>' for r in comparisons)
    page = f"""<!doctype html><meta charset="utf-8"><title>Scoreboard binding question</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto;background:#171b22;color:#eee}}
img{{max-width:100%;height:auto}}li{{margin:.3rem 0}}</style>
<h1>Which scoreboard row matches this victim?</h1>
<p>Death observed at {DEATH_MS:.0f} ms; scoreboard observed at {BOARD_MS:.0f} ms.
Use the visible player name or portrait. If the connection is unclear, answer “cannot tell.”
This answer checks the reader; it does not name the machine event.</p>
<h2>Death source</h2><img alt="Annotated death source" src="../death-round4-v3/review-frame-1.jpg">
<h2>Scoreboard source</h2><img alt="Annotated scoreboard source" src="board-282500-annotated.jpg">
<h2>Stored row comparison</h2><ol start="0">{items}</ol>
<p>Question: which row, if any, shows the victim from the death source? Which visible
evidence establishes the match?</p>"""
    question = output / "question.html"
    if question.exists() and question.read_text(encoding="utf-8") != page:
        raise FileExistsError(question)
    if not question.exists():
        question.write_text(page, encoding="utf-8")
    return {"evidence": str(data), "question": str(question), "binding": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("teststore/death-round4-scoreboard"))
    args = parser.parse_args()
    print(json.dumps(build(Store(), args.output), indent=2))
