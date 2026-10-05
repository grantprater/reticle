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
join along their links, but no cluster, read once or on many entries, joins
two groups each read on two entries or more unless the groups read one name
whole, one is a word of the other, or it is a word at the left end of one and
the right end of the other with too little beside it for another word. Every
such bridge is removed before any is tested, so a junk crop, two junk
clusters or a word two names share at one end never bridges two names
(`join_fragments`).

**One residual is by design.** A word two names share at opposite ends
("TAG X" and "Y TAG") still bridges them when each crop is less than
`FRAGMENT_MIN_PX` wider than the shared word (the other word plus the gap
beside it), because the guard cannot tell it from one name whose crops carry
an icon's edge on opposite sides: with 12 px other words (18 px beside the
shared word) all six crops of that case merge. Both guard
conditions were designed and checked on the same 21 Riot matches; no
held-out data tests them.

Every score is one masked sum per shift over a stack of crops
(`_pair_ncc`), and every top-hat one erosion and one dilation over a canvas
of crops (`_tophat`); `ncc` scores one pair the same way.

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
# 0.5.0 (2026-10-04): the bridge guard covers every cluster, not only
# singletons: a cluster whose links would join two groups each read on two
# entries or more joins them only when they read one name whole or it is a
# word at the left end of one and the right end of the other; otherwise it
# joins nothing. On the 21 Riot matches it changes no join
# [metric:killfeed_name_fragments/bridge_guard#shipped_join_sets_changed=0];
# the opposite-ends case keeps
# [metric:killfeed_name_fragments/bridge_guard#bridges_at_opposite_ends=10]
# joins, none mixing Riot agents, that reading one name whole alone would cut
# (designed on those matches; no held-out data). Scores and top-hats are
# batched (`_pair_ncc`, `_tophat`), greedy clustering included; texts are
# bit-equal and scores within float error of 0.4.0's
# [metric:killfeed_name_fragments/scorer_equality#ncc_threshold_flips=0], and
# clustering the 21 matches takes
# [metric:killfeed_name_fragments/join_time#name_clusters_s_050=6.95] s
# against [metric:killfeed_name_fragments/join_time#name_clusters_s_040=18.08].
# 0.5.1 (2026-10-04): the guard removes every bridge before testing any, and
# each recurring bridge counts as a group of its own, so two recurring junk
# clusters on the same two names no longer vouch for each other; two groups
# may also join when one is a word of the other. The opposite-ends case
# needs less than `FRAGMENT_MIN_PX` beside the word in each group, so a word
# two names share at opposite ends ("TAG X", "Y TAG") no longer joins them.
# Without that case the guard splits the joins of
# [metric:killfeed_name_fragments/opposite_ends_051#joins_split_without_opposite_ends=11]
# of the 42 side-runs on the 21 Riot matches, so it stays (0.5.0's guard
# without it splits 9); the widest rest
# beside a kept word there is
# [metric:killfeed_name_fragments/strict_guard#widest_rest_px=18] px. On the
# 21 matches the join sets equal 0.5.0's
# [metric:killfeed_name_fragments/strict_guard#side_runs_changed=0]
# (designed on those matches; no held-out data). The test of every bridge is
# one batch per pass, with no Python loop over bridges.
KILLFEED_NAME_CLUSTER_VERSION = "killfeed-name-cluster-0.5.1"

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


def _stack(arrays: list[np.ndarray], fill: float = 0.0, pad: int = 0
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """2-D arrays of differing shapes laid top-left in one float32 stack
    `(n, H + pad, W + pad)`, the rest `fill`, with the mask of laid pixels
    and each array's height and width. One scatter places every pixel."""
    hs = np.array([a.shape[0] for a in arrays], np.int64)
    ws = np.array([a.shape[1] for a in arrays], np.int64)
    n, sizes = len(arrays), hs * ws
    flat = np.concatenate([np.asarray(a, np.float32).reshape(-1) for a in arrays])
    k = np.repeat(np.arange(n), sizes)
    local = np.arange(flat.size) - np.repeat(np.cumsum(sizes) - sizes, sizes)
    wk = np.repeat(ws, sizes)
    shape = (n, int(hs.max()) + pad, int(ws.max()) + pad)
    s = np.full(shape, fill, np.float32)
    m = np.zeros(shape, bool)
    s[k, local // wk, local % wk] = flat
    m[k, local // wk, local % wk] = True
    return s, m, hs, ws


def _tophat(s: np.ndarray, m: np.ndarray) -> np.ndarray:
    """The white top-hat of side `TOPHAT` of each masked image in the stack
    `s` `(n, H, W)`, as `cv2.morphologyEx` computes it on the image alone:
    pixels outside its mask count as the border, ignored by the erosion and
    the dilation. The stack is one canvas, each cell padded by the kernel's
    half-width, eroded and dilated once. Zero outside the masks."""
    r = TOPHAT // 2
    n, h, w = s.shape
    c = np.full((n, h + r, w + r), np.inf, np.float32)
    c[:, :h, :w] = np.where(m, s, np.inf)
    mc = np.zeros(c.shape, bool)
    mc[:, :h, :w] = m
    k = np.ones((TOPHAT, TOPHAT), np.uint8)
    e = cv2.erode(c.reshape(n * (h + r), w + r), k)
    e = np.where(mc.reshape(e.shape), e, -np.inf).astype(np.float32)
    o = cv2.dilate(e, k).reshape(c.shape)
    return np.where(mc, c - o, np.float32(0))[:, :h, :w]


def _texts(grays: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Each crop's text (`_text`) in one stack, with its mask, heights and
    widths (`_stack`)."""
    s, m, hs, ws = _stack(grays)
    return _tophat(s, m), m, hs, ws


def _text(g: np.ndarray) -> np.ndarray:
    """The whiteness less the plate behind it (white top-hat)."""
    k = np.ones((TOPHAT, TOPHAT), np.uint8)
    return cv2.morphologyEx(g.astype(np.float32), cv2.MORPH_TOPHAT, k)


#: Pixels per chunk of a pair stack (`_pair_ncc`), bounding its memory.
CHUNK_PX = 1 << 16


def _integral(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Summed-area tables of a stack `(n, H, W)` and of its squares, for the
    stack as one canvas of `n * H` rows (`cv2.integral2`)."""
    n, h, w = x.shape
    s, sq = cv2.integral2(np.ascontiguousarray(x.reshape(n * h, w)), sdepth=cv2.CV_64F,
                          sqdepth=cv2.CV_64F)
    return s, sq


def _rect(ii: np.ndarray, h_img: int, y0: np.ndarray, x0: np.ndarray, h: np.ndarray,
          w: np.ndarray) -> np.ndarray:
    """`out[k, s]`: image `k`'s sum over rows `[y0[s], y0[s] + h[k, s])` and
    columns `[x0[s], x0[s] + w[k, s])`, from the canvas table `ii` of images
    `h_img` rows tall (`_integral`)."""
    top = np.arange(h.shape[0])[:, None] * h_img + y0[None, :]
    left = np.broadcast_to(x0[None, :], h.shape)
    return ii[top + h, left + w] - ii[top, left + w] - ii[top + h, left] + ii[top, left]


#: The shifts `ncc` scores, in the order of `_pair_ncc`'s sliding windows:
#: vertical `dy` from 2 to -2, horizontal `dx` from `WIDTH_TOL` to `-WIDTH_TOL`.
_DY = np.repeat(np.arange(2, -3, -1), 2 * WIDTH_TOL + 1)
_DX = np.tile(np.arange(WIDTH_TOL, -WIDTH_TOL - 1, -1), 5)


def _pair_ncc(ta: np.ndarray, ma: np.ndarray, tb: np.ndarray, mb: np.ndarray) -> np.ndarray:
    """For each pair `k`, `ncc` of text `ta[k]` against text `tb[k]` (stacks
    of one shape; masks `ma`, `mb` are top-left rectangles, the texts zero
    outside them): the best Pearson correlation over the overlap, over shifts
    of up to `WIDTH_TOL` px across and 2 px vertically, counting a shift only
    when its overlap is at least 3 px each way; -1 when none counts.

    The pairs go in chunks of similar width, each cut to its own extent.
    Per shift, each pair's overlap is a rectangle: its sums and sums of
    squares come from summed-area tables, and its cross sum is one product
    summed over the chunk."""
    n = ta.shape[0]
    best = np.full(n, -1.0)
    if n == 0:
        return best
    ha, wa = ma.any(axis=2).sum(axis=1), ma.any(axis=1).sum(axis=1)
    hb, wb = mb.any(axis=2).sum(axis=1), mb.any(axis=1).sum(axis=1)
    hh, ww = np.maximum(ha, hb), np.maximum(wa, wb)
    order = np.argsort(ww, kind="stable")
    cut = np.searchsorted(np.cumsum(hh[order] * ww[order]),
                          np.arange(CHUNK_PX, int((hh * ww).sum()), CHUNK_PX))
    for idx in np.split(order, np.unique(cut)):
        if not idx.size:
            continue
        H, W = int(hh[idx].max()), int(ww[idx].max())
        a, b = ta[idx, :H, :W].astype(np.float64), tb[idx, :H, :W].astype(np.float64)
        (ia, ia2), (ib, ib2) = _integral(a), _integral(b)
        ya, yb = np.maximum(_DY, 0), np.maximum(-_DY, 0)
        xa, xb = np.maximum(_DX, 0), np.maximum(-_DX, 0)
        h = np.clip(np.minimum(ha[idx, None] - ya, hb[idx, None] - yb), 0, None)   # (pairs, shifts)
        w = np.clip(np.minimum(wa[idx, None] - xa, wb[idx, None] - xb), 0, None)
        nn = np.maximum(h * w, 1)
        sp, sq = _rect(ia, H, ya, xa, h, w), _rect(ib, H, yb, xb, h, w)
        # Cross sums at every shift: a[i, j] * b[i - dy, j - dx], b zero-padded.
        bp = np.pad(b, ((0, 0), (2, 2), (WIDTH_TOL, WIDTH_TOL)))
        view = np.lib.stride_tricks.sliding_window_view(bp, (H, W), axis=(1, 2))
        spq = np.einsum("kij,kyxij->kyx", a, view).reshape(idx.size, -1)
        cov = spq - sp * sq / nn
        var = ((_rect(ia2, H, ya, xa, h, w) - sp * sp / nn)
               * (_rect(ib2, H, yb, xb, h, w) - sq * sq / nn))
        ok = (h >= 3) & (w >= 3) & (var > 0)
        best[idx] = np.where(ok, cov / np.sqrt(np.where(ok, var, 1.0)), -1.0).max(axis=1)
    return best


def _near(hs: np.ndarray, ws: np.ndarray) -> np.ndarray:
    """`[i, j]`: crops `i` and `j` can show one name whole: heights within
    2 px and widths within `WIDTH_TOL`."""
    return (np.abs(hs[:, None] - hs[None, :]) <= 2) & (np.abs(ws[:, None] - ws[None, :]) <= WIDTH_TOL)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two crops' text, best over shifts of up to
    `WIDTH_TOL` px horizontally and 2 px vertically (`_pair_ncc`); 0 when
    their shapes differ by more than that."""
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > WIDTH_TOL:
        return 0.0
    t, m, _, _ = _texts([a, b])
    return float(_pair_ncc(t[:1], m[:1], t[1:], m[1:])[0])


def whole_matrix(grays: list[np.ndarray]) -> np.ndarray:
    """`out[a, b]`: `ncc` of crops `a` and `b` read whole, for every pair
    `_near` allows; 0 for the rest and the diagonal. One `_pair_ncc` call."""
    m = len(grays)
    out = np.zeros((m, m))
    if m < 2:
        return out
    t, mk, hs, ws = _texts(grays)
    i, j = np.nonzero(np.triu(_near(hs, ws), 1))
    if i.size:
        out[i, j] = out[j, i] = _pair_ncc(t[i], mk[i], t[j], mk[j])
    return out


def fragment_sides(grays: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """`(left, right)`: `left[a, b]` is `ncc` of crop `a` against the
    left-aligned window of crop `b` of `a`'s width, `right[a, b]` against
    the right-aligned one; 0 unless `a` is at least `FRAGMENT_MIN_PX` wide,
    more than `WIDTH_TOL` px narrower than `b`, and within 2 px of its
    height. The windows are cut from one stack of the crops, each window's
    text is its own top-hat (`_tophat`), and all pairs score in one
    `_pair_ncc` call per chunk."""
    m = len(grays)
    left, right = np.zeros((m, m)), np.zeros((m, m))
    if m < 2:
        return left, right
    g, _, hs, ws = _stack(grays)
    ta, ma, _, _ = _texts(grays)
    a, b = np.nonzero((np.abs(hs[:, None] - hs[None, :]) <= 2) & (ws[:, None] >= FRAGMENT_MIN_PX)
                      & (ws[None, :] - ws[:, None] > WIDTH_TOL))
    if not a.size:
        return left, right
    H = int(hs.max())
    W = int(ws[a].max())
    rows = np.arange(H)[None, :, None]
    cols = np.arange(W)[None, None, :]
    wa, ta, ma = ws[a][:, None, None], ta[a][:, :, :W], ma[a][:, :, :W]
    win_mask = (rows < hs[b][:, None, None]) & (cols < wa)
    for side, off in ((left, np.zeros_like(a)), (right, ws[b] - ws[a])):
        x = np.minimum(off[:, None, None] + cols, g.shape[2] - 1)
        win = np.where(win_mask, g[b[:, None, None], rows, x], 0)
        side[a, b] = _pair_ncc(ta, ma, _tophat(win, win_mask), win_mask)
    return left, right


def fragment_matrix(grays: list[np.ndarray]) -> np.ndarray:
    """`out[a, b]`: how well name crop `a` reads as one word of crop `b`'s
    name, the better of its two windows (`fragment_sides`)."""
    left, right = fragment_sides(grays)
    return np.maximum(left, right)


def fragment_ncc(narrow: np.ndarray, wide: np.ndarray) -> float:
    """How well the `narrow` crop reads as one word of the `wide` crop's name
    (`fragment_matrix`); 0 when they cannot be one fragment and one whole."""
    return float(fragment_matrix([narrow, wide])[0, 1])


def join_fragments(clusters: list[list[str]], crops: dict) -> list[list[str]]:
    """One side's clusters with each cluster that reads one word of another
    cluster's name joined to it, members in entry order, largest cluster
    first.

    Two clusters link when a member of one, among their first
    `FRAGMENT_MEMBERS`, matches the left- or right-aligned window of a member
    of the other at `NCC_MIN` (`fragment_sides`): the narrower is one word of
    the wider's name. Clusters join along their links (`connected_components`),
    with one guard. A bridge is a cluster linked to two or more clusters of
    at least `FRAGMENT_SUPPORT` members, names read on two entries or more.
    The guard removes every bridge at once; the recurring clusters left form
    groups along their links, and each recurring bridge counts as a group of
    its own, so no two bridges vouch for each other. A bridge whose links
    reach two or more groups joins them only when each pair of them reads
    one name whole (some member crops within `WIDTH_TOL` reach `NCC_MIN`,
    `whole_matrix`), as when greedy clustering, which compares only first
    members, split one name; or one is a word of the other; or the bridge is
    a word at the left end of a member of one and at the right end of a
    member of the other with less than `FRAGMENT_MIN_PX`, too little for a
    word, beside it in each, as when one name's crops carry a neighbouring
    icon's edge on opposite sides. Otherwise it joins nothing. Removing a
    bridge can change the groups, so the guard repeats until no bridge fails
    it. A junk crop holding one name's word and another's, two such junk
    clusters, or a word two names share at one end so never bridge two
    names however often they recur: the groups' own crops, or the word's
    place in them, must carry the join. The residual, by design: a word two
    names share at opposite ends still bridges them when each crop is less
    than `FRAGMENT_MIN_PX` wider than the word (the other word plus the gap
    beside it), since that reads as one name with an icon's edge on opposite
    sides. A whole name whose two words each
    recur as clusters is such a bridge too and joins neither. A crop read
    once joins the groups it links to, never another crop read once."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    order = {eid: i for i, eid in enumerate(crops)}
    n = len(clusters)
    if n < 2:
        return [sorted(c, key=order.__getitem__) for c in clusters]
    heads = [c[:FRAGMENT_MEMBERS] for c in clusters]
    owner = np.repeat(np.arange(n), [len(h) for h in heads])
    member_of = np.eye(n, dtype=np.int64)[owner]                         # (members, clusters)
    grays = [crops[e]["gray"] for h in heads for e in h]
    other = owner[:, None] != owner[None, :]

    def lift(b: np.ndarray) -> np.ndarray:
        return (member_of.T @ (b & other).astype(np.int64) @ member_of) > 0

    left, right = fragment_sides(grays)
    word_l, word_r = lift(left >= NCC_MIN), lift(right >= NCC_MIN)     # [i, j]: i a word of j
    ws = np.array([g.shape[1] for g in grays])
    rest = ws[None, :] - ws[:, None] < FRAGMENT_MIN_PX                  # no word beside it
    end_l, end_r = lift((left >= NCC_MIN) & rest), lift((right >= NCC_MIN) & rest)
    whole = lift(whole_matrix(grays) >= NCC_MIN).astype(np.int64)
    link = word_l | word_r
    link |= link.T
    big = np.array([len(c) for c in clusters]) >= FRAGMENT_SUPPORT
    live = np.ones(n, bool)
    while True:
        cand = live & ((link & big[None, :] & live[None, :]).sum(axis=1) >= 2)
        if not cand.any():
            break
        keep = big & live & ~cand
        k, group = connected_components(csr_matrix(link & keep[:, None] & keep[None, :]),
                                        directed=False)
        member = np.eye(k, dtype=np.int64)[group] * (big & live)[:, None]  # (clusters, units)
        x = np.flatnonzero(cand)
        reach = (link[x].astype(np.int64) @ member) > 0                    # (bridges, units)
        one = (member.T @ (whole + link) @ member) > 0                     # one name, or a word of it
        at_l = (end_l[x].astype(np.int64) @ member) > 0
        at_r = (end_r[x].astype(np.int64) @ member) > 0
        ok = one[None] | (at_l[:, :, None] & at_r[:, None, :]) | (at_r[:, :, None] & at_l[:, None, :])
        bad = reach[:, :, None] & reach[:, None, :] & ~ok & ~np.eye(k, dtype=bool)[None]
        failed = x[bad.any(axis=(1, 2))]
        if not failed.size:
            break
        live[failed] = False
    edge = link & live[:, None] & live[None, :] & (big[:, None] | big[None, :])
    _, label = connected_components(csr_matrix(edge), directed=False)
    joined: dict[int, list[str]] = {}
    for i, c in enumerate(clusters):
        joined.setdefault(int(label[i]), []).extend(c)
    out = [sorted(c, key=order.__getitem__) for c in joined.values()]
    return sorted(out, key=lambda c: (-len(c), order[c[0]]))


def greedy_clusters(grays: list[np.ndarray]) -> list[list[int]]:
    """Indices of `grays` clustered greedily in order: a crop joins the first
    cluster whose first member it matches (`ncc >= NCC_MIN`), else starts
    one. Each new first member scores every later unclustered crop `_near`
    it in one `_pair_ncc` call, so the calls number the clusters, not the
    crops."""
    if not grays:
        return []
    t, m, hs, ws = _texts(grays)
    near = _near(hs, ws)
    free = np.ones(len(grays), bool)
    clusters = []
    while free.any():
        h = int(np.argmax(free))
        free[h] = False
        cand = np.flatnonzero(free & near[h])
        hit = cand[_pair_ncc(t[np.full(cand.size, h)], m[np.full(cand.size, h)], t[cand], m[cand])
                   >= NCC_MIN] if cand.size else cand
        free[hit] = False
        clusters.append([h, *hit.tolist()])
    return clusters


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
    sides: dict[str, list[list[str]]] = {}
    for team in ("ally", "enemy"):
        ids = [eid for eid, c in crops.items()
               if not c["me"] and c["gray"] is not None and c["team"] == team]
        sides[team] = [[ids[i] for i in cl]
                       for cl in greedy_clusters([crops[e]["gray"] for e in ids])]
    return {"version": KILLFEED_NAME_CLUSTER_VERSION,
            "sides": {t: join_fragments(cl, crops) for t, cl in sides.items()},
            "left_out": {eid: c["reason"] for eid, c in crops.items() if c["reason"]}}
