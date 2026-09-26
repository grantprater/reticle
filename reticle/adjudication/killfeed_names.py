"""Which killfeed entry roles in one match print one player's name.

A killfeed name belongs to one player, hence one agent, for the whole match
[domain:rounds/agent-uniqueness]. This module joins entry roles whose name
crops (`killfeed.name_observations`, the `killfeed_name` stream) show the same
text on the same plate side, so `adjudication.identity` can name a player once
per match instead of once per entry. It never names anyone: a cluster is a set
of entity ids, and its agent is the arbiter's (`identity.name_cluster_claims`).

Two crops show one name when their widths differ by at most `WIDTH_TOL` px and
the normalised correlation of their text reaches `NCC_MIN`, best over small
shifts. The text is the band's whiteness less the plate behind it (a white
top-hat of side `TOPHAT`), because the plate's brightness changes with the
scene. Crops are compared only within one plate side: a hidden name prints the
agent's name, so an ally and an enemy on one agent print alike.

Each role is read at two of the views death adjudication followed it through
(a third and two thirds along), at the slot of that view: the stack rises as
older entries expire, so the entry's first slot holds another entry later. The
first view with a crop is the role's crop. The player's own roles print "Me"
and stay out of the clusters; the lineup already names the player.

Measured in `prototypes/killfeed_name_continuity.py`; its stability, recall
and precision against the reference channels are the outcome
`killfeed-name-continuity` in the store's `notes/predictions.jsonl`.
Clustering is greedy: a crop joins the first cluster whose first member it
matches, in entry order.

Owns [owns:killfeed-name-continuity].
"""
from __future__ import annotations

import cv2
import numpy as np

from ..killfeed import unpack_name_gray

# 0.1.0 (2026-09-26): greedy clusters of whole-name crops per plate side, from
# the `killfeed_name` stream at two followed views per entry role.
KILLFEED_NAME_CLUSTER_VERSION = "killfeed-name-cluster-0.1.0"

#: Set from the two views of one entry, which are one name (labels-free).
NCC_MIN = 0.9
#: The white top-hat's side: wider than a stroke, so the plate is removed and
#: the text kept.
TOPHAT = 7
#: Widths of one name's crop differ by up to this much between frames.
WIDTH_TOL = 3

OTHER_SIDE = {"ally": "enemy", "enemy": "ally"}


def _text(g: np.ndarray) -> np.ndarray:
    """The whiteness less the plate behind it (white top-hat)."""
    k = np.ones((TOPHAT, TOPHAT), np.uint8)
    return cv2.morphologyEx(g.astype(np.float32), cv2.MORPH_TOPHAT, k)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two crops' text, best over shifts of up to
    `WIDTH_TOL` px horizontally and 2 px vertically; 0 when their shapes
    differ by more than that."""
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > WIDTH_TOL:
        return 0.0
    a, b = _text(a), _text(b)
    best = -1.0
    for dy in (-2, -1, 0, 1, 2):
        for dx in range(-WIDTH_TOL, WIDTH_TOL + 1):
            ya, yb = max(0, dy), max(0, -dy)
            xa, xb = max(0, dx), max(0, -dx)
            h = min(a.shape[0] - ya, b.shape[0] - yb)
            w = min(a.shape[1] - xa, b.shape[1] - xb)
            if h < 3 or w < 3:
                continue
            p = a[ya:ya + h, xa:xa + w].ravel()
            q = b[yb:yb + h, xb:xb + w].ravel()
            p = p - p.mean()
            q = q - q.mean()
            d = float(np.sqrt((p * p).sum() * (q * q).sum()))
            if d > 0:
                best = max(best, float((p * q).sum()) / d)
    return best


def followed_views(observations: list[dict]) -> list[tuple[float, int, int]]:
    """Two (t_ms, slot, frame_idx) views of an entry from the portrait views
    death adjudication followed it through: a third and two thirds along. The
    slot and frame come from each view's `observation_key`
    (`sid:frame:slot:role`); the observation's own `slot` is the entry's first."""
    seen = {}
    for o in observations:
        key = o.get("observation_key")
        if not key:
            continue
        parts = key.split(":")
        seen[(float(o["t_ms"]), int(parts[2]))] = int(parts[1])
    views = sorted(seen)
    if not views:
        return []
    picks = sorted({len(views) // 3, (2 * len(views)) // 3})
    return [(views[i][0], views[i][1], seen[views[i]]) for i in picks]


def role_crops(roles: list[dict], name_rows: list[dict], session_id: str) -> dict:
    """{entity_id: {"team", "me", "gray" or None, "reason", "observation_key"}}
    for each role (`entity_id`, `role`, `team`, `views` from `followed_views`)."""
    rows = {r["observation_key"]: r for r in name_rows if r.get("kind") == "name_observation"}
    out = {}
    for role in roles:
        got, me, reason = None, False, "no_followed_view"
        for _, slot, frame in role["views"]:
            key = f"{session_id}:{frame}:{slot}:{role['role']}"
            r = rows.get(key)
            if r is None:
                reason = "no_name_observation"
                continue
            me = me or bool(r.get("me"))
            g = unpack_name_gray(r)
            if g is None:
                reason = r.get("reason") or "no_name_text"
                continue
            if got is None:
                got = (g, key)
        out[role["entity_id"]] = {
            "team": role["team"], "me": me,
            "gray": got[0] if got else None,
            "observation_key": got[1] if got else None,
            "reason": "player_me" if me else None if got else reason}
    return out


def self_entry(views: list[tuple[float, int, int]], name_rows: list[dict],
               session_id: str) -> tuple[bool | None, str | None]:
    """Whether one entry's killer and victim print one name, or None with the
    unread role's reason. `views` are the entry's `followed_views`.

    A self entry (a Clove revive's expiry, a spike death, a self-kill) prints
    one name on one colour end to end [domain:rounds/clove-revive-expiry-entry],
    as a revive banner does [domain:killfeed/revive-entries], so the plates
    alone cannot tell them apart. Across the darker killer plate and the
    lighter victim plate the `ncc >= NCC_MIN` rule read one name on 14 of 14
    Not Dead Yet entries and two on 8 of 8 Resurrection entries where both
    crops read; the victim's crop read no text on 12 of 34 one-colour banners
    (`revive-plate-self-entry` in the store's `notes/predictions.jsonl`)."""
    crops = role_crops([{"entity_id": r, "role": r, "team": None, "views": views}
                        for r in ("killer", "victim")], name_rows, session_id)
    for r in ("killer", "victim"):
        if crops[r]["gray"] is None:
            return None, f"{r}:{crops[r]['reason']}"
    return ncc(crops["killer"]["gray"], crops["victim"]["gray"]) >= NCC_MIN, None


def name_clusters(crops: dict) -> dict:
    """Per plate side, the clusters of entity ids whose crops show one name,
    largest first (ties keep entry order), with the roles left out and why.

    `crops` is `role_crops`'s output in entry order."""
    sides: dict[str, list[list[str]]] = {"ally": [], "enemy": []}
    for eid, c in crops.items():
        if c["me"] or c["gray"] is None or c["team"] not in sides:
            continue
        for cl in sides[c["team"]]:
            if ncc(crops[cl[0]]["gray"], c["gray"]) >= NCC_MIN:
                cl.append(eid)
                break
        else:
            sides[c["team"]].append([eid])
    return {"version": KILLFEED_NAME_CLUSTER_VERSION,
            "sides": {t: sorted(cl, key=len, reverse=True) for t, cl in sides.items()},
            "left_out": {eid: c["reason"] for eid, c in crops.items() if c["reason"]}}
