r"""Which ability each tracked minimap disc draws, and the claim on its caster.

    .\.venv\Scripts\python.exe -m reticle ability-glyphs <session>

Owns [owns:ability-glyph-name]. Stage 3 of `docs/MINIMAP_GLYPH_CHANNEL.md`
(section 2, "The glyph verdict" and "The claim"). Pure over stored rows: the
`ability_glyph` rows the reader wrote, the tracks `adjudication.ability
.disc_tracks` joins from them (`ability-disc-track`), the stored
`tray_kit` spans, the lineup's slots and the versioned null, bank and states
tables in the store. It reads no pixels and decodes nothing.

Per track:

1. **Gates, from other owners' stored answers.** A sample counts (is clean)
   when the reader scored it: the widget was drawn (`widget-drawn`, carried
   by the proposer's frame reason), no stored portrait covers the disc (the
   reader's `portrait`, stage 1's `portrait_cover` over the stored
   `ally_icon` fits and self icon; the stored `team_vision` is stale on the
   variant session, `minimap_glyph`'s docstring), and the disc is not the
   baked map's (`static_like`, `map_shown`)
   [domain:capture/session-pixels-are-not-the-map]. The sample's view is
   `self` while the tray shows the player's kit and `spectator` while it
   shows another's (`tray-kit`, `kit_agents_at`)
   [domain:hud/tray-after-player-death]; a key whose winning texture the
   states table (`ability-states-gamedata-0.2.0`) marks false for that view
   leaves that sample. The reader stores each key's best texture only, so a
   key whose best texture is excluded leaves the sample whole: its other
   textures' scores were not stored. A null view stays in as `view_unknown`,
   and a verdict resting on one stores the surprise
   [domain:minimap/spectator-view-matches-self].
2. **Pooling.** The mean score per key over the clean samples.
3. **The cut, once.** A key names the track when its pooled score exceeds
   its own cut (`keys.<key>.cut`) and its margin over the runner-up exceeds
   the tie margin (`tie_margin.value`), both read from the null table at its
   version (`minimap_glyph.GLYPH_DATA`), never a constant here. The audit
   path reads each key's `audit_cut` and the audit bank cut, the surprise
   path the per-key cut and the full bank cut (stage 2: a full-set search
   must read its bank cut). A refused track keeps one reason: `no_clean_frame`,
   `occluded` (every sample a portrait cover), `view_excluded`, `below_null`,
   `pairwise_tie`, `outside_candidate_set` (the context path refused and the
   audit or surprise path named a kit outside the lineup's set) or `pending`.
4. **Per-ability rules, from facts.** Each cites its fact and runs only where
   its keys are candidates [domain:abilities/ability-rules-are-unique]:
   - Astra: a track whose best key is Astra:X with the placed-inactive star
     texture (`TX_Astra_Minimap_PassiveBlack`, the player's texture answer)
     winning on most clean samples is `Astra:star`, `pending`: the slot it
     turns into is read at the turn, never here
     [domain:abilities/astra-star-placed-then-turned].
   - Omen: Paranoia against Dark Cover by motion and lifetime
     [domain:abilities/omen-paranoia-minimap-icon]
     [domain:abilities/omen-dark-cover-minimap-phases]. The 40 px is read
     on demo captures at a widget scale the fact does not state; the rule
     would apply it as base x widget scale x map zoom and runs only once a
     fact or a dev measurement records that scale. None does, so the rule
     refuses (`scale_unrecorded`) and stores the track's motion and lifetime
     beside the glyph's verdict, which stands alone.
5. **State.** The winning texture and its game-data states are an
   observation of that ability's drawing; no lifecycle phase is inferred
   [domain:minimap/device-dim-on-deactivation].

`map_shown` stands beside the verdict: each row stores the track's
`map_shown` samples and gated count, and a track the gate cut short is never
dropped, since the tracks join gated samples (`disc_tracks`).

**The claim.** Per track whose winning kit is clear (its pooled best exceeds
its cut and its margin over every other agent's best key exceeds the tie
margin), one `identity_claim` on channel `minimap_glyph` naming the kit's
owner, as `smoke_owner` publishes (`ability_glyph_identity`). The kit may be
clear where the slot is not (a tie inside one kit, an Astra star); the claim
then names the agent and the track stays refused on its slot. The lineup
chose the candidates, so each claim `depends_on` the slots of the sides that
admit the agent: it never witnesses the roster. A kit admitted only as a
refused slot's rival never takes the name (`rival_kit`), and a side with a
blind slot refuses every claim (`blind_slot`), as the arbiter rules for
portraits. A track with a clean sample and no clear kit publishes an
abstention with its reason. Audit-path claims (every kit, every rotation)
are built and stored on the row but stay out of the aggregator until the
audit null is shown to hold on rows it was not built on; the null table's
gate 3 has no unlabelled proposer disc yet, so it is not
(`AUDIT_NULL_HOLDS`).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from ..version import (ABILITY_DISC_TRACK_VERSION, ABILITY_GLYPH_NAME_VERSION,
                       ABILITY_GLYPH_VERSION)
from .identity import adjudicate_agent_identity, identity_claim, identity_events

CHANNEL = "minimap_glyph"
AUDIT_CHANNEL = "minimap_glyph_audit"
#: The game-data states table whose texture rows give each texture's states
#: and views (`prototypes/ability_states_gamedata.py`, store `reference/ability-states/`).
STATES_TABLE = ("reference/ability-states", "ability-states-gamedata-0.2.0")
#: Whether audit-path claims enter the aggregator, and why not. The audit null
#: (`glyph-null-table-0.2.2` `banks.audit`) is built on the 63 labelled dev
#: no-ability discs; gate 3's unlabelled proposer discs are unmet
#: (`gate3.unlabelled_proposer_discs` false), so no rows outside its build show it holds.
AUDIT_NULL_HOLDS = (False, "the audit null is measured on the 63 labelled dev no-ability discs only; "
                           "gate 3's unlabelled proposer discs are unmet (null table gate3)")
#: The texture the player named Astra's placed-inactive star (answers.jsonl
#: L367, `state` "placed-inactive star"), filed under Astra:X by the game data.
ASTRA_STAR = ("Astra:X", "TX_Astra_Minimap_PassiveBlack")
OMEN_KEYS = ("Omen:Q", "Omen:E")
#: Why the Omen rule does not run (module docstring).
OMEN_RULE_REFUSAL = ("scale_unrecorded: domain:abilities/omen-paranoia-minimap-icon reads 40-70 px on "
                     "demo captures at a widget scale it does not state, and no dev measurement "
                     "replaces it")
PORTRAIT_COVERS = ("self_portrait", "ally_portrait", "ally_stack")
MAP_GATES = ("static_like", "map_shown")
REFUSALS = ("no_clean_frame", "occluded", "view_excluded", "below_null", "pairwise_tie",
            "outside_candidate_set", "pending")
VIEWS = ("self", "spectator")


def _agent_key(agent: str | None) -> str:
    """An agent name compared across stores: `KAY_O` and `KAY/O` are one."""
    return "".join(ch for ch in (agent or "").lower() if ch.isalnum())


def _texture(provenance: str) -> str:
    """The game texture a bank source draws ('display_icon' for the DisplayIcon)."""
    m = re.search(r"(TX_[A-Za-z0-9_]+)", provenance or "")
    return m.group(1) if m else ("display_icon" if (provenance or "").startswith("icon") else
                                 str(provenance))


# ------------------------------------------------------------------ tables


class VerdictTables:
    """The cuts, the bank's sources and the states table's texture rows."""

    def __init__(self, keys, cuts, audit_cuts, bank_cuts, tie_margin, sources, states,
                 provenance):
        self.keys: list[str] = list(keys)
        self.index = {k: j for j, k in enumerate(self.keys)}
        self.cut = np.array([cuts.get(k, np.nan) for k in self.keys], float)
        self.audit_cut = np.array([audit_cuts.get(k, np.nan) for k in self.keys], float)
        self.bank_cuts = dict(bank_cuts)
        self.tie = float(tie_margin) if tie_margin is not None else np.nan
        #: key -> [texture name per bank source index]
        self.sources = {k: [_texture(p) for p in sources[k]] for k in self.keys}
        self.agent = [k.split(":", 1)[0] for k in self.keys]
        smax = max(len(v) for v in self.sources.values()) if self.sources else 1
        #: (key, source, view) -> the states table marks the texture false there.
        self.view_false = np.zeros((len(self.keys), smax, len(VIEWS)), bool)
        self.states: dict = {}
        for j, k in enumerate(self.keys):
            for s, tex in enumerate(self.sources[k]):
                rows = states.get((_agent_key(self.agent[j]), k.split(":", 1)[1], tex), [])
                self.states[(k, s)] = sorted({(r["state"], r.get("phase")) for r in rows},
                                             key=lambda x: (str(x[0]), str(x[1])))
                for v, view in enumerate(VIEWS):
                    vals = [(r.get("views") or {}).get(view) for r in rows]
                    known = [x for x in vals if x is not None]
                    self.view_false[j, s, v] = bool(known) and not any(known)
        self.provenance = provenance

    @classmethod
    def load(cls, store_root) -> "VerdictTables":
        from ..minimap_glyph import GlyphData
        data = GlyphData.load(store_root)
        sdir, sver = STATES_TABLE
        sp = Path(store_root) / sdir / f"{sver}.jsonl"
        states: dict = {}
        if sp.is_file():
            needle = b'"cue_type": "texture"'
            with open(sp, "rb") as fh:
                for line in fh:
                    if needle not in line:
                        continue
                    r = json.loads(line)
                    if r.get("version") != sver:
                        raise ValueError(f"{sp}: version {r.get('version')!r}, expected {sver!r}")
                    tex = (r.get("cue") or "").rsplit("/", 1)[-1].split(".")[0]
                    states.setdefault((_agent_key(r.get("agent")), r.get("key"), tex), []).append(
                        {"state": r.get("state"), "phase": r.get("phase"), "views": r.get("views")})
        prov = {"glyph": data.provenance,
                "states": {"version": sver, "file": f"{sdir}/{sver}.jsonl",
                           "read": sp.is_file(), "texture_rows": sum(map(len, states.values()))}}
        return cls(data.keys, data.cuts, data.audit_cuts, data.bank_cuts,
                   data.provenance["null"].get("tie_margin"),
                   {k: [p for p, _ in data.sources[k]] for k in data.keys}, states, prov)


# ------------------------------------------------------------------ stored rows, as columns


def load_glyph_rows(path, keys: list[str]) -> dict:
    """The stored `ability_glyph` stream as columns (`pyarrow.json`, one
    thread): `head` (the coverage row), `frames` ({t_ms, reason}), and per
    disc set (`context`, `audit`, `surprise`) its rows' columns with `S`
    (rows x keys, the stored score, NaN where the key was not scored) and
    `SI` (the winning bank source index, -1 where none)."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.json as pj
    path = Path(path)
    with open(path, "rb") as fh:
        head = json.loads(fh.readline() or b"{}")
    fields = [("kind", pa.string()), ("set", pa.string()), ("t_ms", pa.float64()),
              ("frame_idx", pa.int64()), ("disc", pa.string()), ("i", pa.int64()),
              ("cx", pa.float64()), ("cy", pa.float64()), ("r", pa.float64()),
              ("scale", pa.float64()), ("map_shown", pa.float64()),
              ("static_corr", pa.float64()), ("portrait", pa.string()), ("reason", pa.string()),
              ("rests_on", pa.list_(pa.string())),
              ("scores", pa.struct([(k, pa.list_(pa.float64())) for k in keys]))]
    t = pj.read_json(path, read_options=pj.ReadOptions(use_threads=False, block_size=1 << 24),
                     parse_options=pj.ParseOptions(explicit_schema=pa.schema(fields),
                                                   unexpected_field_behavior="ignore"))
    kind = t.column("kind")
    fr = t.filter(pc.equal(kind, "frame"))
    out = {"head": head,
           "frames": {"t_ms": fr.column("t_ms").to_numpy(),
                      "reason": np.asarray(fr.column("reason").fill_null("").to_pylist(), object)}}
    for which in ("context", "audit", "surprise"):
        d = t.filter(pc.and_(pc.equal(kind, "disc"), pc.equal(t.column("set"), which)))
        n = d.num_rows
        rests = d.column("rests_on").combine_chunks()
        offs = np.asarray(rests.offsets.to_numpy(), np.int64)
        vals = np.asarray(rests.values.to_pylist() if len(rests.values) else [], object)
        # The predecessor disc: the first `ability_icon:` id in rests_on.
        pred = np.full(n, "", object)
        if len(vals):
            # The reader stores at most one predecessor disc per row.
            hits = np.flatnonzero(np.char.startswith(vals.astype(str), "ability_icon:"))
            pred[np.repeat(np.arange(n), np.diff(offs))[hits]] = vals[hits]
        S = np.full((n, len(keys)), np.nan)
        SI = np.full((n, len(keys)), -1, np.int64)
        sc = d.column("scores").combine_chunks()
        for j, k in enumerate(keys):
            col = sc.field(k)
            valid = np.asarray(col.is_valid().to_numpy(zero_copy_only=False), bool)
            if not valid.any():
                continue
            lo = np.asarray(col.offsets.to_numpy(), np.int64)
            v = np.asarray(col.values.to_numpy(zero_copy_only=False), float)
            at = lo[:-1][valid]
            S[valid, j] = v[at]
            SI[valid, j] = v[at + 1].astype(np.int64)
        out[which] = {
            "n": n, "t_ms": d.column("t_ms").to_numpy(zero_copy_only=False),
            "frame_idx": d.column("frame_idx").to_numpy(zero_copy_only=False),
            "disc": np.asarray(d.column("disc").to_pylist(), object), "pred": pred,
            "i": d.column("i").to_numpy(zero_copy_only=False),
            "cx": d.column("cx").to_numpy(zero_copy_only=False),
            "cy": d.column("cy").to_numpy(zero_copy_only=False),
            "scale": d.column("scale").to_numpy(zero_copy_only=False),
            "map_shown": d.column("map_shown").fill_null(np.nan).to_numpy(zero_copy_only=False),
            "portrait": np.asarray(d.column("portrait").fill_null("").to_pylist(), object),
            "reason": np.asarray(d.column("reason").fill_null("").to_pylist(), object),
            "S": S, "SI": SI}
    return out


def load_icon_verify(path) -> dict | None:
    """The stored `ability_icon` verify rows as columns: `t_ms` (the sample
    that verified), `of` and `lost`. None where no stream is stored."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.json as pj
    path = Path(path)
    if not path.is_file():
        return None
    vrow = pa.struct([("of", pa.int64()), ("score", pa.float64())])
    schema = pa.schema([("kind", pa.string()), ("t_ms", pa.float64()),
                        ("verify", pa.struct([("of_t_ms", pa.float64()),
                                              ("rows", pa.list_(vrow))]))])
    t = pj.read_json(path, read_options=pj.ReadOptions(use_threads=False, block_size=1 << 24),
                     parse_options=pj.ParseOptions(explicit_schema=schema,
                                                   unexpected_field_behavior="ignore"))
    t = t.filter(pc.and_(pc.equal(t.column("kind"), "frame"), pc.is_valid(t.column("verify"))))
    rows = t.column("verify").combine_chunks().field("rows")
    offs = np.asarray(rows.offsets.to_numpy(), np.int64)
    flat = rows.values
    return {"t_ms": np.repeat(t.column("t_ms").to_numpy(zero_copy_only=False), np.diff(offs)),
            "of": np.asarray(flat.field("of").to_numpy(zero_copy_only=False), np.int64),
            "lost": ~np.asarray(flat.field("score").is_valid().to_numpy(zero_copy_only=False), bool)}


# ------------------------------------------------------------------ the verdict


def frame_views(t_ms, kit_spans, player: str | None) -> tuple[np.ndarray, str | None]:
    """Per instant, 0 (`self`), 1 (`spectator`) or 2 (unknown), from the
    stored tray kit spans (`tray_kit.kit_agents_at`) and the player's agent,
    with the reason every instant is unknown, or None."""
    from .tray_kit import kit_agents_at, same_agent
    t = np.asarray(t_ms, float)
    if kit_spans is None:
        return np.full(len(t), 2, np.int64), "no_tray_kit"
    if player is None:
        return np.full(len(t), 2, np.int64), "no_player_agent"
    who = np.asarray([a or "" for a in kit_agents_at(t, kit_spans)], object).astype(str)
    names, inv = np.unique(who, return_inverse=True)
    code = np.array([2 if not a else (0 if same_agent(a, player) else 1) for a in names], np.int64)
    return (code[inv] if len(t) else np.zeros(0, np.int64)), None


def _pool(track: np.ndarray, ntracks: int, S: np.ndarray, keep: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(mean, count), tracks x keys, of S over the rows `keep` marks per key."""
    k = S.shape[1]
    sums = np.zeros((ntracks, k))
    cnt = np.zeros((ntracks, k))
    np.add.at(sums, track, np.where(keep, S, 0.0))
    np.add.at(cnt, track, keep.astype(float))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, sums / np.where(cnt > 0, cnt, 1.0), np.nan), cnt


def _ranked(pool: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per row: (best index, best value, second index, second value), NaN-safe."""
    p = np.where(np.isnan(pool), -np.inf, pool)
    o = np.argsort(-p, axis=1, kind="stable")
    b, s = o[:, 0], o[:, 1] if p.shape[1] > 1 else o[:, 0]
    r = np.arange(len(p))
    bv, sv = p[r, b], (p[r, s] if p.shape[1] > 1 else np.full(len(p), -np.inf))
    return b, bv, s, sv


def _path_verdicts(tracks_n: int, rows: dict, track_of: np.ndarray, tables: VerdictTables,
                   cut: np.ndarray, bank_cut: float | None) -> dict:
    """The audit or surprise path's pooled verdict per track (every key)."""
    if rows["n"] == 0:
        return {}
    ok = np.isfinite(rows["S"])
    pool, cnt = _pool(track_of, tracks_n, rows["S"], ok)
    has = cnt.sum(1) > 0
    b, bv, s, sv = _ranked(pool)
    margin = bv - np.where(np.isfinite(sv), sv, -1.0)
    out = {}
    for c in np.flatnonzero(has):
        key = tables.keys[b[c]]
        cut_k = cut[b[c]]
        why = None
        if not np.isfinite(cut_k):
            why = "no_cut_for_key"
        elif not bv[c] > cut_k:
            why = "below_null"
        elif bank_cut is not None and not bv[c] > bank_cut:
            why = "below_bank_cut"
        elif not margin[c] > tables.tie:
            why = "pairwise_tie"
        out[int(c)] = {"best": key, "pooled": round(float(bv[c]), 4),
                       "second": tables.keys[s[c]] if np.isfinite(sv[c]) else None,
                       "margin": round(float(margin[c]), 4), "cut": None if not np.isfinite(cut_k)
                       else float(cut_k), "bank_cut": bank_cut,
                       "samples": int(cnt[c].max()), "named": why is None, "reason": why}
    return out


def adjudicate(session_id: str, glyph: dict, verify: dict | None, tables: VerdictTables,
               lineup: dict | None, kit_spans, player: str | None,
               kit_reason: str | None = None, stamps: dict | None = None) -> dict:
    """The session's tracks, verdicts, claims and identity events, from the
    stored rows (`load_glyph_rows`, `load_icon_verify`), the tables, the
    lineup (its slots), the stored tray kit spans and the player's agent."""
    from .ability import disc_tracks
    from .ult_cast import lineup_sides
    t_start = time.perf_counter()
    head = glyph["head"]
    ctx = glyph["context"]
    tr = disc_tracks(session_id, ctx, glyph["frames"], verify)
    tracks, track_of = tr["tracks"], tr["track"]
    T = len(tracks)
    keys = tables.keys
    K = len(keys)

    # Each set's rows join their disc's track.
    order = np.argsort(ctx["disc"].astype(str), kind="stable")
    sorted_ids = ctx["disc"].astype(str)[order]

    def join(rows):
        if rows["n"] == 0:
            return np.zeros(0, np.int64), np.zeros(0, bool)
        ids = rows["disc"].astype(str)
        pos = np.clip(np.searchsorted(sorted_ids, ids), 0, max(len(sorted_ids) - 1, 0))
        ok = sorted_ids[pos] == ids if len(sorted_ids) else np.zeros(len(ids), bool)
        return np.where(ok, track_of[order[pos]], 0), ok

    # Gates and views, per context row.
    reason = ctx["reason"].astype(str)
    scored = reason == ""
    views, view_reason = frame_views(ctx["t_ms"], kit_spans, player)
    vf = tables.view_false
    si = np.clip(ctx["SI"], 0, vf.shape[1] - 1)
    vi = np.clip(views, 0, len(VIEWS) - 1)
    excl = vf[np.arange(K)[None, :], si, vi[:, None]] & (views[:, None] < 2) & (ctx["SI"] >= 0)
    keep = scored[:, None] & np.isfinite(ctx["S"]) & ~excl
    pool, cnt = _pool(track_of, T, ctx["S"], keep)
    clean = np.bincount(track_of, weights=keep.any(1), minlength=T)
    n_scored = np.bincount(track_of, weights=scored, minlength=T)
    n_unknown_view = np.bincount(track_of, weights=scored & (views == 2), minlength=T)
    n_by_view = {v: np.bincount(track_of, weights=scored & (views == j), minlength=T)
                 for j, v in enumerate(VIEWS)}
    n_portrait = np.bincount(track_of, weights=np.isin(reason, PORTRAIT_COVERS), minlength=T)
    n_map = np.bincount(track_of, weights=np.isin(reason, MAP_GATES), minlength=T)
    n_excl = np.bincount(track_of, weights=(scored[:, None] & excl).any(1), minlength=T)
    b, bv, s, sv = _ranked(pool)
    margin = bv - np.where(np.isfinite(sv), sv, -1.0)
    agent_ix = np.array([_agent_key(a) for a in tables.agent], object)
    same_agent = agent_ix[None, :] == agent_ix[b][:, None]
    other = np.where(same_agent | np.isnan(pool), -np.inf, pool).max(1) if T else np.zeros(0)
    agent_margin = bv - np.where(np.isfinite(other), other, -1.0)
    cut_b = tables.cut[b] if T else np.zeros(0)

    # The audit and surprise paths, per track.
    a_track, a_ok = join(glyph["audit"])
    s_track, s_ok = join(glyph["surprise"])

    def sub(rows, okm):
        return {k: (v[okm] if isinstance(v, np.ndarray) and len(v) == rows["n"] else v)
                for k, v in rows.items()} | {"n": int(okm.sum())}
    audit = _path_verdicts(T, sub(glyph["audit"], a_ok), a_track[a_ok], tables, tables.audit_cut,
                           tables.bank_cuts.get("audit")) if glyph["audit"]["n"] else {}
    surprise = _path_verdicts(T, sub(glyph["surprise"], s_ok), s_track[s_ok], tables, tables.cut,
                              tables.bank_cuts.get("full")) if glyph["surprise"]["n"] else {}

    # The candidate set, its sides and slots.
    cands = head.get("candidates") or {}
    sides = lineup_sides(lineup, session_id) if lineup else None
    blind = sum(int((v or {}).get("blind") or 0) for v in cands.values())
    admit: dict = {}
    for side, v in cands.items():
        for a, how in ((v or {}).get("agents") or {}).items():
            admit.setdefault(_agent_key(a), []).append((side, a, how))
    lineup_stamp = head.get("candidates_from")

    # map_shown beside the verdict, per track.
    ms_split = np.split(ctx["map_shown"][np.lexsort((ctx["i"], ctx["t_ms"], track_of))],
                        np.flatnonzero(np.diff(np.sort(track_of))) + 1) if len(track_of) else []
    # The best key's winning texture per track: the most frequent bank source
    # over its clean samples, with its count and share.
    smax = vf.shape[1]
    if len(track_of):
        rb = b[track_of]
        src = ctx["SI"][np.arange(len(track_of)), rb]
        on = keep[np.arange(len(track_of)), rb] & (src >= 0)
        src_n = np.bincount(track_of[on] * smax + np.clip(src[on], 0, smax - 1),
                            minlength=T * smax).reshape(T, smax)
    else:
        src_n = np.zeros((T, smax), np.int64)
    src_mode = src_n.argmax(1)

    rows, claims, audit_claims = [], [], []
    for c, trk in enumerate(tracks):
        k = int(b[c])
        key = keys[k] if np.isfinite(bv[c]) else None
        cut_k = float(cut_b[c]) if np.isfinite(cut_b[c]) else None
        surprises = list(trk["surprises"])
        rule = "cut"
        state = None
        reason_c = None
        named_key = None
        kit_clear = False
        if n_scored[c] == 0:
            n_all = trk["fixes"]
            reason_c = "occluded" if n_portrait[c] == n_all and n_all else "no_clean_frame"
        elif clean[c] == 0:
            reason_c = "view_excluded"
        else:
            if cut_k is None or not bv[c] > cut_k:
                reason_c = "below_null"
            else:
                kit_clear = bool(agent_margin[c] > tables.tie)
                if not margin[c] > tables.tie:
                    reason_c = "pairwise_tie"
                else:
                    named_key = key
            if n_unknown_view[c] > 0:
                surprises.append("view_unknown")
        # The winning texture and its states (an observation).
        tex = None
        n_src = int(src_n[c].sum())
        if key is not None and n_src:
            s_mode = int(src_mode[c])
            tex = tables.sources[key][s_mode] if s_mode < len(tables.sources[key]) else None
            state = {"texture": tex, "source": s_mode,
                     "states": [list(x) for x in tables.states.get((key, s_mode), [])],
                     "samples": n_src, "share": round(float(src_n[c, s_mode] / n_src), 4)}
        # Astra's placed star.
        if key == ASTRA_STAR[0] and tex == ASTRA_STAR[1] and reason_c in (None, "pairwise_tie"):
            rule, named_key, reason_c = "astra_star_pending", None, "pending"
            kit_clear = bool(bv[c] > (cut_k if cut_k is not None else np.inf)
                             and agent_margin[c] > tables.tie)
        omen = None
        if key in OMEN_KEYS and _agent_key("Omen") in admit:
            omen = {"rule": "omen_motion_lifetime", "applied": False, "reason": OMEN_RULE_REFUSAL,
                    "first_second_disp_base": trk["first_second"]["disp_base"],
                    "lifetime_ms": trk["lifetime_ms"], "end": trk["end"],
                    "pooled": {x: (None if not np.isfinite(pool[c, tables.index[x]])
                                   else round(float(pool[c, tables.index[x]]), 4)) for x in OMEN_KEYS}}
        # outside_candidate_set: the context path refused and a full-set path named.
        alt = None
        if reason_c in ("below_null", "no_clean_frame", "view_excluded"):
            for path, got in (("surprise", surprise.get(c)), ("audit", audit.get(c))):
                if got and got["named"] and _agent_key(got["best"].split(":")[0]) not in admit:
                    alt = {"path": path, **got}
                    break
            if alt is not None and reason_c == "below_null":
                reason_c = "outside_candidate_set"
        ag = key.split(":")[0] if key else None
        how = admit.get(_agent_key(ag), []) if ag else []
        depends = sorted({s for side, _, _ in how for s in ((sides or {}).get(side) or {}).get("slots", [])})
        claim_agent, claim_why = None, None
        if kit_clear and ag:
            if blind:
                claim_why = "blind_slot"
            elif not how:
                claim_why = "outside_candidate_set"
            elif all(h == "rival" for _, _, h in how):
                claim_why = "rival_kit"
            else:
                claim_agent = next(a for _, a, h in how if h == "named")
        elif clean[c] > 0:
            claim_why = reason_c or "kit_unclear"
            if reason_c is None:
                claim_why = "agent_margin_below_tie"
        ev = {"key": key, "pooled": None if key is None else round(float(bv[c]), 4),
              "cut": cut_k, "margin": round(float(margin[c]), 4) if np.isfinite(margin[c]) else None,
              "agent_margin": round(float(agent_margin[c]), 4) if np.isfinite(agent_margin[c]) else None,
              "tie_margin": tables.tie, "rule": rule, "clean_samples": int(clean[c])}
        if clean[c] > 0:
            claims.append(identity_claim(trk["entity_id"], claim_agent, channel=CHANNEL,
                                         observed_at_ms=trk["birth_ms"],
                                         reason=None if claim_agent else claim_why,
                                         source_version=ABILITY_GLYPH_NAME_VERSION,
                                         depends_on=depends or None, evidence=ev))
        a_got = audit.get(c)
        a_claim = None
        if a_got and a_got["named"]:
            a_claim = identity_claim(trk["entity_id"], a_got["best"].split(":")[0],
                                     channel=AUDIT_CHANNEL, observed_at_ms=trk["birth_ms"],
                                     source_version=ABILITY_GLYPH_NAME_VERSION,
                                     evidence={k2: a_got[k2] for k2 in ("best", "pooled", "margin", "cut",
                                                                        "bank_cut")})
            audit_claims.append(a_claim)
        alts = {keys[j]: round(float(pool[c, j]), 4) for j in np.argsort(-np.nan_to_num(pool[c], nan=-9))[:8]
                if np.isfinite(pool[c, j])} if clean[c] else {}
        msv = ms_split[c] if c < len(ms_split) else np.zeros(0)
        rows.append({
            "kind": "verdict", "track": trk["track"], "entity_id": trk["entity_id"],
            "birth_ms": trk["birth_ms"], "last_ms": trk["last_ms"],
            "ability": None if named_key is None else {
                "agent": named_key.split(":")[0], "slot": named_key.split(":")[1], "key": named_key},
            "pending": "Astra:star" if rule == "astra_star_pending" else None,
            "reason": reason_c, "rule": rule, "state": state,
            "best": key, "pooled": ev["pooled"], "second": keys[int(s[c])] if np.isfinite(sv[c]) else None,
            "margin": ev["margin"], "agent_margin": ev["agent_margin"], "cut": cut_k,
            "tie_margin": tables.tie, "alternatives": alts,
            "samples": {"fixes": trk["fixes"], "scored": int(n_scored[c]), "clean": int(clean[c]),
                        "portrait_cover": int(n_portrait[c]), "map_gated": int(n_map[c]),
                        "view_excluded": int(n_excl[c]), "view_unknown": int(n_unknown_view[c]),
                        **{f"view_{v}": int(n_by_view[v][c]) for v in VIEWS}},
            "map_shown": {"n": int(np.isfinite(msv).sum()),
                          "max": None if not np.isfinite(msv).any() else round(float(np.nanmax(msv)), 4),
                          "gated": int(n_map[c])},
            "omen_rule": omen, "outside": alt,
            "audit": a_got, "audit_claim": a_claim, "surprise": surprise.get(c),
            "kit_clear": kit_clear, "claim_reason": claim_why,
            "depends_on": depends, "surprises": surprises,
            "rests_on": [x for x in (lineup_stamp,) if x]})
    verdicts = {v["entity_id"]: v for v in adjudicate_agent_identity(claims)}
    events = []
    for r in rows:
        v = verdicts.get(r["entity_id"])
        r["agent"] = v["agent"] if v and v["status"] == "resolved" else None
        r["identity_status"] = v["status"] if v else None
        if v:
            events += identity_events([v], session_id, r["birth_ms"])
    refused: dict = {}
    for r in rows:
        if r["reason"]:
            refused[r["reason"]] = refused.get(r["reason"], 0) + 1
    clean_rows = [r for r in rows if r["samples"]["clean"]]
    a_rows = [r for r in rows if r["audit"]]
    agree = [r for r in a_rows if r["audit"]["named"] and r["ability"]
             and r["audit"]["best"] == r["ability"]["key"]]
    wall = time.perf_counter() - t_start
    common = {"session_id": session_id, "ability_glyph_name_version": ABILITY_GLYPH_NAME_VERSION}
    cover = {**common, "kind": "coverage",
             "tracks": T, "with_clean_sample": len(clean_rows),
             "named": sum(r["ability"] is not None for r in rows),
             "pending": sum(r["pending"] is not None for r in rows),
             "kit_clear": sum(r["kit_clear"] for r in rows),
             "claims": len(claims), "claims_named": sum(c["agent"] is not None for c in claims),
             "agents_named": sum(r["agent"] is not None for r in rows),
             "refused": dict(sorted(refused.items())),
             "refused_with_clean_sample": dict(sorted(
                 {k: sum(1 for r in clean_rows if r["reason"] == k) for k in REFUSALS
                  if any(r["reason"] == k for r in clean_rows)}.items())),
             "audit": {"tracks": len(a_rows), "named": sum(1 for r in a_rows if r["audit"]["named"]),
                       "agree_with_context": len(agree),
                       "claims_built": len(audit_claims),
                       "in_aggregator": AUDIT_NULL_HOLDS[0], "why": AUDIT_NULL_HOLDS[1]},
             "views": {"reason": view_reason or kit_reason,
                       "player_agent": player},
             "rules": {"cut": "pooled > keys.<key>.cut and margin > tie_margin.value (null table)",
                       "astra_star": f"{ASTRA_STAR[0]} with {ASTRA_STAR[1]} -> Astra:star pending",
                       "omen": OMEN_RULE_REFUSAL},
             "blind_slots": blind,
             "candidates": cands, "candidates_from": lineup_stamp,
             "tables": tables.provenance,
             "inputs": {"ability_glyph": head.get("ability_glyph_version"),
                        "glyph_bank": head.get("glyph_bank"),
                        "ability_disc_track": ABILITY_DISC_TRACK_VERSION,
                        "null_table": tables.provenance["glyph"]["null"]["version"],
                        "states_table": tables.provenance["states"]["version"],
                        **(stamps or {})},
             "wall_s": round(wall, 3)}
    track_cover = {"session_id": session_id, "ability_disc_track_version": ABILITY_DISC_TRACK_VERSION,
                   "kind": "coverage", "tracks": T,
                   "inputs": {"ability_glyph": head.get("ability_glyph_version"),
                              "glyph_bank": head.get("glyph_bank"),
                              "ability_icon": head.get("ability_icon_version")},
                   "ends": _count(t["end"].split(":")[0] for t in tracks),
                   "onsets": _count(t["onset"].split(":")[0] for t in tracks),
                   "jumps": sum(bool(t["jumps"]) for t in tracks),
                   "single_fix": sum(t["fixes"] == 1 for t in tracks)}
    return {"tracks": [track_cover] + [{"session_id": session_id,
                                        "ability_disc_track_version": ABILITY_DISC_TRACK_VERSION, **t}
                                       for t in tracks],
            "rows": [cover] + [{**common, **r} for r in rows],
            "events": events, "claims": claims, "audit_claims": audit_claims}


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def stale_reason(head: dict) -> str | None:
    """Why a stored `ability_glyph` stream cannot be adjudicated, or None:
    the verdict applies the null table at the code's version to stored scores,
    which holds only where the reader scored under the same bank and tables."""
    from ..minimap_glyph import GLYPH_BANK_STAMP
    if head.get("ability_glyph_version") != ABILITY_GLYPH_VERSION:
        return f"ability_glyph is {head.get('ability_glyph_version')}, current {ABILITY_GLYPH_VERSION}"
    if head.get("glyph_bank") != GLYPH_BANK_STAMP:
        return f"ability_glyph was scored on {head.get('glyph_bank')}, current {GLYPH_BANK_STAMP}"
    return None
