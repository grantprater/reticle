"""Which agent each scoreboard row shows, and whether the game dimmed it as dead.

The reader (`reticle.scoreboard`) scores every portrait against the official
square agent art and stores the raw best, runner-up, margin and brightness gain.
This module decides which openings are trustworthy and what they say.

**The board is the unit of acceptance, not the row.** A board still fading in
draws live portraits at low contrast, which reads exactly like the dimming the
game applies to the dead [domain:rounds/scoreboard-dead-dimmed]. On
`a06f04a0059f` at 237500 ms four live allies read dim while the enemy rows,
still sliding in, failed the agent gate. So one failed row refuses the whole
opening, and a gain between the two bands refuses it as well.

**Measured on one round, so provisional.** Round 4 of `a06f04a0059f`, eight
openings: expanded rows scored 0.80-0.94 with margins of at least 0.30, and
misaligned rows at most 0.70 with margins of at most 0.23. Live gain was
0.84-0.95 and dimmed gain was 0.30-0.41. The cuts sit in those gaps; the
row identity also has to hold across openings, which the death witness checks
by requiring each side's five agents to be distinct.

**This module gates rows; it does not decide names.** Each gated row becomes
an `identity_claim` on channel `scoreboard_portrait`, and the name on a row is
`adjudication.identity`'s verdict. The distinct-agents test only accepts or
refuses an opening. Naming a side from the board belongs to
`identity.assign_side`, which needs the full per-agent score matrix this
reader does not yet store.

**Two witnesses say the board is on screen.** The slab test
(`scoreboard.read_scoreboard`) stores one `sample` row per frame it read,
open or closed with the branch that closed it; the round-history strip
(`scoreboard_strip.read_strip`) stores one per cached frame, `present`,
`absent` or `unreadable` [domain:hud/scoreboard-round-history-strip]. They
sample the same frames. `board_presence` reads both rows and neither rule:
the board is present where the slab test opened it or the strip reads
present, and each sample keeps what each witness said, so the
disagreements (`slab_only`, `strip_only`, and `unreadable` where the strip
could not read) stay countable. From `scoreboard-0.8.0` the slab test asks
the strip where its blocks lie, and a read it anchored there
(`anchor == "strip"`) rests on the strip: such a sample is `both_anchored`,
one witness and a read that depends on it, and only a read placed by the
tallest runs counts as `both`. Stored rows without `anchor` count as before. The player holds Tab to open the board and
releases it to close it [domain:hud/scoreboard-tab-hold]; `presence_runs`
groups present samples into holds, joined across one-sample holes. Only the
slab test reads rows, so an opening the strip alone saw names nothing.

**A board confirmed by its portraits counts once.** From `scoreboard-0.9.0`
the strip's lower line may place the enemy rows where no red run confirms
them, and the reader then opens the board only when all five enemy portraits
score at least `PORTRAIT_CONFIRM_MIN` (stored `confirm == "portraits"`).
Those rows have no witness but the portrait scores, and the gate accepts the
opening on the same scores. So each opening says where its enemy rows come
from (`enemy_rows_from`): `slab` where a red run placed or confirmed them,
`portraits` where the portraits alone did. An accepted opening witnesses its
rows' placement only where they come from the slab; one from the portraits
names agents and no more, and the coverage counts it apart.

Owns [owns:scoreboard-row-agent] and [owns:scoreboard-presence].
"""
from __future__ import annotations

from collections import defaultdict

from .identity import BOARD_MARGIN_MIN, adjudicate_agent_identity, identity_claim

# 0.3.0: given the strip's rows, openings are built from the combined
# presence (`board_presence`): each carries what both witnesses said and its
# hold, and a sample only the strip saw is an opening refused as
# `strip_only_no_rows`. The portrait gate is unchanged.
# 0.4.0: a sample whose slab read was anchored on the strip (the stored
# `anchor`, from scoreboard-0.8.0) is `both_anchored`, not `both`; each
# sample keeps the anchor as `slab_anchor`. Rows without it count as before.
# 0.5.0: each opening says where its enemy rows come from
# (`enemy_rows_from`, `ENEMY_ROWS_FROM`): a board the reader confirmed by its
# portraits rests on them, so its acceptance is counted once. The gate's
# verdicts are unchanged.
SCOREBOARD_AGENT_VERSION = "scoreboard-agent-0.5.0"

#: Where an opening's enemy rows come from: a red run of the slab test placed
#: or confirmed them (`slab`; every read without a stored `confirm`, before
#: scoreboard-0.9.0 or placed by the tallest runs, is one), or the five enemy
#: portraits alone confirmed the rows the strip's line placed (`portraits`).
ENEMY_ROWS_FROM = ("slab", "portraits")

#: Consecutive samples further apart than this are not neighbours: a gap in
#: the sampling breaks a hold rather than being joined across. The scan and
#: the crop cache sample every 500 ms.
SAMPLE_GAP_MS = 750.0

AGENT_SCORE_MIN = 0.75
AGENT_MARGIN_MIN = BOARD_MARGIN_MIN
DIM_GAIN_MAX = 0.60
LIT_GAIN_MIN = 0.75


def _row_state(row: dict) -> tuple[str | None, bool | None, str | None]:
    """(agent, dim, reason) for one stored row; a refused row names nothing."""
    if row.get("portrait_agent_reason"):
        return None, None, row["portrait_agent_reason"]
    score, margin, gain = (row.get("portrait_agent_score"),
                           row.get("portrait_agent_margin"), row.get("portrait_gain"))
    if score is None or margin is None or gain is None:
        return None, None, "portrait_agent_not_scored"
    if score < AGENT_SCORE_MIN:
        return None, None, f"agent_score_below_gate {score:.3f}"
    if margin < AGENT_MARGIN_MIN:
        return None, None, f"agent_margin_below_gate {margin:.3f}"
    if gain <= DIM_GAIN_MAX:
        return row["portrait_agent_best"], True, None
    if gain >= LIT_GAIN_MIN:
        return row["portrait_agent_best"], False, None
    return None, None, f"gain_between_bands {gain:.3f}"


#: The K/D/A fields of a row, as `row_counts` gives them.
COUNT_FIELDS = ("kills", "deaths", "assists")


def row_counts(row: dict, dim: bool | None) -> dict:
    """A stored row's kills, deaths and assists as this module stands behind
    them, with `counts_reason` saying why a count is null, and the reader's
    own values under `counts_raw`.

    **A dimmed row's counts are unread.** The reader binarises each digit
    cell at the lit table's contrast, and a dimmed (dead) row
    [domain:rounds/scoreboard-dead-dimmed] mostly yields no digits at all:
    its deaths read null on all but a handful of dim rows on four sessions.
    The few it did read contradict themselves (043bafca271a, ally Jett
    dimmed 1395.0-1405.0 s: deaths 2, then 2, then 12), so none is taken: a
    death that dimmed a row is counted from the next lit opening, never
    guessed as the last lit count plus one. A lit row's null count is the
    reader's refusal (`digit_cell_unread`); a row whose dim state the gate
    refused is `row_state_unknown`.
    """
    raw = {k: row.get(k) for k in COUNT_FIELDS}
    if dim is True:
        return {**{k: None for k in COUNT_FIELDS}, "counts_reason": "dimmed_row_unread",
                "counts_raw": raw}
    if dim is None:
        return {**{k: None for k in COUNT_FIELDS}, "counts_reason": "row_state_unknown",
                "counts_raw": raw}
    return {**raw, "counts_reason": ("digit_cell_unread" if None in raw.values() else None),
            "counts_raw": raw}


def _slab_samples(board_rows: list[dict], grid: set[int]) -> tuple[dict[int, dict], str | None]:
    """The slab test's verdict per sample frame, from its stored rows, and
    where its closed samples come from.

    From `scoreboard-0.7.0` the reader stores a `sample` row per frame it read
    (`sample_rows`). Rows written before stored only the open frames' rows;
    a closed sample is then taken at each frame of `grid` (the strip's cached
    frames) without rows, and only when the reader's coverage offered exactly
    that many frames and every open frame lies on it (`offered_frames`); its
    reason is None, unstored. Otherwise closed samples are unknown (None)."""
    stored = [r for r in board_rows if r.get("kind") == "sample"]
    if stored:
        return ({int(r["frame_idx"]): {"t_ms": float(r["t_ms"]),
                                       "slab": "open" if r["open"] else "closed",
                                       "slab_reason": r.get("reason"),
                                       "slab_anchor": r.get("anchor")} for r in stored},
                "sample_rows")
    out = {}
    for r in board_rows:
        if r.get("kind") == "row_observation":
            out[int(r["frame_idx"])] = {"t_ms": float(r["t_ms"]), "slab": "open",
                                        "slab_reason": None}
    offered = next((r.get("frames_offered") for r in board_rows
                    if r.get("kind") == "coverage"), None)
    if grid and offered == len(grid) and set(out) <= grid:
        for f in grid - set(out):
            out[f] = {"t_ms": None, "slab": "closed", "slab_reason": None}
        return out, "offered_frames"
    return out, None


def _witness(slab: str | None, strip: str | None, anchor: str | None = None) -> str:
    """Which witnesses saw the board at one sample. A slab read anchored on
    the strip (`anchor == "strip"`) is not a second witness beside it."""
    if strip is None:
        return "no_strip"
    if slab is None:
        return "no_slab"
    if strip == "unreadable":
        return "unreadable"
    if (slab, strip) == ("open", "present") and anchor == "strip":
        return "both_anchored"
    return {("open", "present"): "both", ("open", "absent"): "slab_only",
            ("closed", "present"): "strip_only", ("closed", "absent"): "neither"}[(slab, strip)]


def board_presence(board_rows: list[dict], strip_rows: list[dict]) -> dict:
    """Per sample, what the slab test and the strip said, and whether the board
    is on screen: the slab test opened it, or the strip reads present.

    Reads the two witnesses' stored rows (`scoreboard` and `scoreboard_strip`
    events) and neither rule. Returns `samples`, one per frame either witness
    read, in frame order: `slab` (`open`, `closed` or None), `slab_reason`,
    `slab_anchor` (the rule that placed the slab read's blocks, None on rows
    stored before `scoreboard-0.8.0`), `strip` (`present`, `absent`,
    `unreadable` or None), `strip_reason`, `present` and `witness` (`both`,
    `both_anchored`, `slab_only`, `strip_only`, `neither`, `unreadable`,
    `no_strip`, `no_slab`); and `slab_closed_from`, where the slab test's
    closed samples come from (`_slab_samples`).
    """
    strip = {int(r["frame_idx"]): r for r in strip_rows if r.get("kind") == "sample"}
    slab, closed_from = _slab_samples(board_rows, set(strip))
    samples = []
    for f in sorted(set(slab) | set(strip)):
        s, w = slab.get(f), strip.get(f)
        sv, wv = (s or {}).get("slab"), (w or {}).get("verdict")
        t_ms = (w or {}).get("t_ms")
        anchor = (s or {}).get("slab_anchor")
        samples.append({"frame_idx": f, "t_ms": float(t_ms if t_ms is not None else s["t_ms"]),
                        "slab": sv, "slab_reason": (s or {}).get("slab_reason"),
                        "slab_anchor": anchor,
                        "strip": wv, "strip_reason": (w or {}).get("reason"),
                        "present": sv == "open" or wv == "present",
                        "witness": _witness(sv, wv, anchor)})
    return {"samples": samples, "slab_closed_from": closed_from}


def presence_runs(samples: list[dict], on=None) -> list[dict]:
    """Holds: runs of samples on which `on` holds (default: `present`), joined
    across one-sample holes, the board closed for one sample between two open
    ones. Samples further apart than SAMPLE_GAP_MS are not neighbours.

    Each run gives its first and last sample index (`a`, `z`) and frame, the
    number of samples `on` holds for, and the frames of its holes; a run of
    one sample is `single`."""
    on = on or (lambda s: s["present"])
    flags = [bool(on(s)) for s in samples]
    ts = [s["t_ms"] for s in samples]
    near = lambda i: ts[i + 1] - ts[i] <= SAMPLE_GAP_MS  # noqa: E731
    n, out, i = len(samples), [], 0
    while i < n:
        if not flags[i]:
            i += 1
            continue
        a = j = i
        holes = []
        while True:
            while j + 1 < n and flags[j + 1] and near(j):
                j += 1
            if j + 2 < n and not flags[j + 1] and flags[j + 2] and near(j) and near(j + 1):
                holes.append(samples[j + 1]["frame_idx"])
                j += 2
                continue
            break
        out.append({"a": a, "z": j, "first_frame": samples[a]["frame_idx"],
                    "last_frame": samples[j]["frame_idx"], "t_first_ms": ts[a],
                    "t_last_ms": ts[j], "samples_on": j - a + 1 - len(holes),
                    "holes": holes, "single": a == j})
        i = j + 1
    return out


def enemy_rows_from(group: list[dict]) -> str | None:
    """Where one opening's enemy rows come from (`ENEMY_ROWS_FROM`), from the
    `confirm` its stored rows carry; None for an opening without rows."""
    if not group:
        return None
    return "portraits" if group[0].get("confirm") == "portraits" else "slab"


def scoreboard_openings(rows: list[dict], *, strip_rows: list[dict] | None = None) -> list[dict]:
    """Group stored row observations into openings and gate each one whole.

    An accepted opening names five distinct agents per side, each lit or dim.
    A refused one keeps its per-row reasons and names nothing.

    Given the strip's stored rows, openings are built from the combined
    presence (`board_presence`): every present sample is an opening carrying
    what each witness said (`presence`) and the index of its hold
    (`presence_runs`). A sample only the strip saw has no rows to gate and is
    refused as `strip_only_no_rows`.

    Each opening carries `enemy_rows_from`: `portraits` where the reader
    confirmed the enemy rows by the same portrait scores this gate reads, so
    its acceptance witnesses the agents and not the rows' placement.
    """
    by_t: dict[float, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("kind") == "row_observation":
            by_t[float(row["t_ms"])].append(row)
    out = []
    for t_ms in sorted(by_t):
        group = sorted(by_t[t_ms], key=lambda r: r["display_row"])
        states, claims = [], []
        for row in group:
            agent, dim, reason = _row_state(row)
            entity = f"scoreboard:{t_ms:.0f}:{row['team']}:row:{row['display_row']}"
            claims.append(identity_claim(
                entity, agent, channel="scoreboard_portrait", observed_at_ms=t_ms,
                reason=reason, source_version=row.get("scoreboard_version"),
                evidence={"observation_key": row.get("observation_key"),
                          "score": row.get("portrait_agent_score"),
                          "margin": row.get("portrait_agent_margin"),
                          "gain": row.get("portrait_gain")}))
            states.append({"observation_key": row.get("observation_key"),
                           "entity_id": entity,
                           "display_row": row["display_row"], "team": row["team"],
                           "agent": None, "dim": dim, "reason": reason,
                           **row_counts(row, dim),
                           "score": row.get("portrait_agent_score"),
                           "margin": row.get("portrait_agent_margin"),
                           "gain": row.get("portrait_gain"),
                           "scores": row.get("portrait_agent_scores")})
        named = {v["entity_id"]: v["agent"] for v in adjudicate_agent_identity(claims)}
        for state in states:
            state["agent"] = named.get(state["entity_id"])
        reason = None
        teams = [s["team"] for s in states]
        ally_y = [r["row_y0"] for r in group if r["team"] == "ally" and r.get("row_y0") is not None]
        enemy_y = [r["row_y0"] for r in group if r["team"] == "enemy" and r.get("row_y0") is not None]
        if teams.count("ally") != 5 or teams.count("enemy") != 5:
            reason = "not_five_rows_per_side"
        elif ally_y and enemy_y and min(enemy_y) <= max(ally_y):
            # The enemy block is drawn below the ally block. At 1999000 ms of
            # a06f04a0059f the reader placed the enemy rows ON the ally rows
            # and read the ally portraits twice -- a reader defect this gate
            # refuses rather than names.
            reason = "enemy_rows_not_below_ally_rows"
        elif any(s["reason"] for s in states):
            reason = "row_refused"
        else:
            for side in ("ally", "enemy"):
                names = [s["agent"] for s in states if s["team"] == side]
                if len(set(names)) != 5:
                    reason = f"{side}_agents_not_distinct"
        out.append({"t_ms": t_ms, "frame_idx": group[0].get("frame_idx"),
                    "accepted": reason is None, "reason": reason, "rows": states,
                    "claims": claims, "enemy_rows_from": enemy_rows_from(group),
                    "source_version": group[0].get("scoreboard_version"),
                    "version": SCOREBOARD_AGENT_VERSION})
    if strip_rows is None:
        return out
    samples = board_presence(rows, strip_rows)["samples"]
    hold = {}
    for k, run in enumerate(presence_runs(samples)):
        for s in samples[run["a"]:run["z"] + 1]:
            hold[s["frame_idx"]] = k
    by_frame = {s["frame_idx"]: s for s in samples}
    for o in out:
        s = by_frame.get(int(o["frame_idx"]))
        o["presence"] = None if s is None else {k: s[k] for k in ("slab", "strip", "witness")}
        o["hold"] = hold.get(int(o["frame_idx"]))
    strip_version = next((r.get("scoreboard_strip_version") for r in strip_rows), None)
    for s in samples:
        if s["present"] and s["slab"] != "open":
            out.append({"t_ms": s["t_ms"], "frame_idx": s["frame_idx"], "accepted": False,
                        "reason": "strip_only_no_rows", "rows": [], "claims": [],
                        "enemy_rows_from": None,
                        "presence": {k: s[k] for k in ("slab", "strip", "witness")},
                        "hold": hold.get(s["frame_idx"]), "source_version": strip_version,
                        "version": SCOREBOARD_AGENT_VERSION})
    return sorted(out, key=lambda o: o["t_ms"])


def side_state(opening: dict, side: str) -> dict[str, set[str]]:
    """The accepted opening's agents on one side, split into lit and dim."""
    rows = [s for s in opening["rows"] if s["team"] == side]
    return {"lit": {s["agent"] for s in rows if s["dim"] is False},
            "dim": {s["agent"] for s in rows if s["dim"] is True}}
