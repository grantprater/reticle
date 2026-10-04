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
first view with a crop is the role's crop. When both views refuse the name,
the role tries its other followed views in time order (`every=True`): at
223d636bf8d2 the victim at 335.5 s read no name text at both views, and its
portrait alone named Fade's player Iso, which the player corrected. The
player's own roles print "Me" and stay out of the clusters; the lineup
already names the player.

Measured in `prototypes/killfeed_name_continuity.py`; its stability, recall
and precision against the reference channels are the outcome
`killfeed-name-continuity` in the store's `notes/predictions.jsonl`.
Clustering is greedy: a crop joins the first cluster whose first member it
matches, in entry order.

**A name with a space can be read whole or cut at its word gap.** At
bfad2778a372 the ally killer crops read "FazeTSMGhost JBJ" (130 px) while the
same player's victim crops read "FazeTSMGhost" (100 px), and "Rylo Rodriguez"
(101 px) read "Rodriguez" (67 px) as a killer. Widths that far apart never
match, so one name made two large clusters, and the one-to-one assignment gave
the 11-role Miks fragment Fade against 204.5 nats of its own portrait
evidence. After the greedy pass, two clusters on one side link when a member
crop of the narrower matches the left- or right-aligned window of a member of
the wider at `NCC_MIN`: the narrower is one word of the wider's name. Clusters
read on two entries or more join along their links; a crop read once joins
the one group it links to, and two groups only when they read one name whole,
so one junk crop never bridges two names (`join_fragments`).

Owns [owns:killfeed-name-continuity].
"""
from __future__ import annotations

import cv2
import numpy as np

from ..killfeed import unpack_name_gray

# 0.1.0 (2026-09-26): greedy clusters of whole-name crops per plate side, from
# the `killfeed_name` stream at two followed views per entry role.
# 0.2.0 (2026-09-28): a role whose two views read no name tries its other
# followed views (`followed_views(every=True)`).
# 0.3.0 (2026-10-04): clusters whose crops are one name read whole and cut at
# its word gap join (`join_fragments`).
# 0.4.0 (2026-10-04): a singleton cluster joins only the one group it links
# to, or groups that read one name whole (`join_fragments`); scores come from
# one masked `_best_ncc` per crop and joins from `connected_components`.
KILLFEED_NAME_CLUSTER_VERSION = "killfeed-name-cluster-0.4.0"

#: Set from the two views of one entry, which are one name (labels-free).
NCC_MIN = 0.9
#: The white top-hat's side: wider than a stroke, so the plate is removed and
#: the text kept.
TOPHAT = 7
#: Widths of one name's crop differ by up to this much between frames.
WIDTH_TOL = 3
#: A word cut from a name is at least this wide (px). Swept over the 20
#: matches other than bfad2778a372 and graded against Riot, no floor from 8
#: to 40 px makes a join that mixes two Riot agents
#: [metric:killfeed_name_fragments/floor_members_sweep#impure_px8=0]; 24 px
#: keeps [metric:killfeed_name_fragments/floor_members_sweep#joins_px24=52]
#: of the [metric:killfeed_name_fragments/floor_members_sweep#joins_px8=55]
#: joins an 8 px floor makes, and its narrowest joined crop is
#: [metric:killfeed_name_fragments/floor_members_sweep#narrowest_px_px24=29]
#: px. The joins it gives up rest on crops as narrow as
#: [metric:killfeed_name_fragments/floor_members_sweep#narrowest_px_px8=15]
#: px, too few in the stored data to vouch for.
FRAGMENT_MIN_PX = 24
#: Members of each cluster compared when testing two clusters for one name.
#: On the same sweep three members make
#: [metric:killfeed_name_fragments/floor_members_sweep#joins_px24=52] joins,
#: one or two make [metric:killfeed_name_fragments/floor_members_sweep#joins_k2=51],
#: and four to six make
#: [metric:killfeed_name_fragments/floor_members_sweep#joins_k4=53], none of
#: them mixed; each further member adds a scoring call per crop.
FRAGMENT_MEMBERS = 3
#: A cluster with fewer members is a crop read once (`join_fragments`).
FRAGMENT_SUPPORT = 2

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


def _best_ncc(a: np.ndarray, bs: list[np.ndarray]) -> np.ndarray:
    """`ncc` of text `a` against each text in `bs` at once: the best Pearson
    correlation over the overlap, over shifts of up to `WIDTH_TOL` px across
    and 2 px vertically. The texts are laid in one zero-padded stack with a
    validity mask, so each shift is one masked sum over the whole stack."""
    hs = [b.shape[0] for b in bs] + [a.shape[0]]
    ws = [b.shape[1] for b in bs] + [a.shape[1]]
    H, W = max(hs), max(ws)
    A = np.zeros((H, W)); MA = np.zeros((H, W), bool)
    A[:a.shape[0], :a.shape[1]] = a
    MA[:a.shape[0], :a.shape[1]] = True
    B = np.zeros((len(bs), H, W)); MB = np.zeros((len(bs), H, W), bool)
    for k, b in enumerate(bs):
        B[k, :b.shape[0], :b.shape[1]] = b
        MB[k, :b.shape[0], :b.shape[1]] = True
    best = np.full(len(bs), -1.0)
    for dy in range(-2, 3):
        for dx in range(-WIDTH_TOL, WIDTH_TOL + 1):
            ya, yb, xa, xb = max(0, dy), max(0, -dy), max(0, dx), max(0, -dx)
            h, w = H - max(ya, yb), W - max(xa, xb)
            m = MA[ya:ya + h, xa:xa + w] & MB[:, yb:yb + h, xb:xb + w]
            p = np.where(m, A[ya:ya + h, xa:xa + w], 0.0)
            q = np.where(m, B[:, yb:yb + h, xb:xb + w], 0.0)
            n = m.sum(axis=(1, 2))
            sp, sq = p.sum(axis=(1, 2)), q.sum(axis=(1, 2))
            nn = np.maximum(n, 1)
            cov = (p * q).sum(axis=(1, 2)) - sp * sq / nn
            var = ((p * p).sum(axis=(1, 2)) - sp * sp / nn) * ((q * q).sum(axis=(1, 2)) - sq * sq / nn)
            ok = (n >= 9) & (var > 0)
            r = np.where(ok, cov / np.sqrt(np.where(ok, var, 1.0)), -1.0)
            best = np.maximum(best, r)
    return best


def fragment_matrix(grays: list[np.ndarray]) -> np.ndarray:
    """`out[a, b]`: how well name crop `a` reads as one word of crop `b`'s
    name, the better `ncc` of `a` against `b`'s left- and right-aligned
    windows of `a`'s width; 0 unless `a` is at least `FRAGMENT_MIN_PX` wide,
    more than `WIDTH_TOL` px narrower than `b`, and within 2 px of its height.
    One `_best_ncc` call per crop scores all its windows."""
    m = len(grays)
    out = np.zeros((m, m))
    if m < 2:
        return out
    hs = np.array([g.shape[0] for g in grays])
    ws = np.array([g.shape[1] for g in grays])
    part = ((np.abs(hs[:, None] - hs[None, :]) <= 2) & (ws[:, None] >= FRAGMENT_MIN_PX)
            & (ws[None, :] - ws[:, None] > WIDTH_TOL))
    for a in np.flatnonzero(part.any(axis=1)):
        bs, w = np.flatnonzero(part[a]), ws[a]
        wins = [_text(x) for b in bs for x in (grays[b][:, :w], grays[b][:, ws[b] - w:])]
        out[a, bs] = _best_ncc(_text(grays[a]), wins).reshape(-1, 2).max(axis=1)
    return out


def fragment_ncc(narrow: np.ndarray, wide: np.ndarray) -> float:
    """How well the `narrow` crop reads as one word of the `wide` crop's name
    (`fragment_matrix`); 0 when they cannot be one fragment and one whole."""
    return float(fragment_matrix([narrow, wide])[0, 1])


def reads_one_name(a: list[np.ndarray], b: list[np.ndarray]) -> bool:
    """Whether some crop of `a` and some crop of `b` show one name whole:
    widths within `WIDTH_TOL`, heights within 2 px and `ncc >= NCC_MIN`."""
    for g in a:
        near = [_text(x) for x in b
                if abs(x.shape[1] - g.shape[1]) <= WIDTH_TOL and abs(x.shape[0] - g.shape[0]) <= 2]
        if near and _best_ncc(_text(g), near).max() >= NCC_MIN:
            return True
    return False


def join_fragments(clusters: list[list[str]], crops: dict) -> list[list[str]]:
    """One side's clusters with each cluster that reads one word of another
    cluster's name joined to it, members in entry order, largest cluster
    first.

    Two clusters link when a member of one, among their first
    `FRAGMENT_MEMBERS`, matches the left- or right-aligned window of a member
    of the other at `NCC_MIN` (`fragment_matrix`): the narrower is one word of
    the wider's name. Clusters of at least `FRAGMENT_SUPPORT` members, names
    read on two entries or more, join along their links, and the joins chain
    (`connected_components`): a name cut on both sides of its gap joins
    through its whole reading. A singleton, a crop read once, joins the one
    group it links to. When it links two or more groups, it joins them only
    if each pair of them reads one name whole (`reads_one_name`), as when
    greedy clustering, which compares only first members, split one name;
    otherwise it joins nothing. A junk crop holding one name's word and
    another's, or a word two names share, so never bridges two names: the
    groups' own crops must carry the join."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    order = {eid: i for i, eid in enumerate(crops)}
    n = len(clusters)
    if n < 2:
        return [sorted(c, key=order.__getitem__) for c in clusters]
    heads = [c[:FRAGMENT_MEMBERS] for c in clusters]
    owner = np.repeat(np.arange(n), [len(h) for h in heads])
    member_of = np.eye(n, dtype=np.int64)[owner]                         # (members, clusters)
    frag = fragment_matrix([crops[e]["gray"] for h in heads for e in h]) >= NCC_MIN
    link = (member_of.T @ (frag & (owner[:, None] != owner[None, :])) @ member_of) > 0
    link |= link.T
    big = np.array([len(c) for c in clusters]) >= FRAGMENT_SUPPORT
    edge = link & big[:, None] & big[None, :]
    k, group = connected_components(csr_matrix(edge), directed=False)
    # The recurring groups each singleton links to.
    hits = ((link & big[None, :]).astype(np.int64) @ np.eye(k, dtype=np.int64)[group]) > 0
    joins = ~big & (hits.sum(axis=1) == 1)
    for i in np.flatnonzero(~big & (hits.sum(axis=1) > 1)):
        crops_of = [[crops[e]["gray"] for j in np.flatnonzero(group == g) for e in heads[j]]
                    for g in np.flatnonzero(hits[i])]
        joins[i] = all(reads_one_name(crops_of[x], crops_of[y])
                       for x in range(len(crops_of)) for y in range(x + 1, len(crops_of)))
    edge |= link & big[None, :] & joins[:, None]
    _, label = connected_components(csr_matrix(edge), directed=False)
    joined: dict[int, list[str]] = {}
    for i, c in enumerate(clusters):
        joined.setdefault(int(label[i]), []).extend(c)
    out = [sorted(c, key=order.__getitem__) for c in joined.values()]
    return sorted(out, key=lambda c: (-len(c), order[c[0]]))


def followed_views(observations: list[dict], every: bool = False
                   ) -> list[tuple[float, int, int]]:
    """Two (t_ms, slot, frame_idx) views of an entry from the portrait views
    death adjudication followed it through: a third and two thirds along. The
    slot and frame come from each view's `observation_key`
    (`sid:frame:slot:role`); the observation's own `slot` is the entry's first.
    `every` appends the other followed views in time order, as fallbacks for a
    reader that takes the first view it can read."""
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
    if every:
        picks += [i for i in range(len(views)) if i not in picks]
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
    largest first (ties keep entry order), with the roles left out and why;
    clusters reading one name whole and cut at its word gap are joined
    (`join_fragments`).

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
            "sides": {t: join_fragments(cl, crops) for t, cl in sides.items()},
            "left_out": {eid: c["reason"] for eid, c in crops.items() if c["reason"]}}
