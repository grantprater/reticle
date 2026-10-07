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
   `occluded` (every sample a portrait cover), `view_excluded`,
   `no_cut_for_key`, `below_null`, `pairwise_tie`, `not_drawn_per_answer`,
   `outside_candidate_set` (the context path refused and the audit or surprise
   path named a kit outside the lineup's set) or `pending`.
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
   - The player's drawing answers: a key the player answered draws
     `nothing` or only a `shape` on the minimap
     (`labels/minimap_glyph_questions/answers.jsonl`, the sure `visibility`
     rows, `player_drawing`: the `drawing` view, else the teammate's view,
     last row wins; where the key's agent is the recording player's own
     agent, the lineup's self slot, the player's `self` view comes first)
     draws no glyph, so a track whose best key is one never
     names it, nor its kit: it refuses `not_drawn_per_answer`, stores the
     answer row and the appearance facts on the ability's subject, and
     stores the surprise `fact_contradicts:<key>`. The runner-up is not
     promoted: a disc that a non-drawing key's texture fits best is unknown.
     A texture the player named with the state it draws (a sure `texture`
     row with `state`, as Astra's placed-inactive star) is drawn whatever its
     key's visibility answer says; the texture answer is the narrower one.
     The rule runs on the context, audit and surprise paths alike, after
     the cut (a `below_null` track keeps that reason). `plan` compares the
     answers the rule reads by a digest of the ruled-out keys and the
     texture states (`drawing_answers_stamp`), so a new answer that moves
     either restales the verdict and an unrelated one does not.
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
refused slot's rival never takes the name (`rival_kit`). A blind slot on a
side that admits the agent refuses the claim (`blind_slot`), as the arbiter
rules for portraits; when no side admits the agent, a blind slot on any side
refuses it, since that slot may hold the agent. A blind slot on a side that
does not admit the agent changes nothing: the claim names an agent, not a
side, and a mirror pick on the blind side would be the same agent. A track with a clean sample and no clear kit publishes an
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

from ..agent_names import agent_key
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
REFUSALS = ("no_clean_frame", "occluded", "view_excluded", "no_cut_for_key", "below_null",
            "pairwise_tie", "not_drawn_per_answer", "outside_candidate_set", "pending")
VIEWS = ("self", "spectator")
#: The player's answers on what each key draws on the minimap (`ask_minimap_glyphs`).
DRAWING_ANSWERS = "labels/minimap_glyph_questions/answers.jsonl"
#: The drawing answers that rule an icon out.
NO_ICON = frozenset({"nothing", "shape"})
#: `other` answers whose words rule an icon out ("nothing, then the green/blue
#: tint ... where gekko can pick it up").
OTHER_NO_ICON = frozenset({"visibility:Gekko:C:ally", "visibility:Gekko:E:ally"})
NOT_DRAWN = "not_drawn_per_answer"


def player_drawing(rows: list[dict], own: bool = False) -> dict:
    """(agent, slot) -> (answer, other, key) from the player's sure visibility
    answers: the `drawing` key, else the `ally` key (the view facts make the
    teammate's view the drawing; `ask_minimap_glyphs.answered`), last row wins.
    With `own` (the caster is the recording player's own agent), the `self`
    key comes first: the player answered how their own ability draws on their
    own minimap, which the teammate's view does not ask."""
    last = {}
    for r in rows:
        last[r["key"]] = r
    rank = {"self": 0, "drawing": 1, "ally": 2} if own else {"drawing": 0, "ally": 1}
    best: dict = {}
    for k, r in last.items():
        parts = k.split(":")
        if parts[0] != "visibility" or len(parts) != 4 or r.get("unsure"):
            continue
        _, agent, slot, view = parts
        if view in rank and ((agent, slot) not in best or rank[view] < best[(agent, slot)][0]):
            best[(agent, slot)] = (rank[view], (r.get("answer"), r.get("other"), k))
    return {a: v for a, (_, v) in best.items()}


def icon_ruled_out(answer: tuple | None) -> bool:
    """Whether a `player_drawing` answer rules an icon out."""
    return answer is not None and (answer[0] in NO_ICON or answer[2] in OTHER_NO_ICON)


def _read_answers(store_root) -> tuple[list[dict], dict, bytes] | None:
    """(rows, key -> the line of its last row, raw bytes) of `DRAWING_ANSWERS`,
    or None where the file is absent."""
    p = Path(store_root) / DRAWING_ANSWERS
    if not p.is_file():
        return None
    raw = p.read_bytes()
    rows, line_of = [], {}
    for n, ln in enumerate(raw.decode("utf-8").splitlines(), 1):
        if ln.strip():
            r = json.loads(ln)
            rows.append(r)
            line_of[r["key"]] = n
    return rows, line_of, raw


def _drawn_textures(rows: list[dict]) -> dict:
    """(key, texture) -> the last sure texture row naming the state it draws."""
    last = {}
    for r in rows:
        last[r["key"]] = r
    return {(r["answer"], k.split(":", 1)[1]): r for k, r in last.items()
            if r.get("kind") == "texture" and not r.get("unsure") and r.get("state")
            and r.get("answer")}


def _answers_digest(rows: list[dict]) -> str:
    """The stamp of what the verdict reads from the answers: the answers that
    rule an icon out, in either view order, and the texture state answers.
    An answer that moves neither leaves it unchanged."""
    import hashlib
    ruled = sorted({(order, a, s, v[0], v[1], v[2])
                    for order, own in (("other", False), ("own", True))
                    for (a, s), v in player_drawing(rows, own).items() if icon_ruled_out(v)},
                   key=lambda x: tuple(map(str, x)))
    tex = sorted((k, t, r["state"]) for (k, t), r in _drawn_textures(rows).items())
    blob = json.dumps({"ruled_out": ruled, "texture_states": tex}, sort_keys=True).encode("utf-8")
    return f"drawing-answers#{hashlib.sha256(blob).hexdigest()[:16]}"


def drawing_answers_stamp(store_root) -> str:
    """The stamp `plan` compares for the drawing answers the verdict read
    (`_answers_digest`), `no_rows` where the file is absent."""
    got = _read_answers(store_root) if store_root is not None else None
    return _answers_digest(got[0]) if got is not None else "no_rows"


def catalogue_names(store_root) -> dict:
    """(agent key, slot) -> the catalogue's display name (`reference/abilities.json`)."""
    cat_p = Path(store_root) / "reference" / "abilities.json"
    cat = json.loads(cat_p.read_text(encoding="utf-8")).get("agents", {}) if cat_p.is_file() else {}
    return {(agent_key(a), ab.get("key")): ab.get("name")
            for a, v in cat.items() for ab in (v or {}).get("abilities", [])}


def load_drawing_answers(store_root, keys: list[str], names: dict | None = None) -> dict:
    """The player's drawing answers the verdict reads, from `DRAWING_ANSWERS`:
    `not_drawn` {key: {answer, other, answer_key, row, domain_subject,
    domain_facts}} for each bank key whose answer rules an icon out when
    another player casts it, `not_drawn_own` the same when the recording
    player casts it (`player_drawing` with `own`), `drawn_textures`
    {(key, texture): {state, row}} for each sure texture answer naming the
    state the texture draws, and `provenance`, whose `stamp` is the one
    `plan` compares (`drawing_answers_stamp`). `names` is
    `catalogue_names(store_root)`, read here when not given."""
    import hashlib

    from ..domain import by_subject
    from ..domain import load as load_facts
    got = _read_answers(store_root)
    if got is None:
        return {"not_drawn": {}, "not_drawn_own": {}, "drawn_textures": {},
                "provenance": {"file": DRAWING_ANSWERS, "read": False, "stamp": "no_rows"}}
    rows, line_of, raw = got
    names = catalogue_names(store_root) if names is None else names
    facts = load_facts()

    def ruled_out(drawing: dict) -> dict:
        out = {}
        for k in keys:
            agent, slot = k.split(":", 1)
            hit = next((v for (a, s), v in drawing.items()
                        if s == slot and agent_key(a) == agent_key(agent)), None)
            if not icon_ruled_out(hit):
                continue
            name = names.get((agent_key(agent), slot))
            subject = f"{agent.lower()}:{name.lower()}" if name else None
            cite = sorted(f"domain:{f.key}" for f in by_subject(facts, subject).values()
                          if f.kind == "appearance") if subject else []
            out[k] = {"answer": hit[0], "other": hit[1], "answer_key": hit[2],
                      "row": f"{DRAWING_ANSWERS}#L{line_of[hit[2]]}",
                      "domain_subject": subject, "domain_facts": cite}
        return out

    not_drawn = ruled_out(player_drawing(rows))
    not_drawn_own = ruled_out(player_drawing(rows, own=True))
    drawn_textures = {kt: {"state": r["state"], "row": f"{DRAWING_ANSWERS}#L{line_of[r['key']]}"}
                      for kt, r in _drawn_textures(rows).items()}
    return {"not_drawn": not_drawn, "not_drawn_own": not_drawn_own,
            "drawn_textures": drawn_textures,
            "provenance": {"file": DRAWING_ANSWERS, "read": True, "rows": len(rows),
                           "sha256": hashlib.sha256(raw).hexdigest()[:16],
                           "stamp": _answers_digest(rows),
                           "not_drawn_keys": len(not_drawn),
                           "not_drawn_own_keys": len(not_drawn_own),
                           "drawn_textures": len(drawn_textures)}}


def _texture(provenance: str) -> str:
    """The game texture a bank source draws ('display_icon' for the DisplayIcon)."""
    m = re.search(r"(TX_[A-Za-z0-9_]+)", provenance or "")
    return m.group(1) if m else ("display_icon" if (provenance or "").startswith("icon") else
                                 str(provenance))


# ------------------------------------------------------------------ tables


class VerdictTables:
    """The cuts, the bank's sources and the states table's texture rows."""

    def __init__(self, keys, cuts, audit_cuts, bank_cuts, tie_margin, sources, states,
                 provenance, drawing: dict | None = None, names: dict | None = None):
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
                rows = states.get((agent_key(self.agent[j]), k.split(":", 1)[1], tex), [])
                self.states[(k, s)] = sorted({(r["state"], r.get("phase")) for r in rows},
                                             key=lambda x: (str(x[0]), str(x[1])))
                for v, view in enumerate(VIEWS):
                    vals = [(r.get("views") or {}).get(view) for r in rows]
                    known = [x for x in vals if x is not None]
                    self.view_false[j, s, v] = bool(known) and not any(known)
        self.provenance = provenance
        drawing = drawing or {}
        #: key -> the answer that rules its icon out when another player
        #: casts it (`load_drawing_answers`).
        self.not_drawn: dict = dict(drawing.get("not_drawn") or {})
        #: key -> the same when the recording player casts it; the other
        #: players' map where a caller gives none.
        self.not_drawn_own: dict = dict(drawing.get("not_drawn_own", self.not_drawn) or {})
        #: (key, texture) -> the texture answer naming the state it draws.
        self.drawn_textures: dict = dict(drawing.get("drawn_textures") or {})
        #: key -> the catalogue's display name.
        self.names: dict = dict(names or {})

    def not_drawn_for(self, key: str | None, texture: str | None,
                      own: bool = False) -> dict | None:
        """The answer that rules `key`'s icon out, unless the player named
        `texture` with the state it draws; None where the key is drawn.
        `own`: the key's agent is the recording player's own agent, whose
        `self` view answer comes first (`player_drawing`)."""
        table = self.not_drawn_own if own else self.not_drawn
        if key is None or key not in table or (key, texture) in self.drawn_textures:
            return None
        return table[key]

    def may_not_draw(self, key: str | None) -> bool:
        """Whether either view order rules `key`'s icon out."""
        return key is not None and (key in self.not_drawn or key in self.not_drawn_own)

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
                    states.setdefault((agent_key(r.get("agent")), r.get("key"), tex), []).append(
                        {"state": r.get("state"), "phase": r.get("phase"), "views": r.get("views")})
        by = catalogue_names(store_root)
        drawing = load_drawing_answers(store_root, data.keys, names=by)
        names = {k: by.get((agent_key(k.split(":", 1)[0]), k.split(":", 1)[1])) for k in data.keys}
        prov = {"glyph": data.provenance,
                "states": {"version": sver, "file": f"{sdir}/{sver}.jsonl",
                           "read": sp.is_file(), "texture_rows": sum(map(len, states.values()))},
                "drawing_answers": drawing["provenance"]}
        return cls(data.keys, data.cuts, data.audit_cuts, data.bank_cuts,
                   data.provenance["null"].get("tie_margin"),
                   {k: [p for p, _ in data.sources[k]] for k in data.keys}, states, prov,
                   drawing=drawing, names=names)


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
    from ..agent_names import same_agent
    from .tray_kit import kit_agents_at
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
                   cut: np.ndarray, bank_cut: float | None, player: str | None = None) -> dict:
    """The audit or surprise path's pooled verdict per track (every key);
    `player` is the recording player's agent, whose own keys read the `self`
    drawing answer first."""
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
        why, nd = None, None
        if not np.isfinite(cut_k):
            why = "no_cut_for_key"
        elif not bv[c] > cut_k:
            why = "below_null"
        elif bank_cut is not None and not bv[c] > bank_cut:
            why = "below_bank_cut"
        if why is None and tables.may_not_draw(key):
            si = rows["SI"][(track_of == c) & ok[:, b[c]], b[c]]
            si = si[si >= 0]
            tex = None
            if len(si):
                m = int(np.bincount(si).argmax())
                tex = tables.sources[key][m] if m < len(tables.sources[key]) else None
            nd = tables.not_drawn_for(key, tex, _is_player(key, player))
            if nd is not None:
                why = NOT_DRAWN
        if why is None and not margin[c] > tables.tie:
            why = "pairwise_tie"
        out[int(c)] = {"best": key, "pooled": round(float(bv[c]), 4),
                       "second": tables.keys[s[c]] if np.isfinite(sv[c]) else None,
                       "margin": round(float(margin[c]), 4), "cut": None if not np.isfinite(cut_k)
                       else float(cut_k), "bank_cut": bank_cut,
                       "samples": int(cnt[c].max()), "named": why is None, "reason": why,
                       **({"not_drawn": nd} if nd is not None else {})}
    return out


def _is_player(key: str | None, player: str | None) -> bool:
    """Whether `key`'s agent is the recording player's agent (`player`, the
    lineup's self slot): the caster the player's `self` answer describes."""
    if key is None or player is None:
        return False
    from ..agent_names import same_agent
    return bool(same_agent(key.split(":", 1)[0], player))


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
    agent_ix = np.array([agent_key(a) for a in tables.agent], object)
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
                           tables.bank_cuts.get("audit"), player) if glyph["audit"]["n"] else {}
    surprise = _path_verdicts(T, sub(glyph["surprise"], s_ok), s_track[s_ok], tables, tables.cut,
                              tables.bank_cuts.get("full"), player) if glyph["surprise"]["n"] else {}

    # The candidate set, its sides and slots.
    cands = head.get("candidates") or {}
    sides = lineup_sides(lineup, session_id) if lineup else None
    blind_by_side = {side: int((v or {}).get("blind") or 0) for side, v in cands.items()}
    blind = sum(blind_by_side.values())
    admit: dict = {}
    for side, v in cands.items():
        for a, how in ((v or {}).get("agents") or {}).items():
            admit.setdefault(agent_key(a), []).append((side, a, how))
    lineup_stamp = head.get("candidates_from")
    # What every row rests on: the lineup that chose the candidates, the
    # stored tray kit that gave the views (where it did), and the policy and
    # null tables the reader scored under and the verdict cuts with.
    glyph_prov = tables.provenance.get("glyph") or {}
    kit_stamp = (stamps or {}).get("tray_kit")
    rests = [x for x in (lineup_stamp,
                         f"tray_kit#{kit_stamp}" if kit_spans is not None and kit_stamp else None,
                         (glyph_prov.get("policy") or {}).get("version"),
                         (glyph_prov.get("null") or {}).get("version")) if x]

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
            if cut_k is None:
                reason_c = "no_cut_for_key"
            elif not bv[c] > cut_k:
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
        # The player's drawing answer, after the cut and the Astra rule.
        not_drawn = None
        if reason_c in (None, "pairwise_tie") or kit_clear:
            not_drawn = tables.not_drawn_for(key, tex, _is_player(key, player))
            if not_drawn is not None:
                if reason_c in (None, "pairwise_tie"):
                    reason_c = NOT_DRAWN
                named_key, kit_clear, rule = None, False, NOT_DRAWN
                surprises.append(f"fact_contradicts:{key}")
        omen = None
        if key in OMEN_KEYS and agent_key("Omen") in admit:
            omen = {"rule": "omen_motion_lifetime", "applied": False, "reason": OMEN_RULE_REFUSAL,
                    "first_second_disp_base": trk["first_second"]["disp_base"],
                    "lifetime_ms": trk["lifetime_ms"], "end": trk["end"],
                    "pooled": {x: (None if not np.isfinite(pool[c, tables.index[x]])
                                   else round(float(pool[c, tables.index[x]]), 4)) for x in OMEN_KEYS}}
        # outside_candidate_set: the context path refused and a full-set path named.
        alt = None
        if reason_c in ("below_null", "no_clean_frame", "view_excluded"):
            for path, got in (("surprise", surprise.get(c)), ("audit", audit.get(c))):
                if got and got["named"] and agent_key(got["best"].split(":")[0]) not in admit:
                    alt = {"path": path, **got}
                    break
            if alt is not None and reason_c == "below_null":
                reason_c = "outside_candidate_set"
        ag = key.split(":")[0] if key else None
        how = admit.get(agent_key(ag), []) if ag else []
        depends = sorted({s for side, _, _ in how for s in ((sides or {}).get(side) or {}).get("slots", [])})
        claim_agent, claim_why = None, None
        if kit_clear and ag:
            if any(blind_by_side.get(side) for side, _, _ in how) or (not how and blind):
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
                "agent": named_key.split(":")[0], "slot": named_key.split(":")[1], "key": named_key,
                "name": tables.names.get(named_key)},
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
            "omen_rule": omen, "outside": alt, "not_drawn": not_drawn,
            "audit": a_got, "audit_claim": a_claim, "surprise": surprise.get(c),
            "kit_clear": kit_clear, "claim_reason": claim_why,
            "depends_on": depends, "surprises": surprises,
            "rests_on": rests + ([not_drawn["row"]] if not_drawn else [])})
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
                       "omen": OMEN_RULE_REFUSAL,
                       "not_drawn": "a best key the player answered draws nothing or a shape refuses "
                                    "not_drawn_per_answer and withholds its kit claim, unless its "
                                    "winning texture has a state answer"},
             "blind_slots": blind, "blind_by_side": blind_by_side,
             "not_drawn": {"refused": sum(r["reason"] == NOT_DRAWN for r in rows),
                           "rows": sum(bool(r["not_drawn"]) for r in rows),
                           "keys": _count(r["best"] for r in rows if r["not_drawn"]),
                           "answers": tables.provenance.get("drawing_answers")},
             "candidates": cands, "candidates_from": lineup_stamp,
             "tables": tables.provenance,
             "inputs": {"ability_glyph": head.get("ability_glyph_version"),
                        "glyph_bank": head.get("glyph_bank"),
                        "ability_disc_track": ABILITY_DISC_TRACK_VERSION,
                        "null_table": tables.provenance["glyph"]["null"]["version"],
                        "states_table": tables.provenance["states"]["version"],
                        "drawing_answers": (tables.provenance.get("drawing_answers")
                                            or {}).get("stamp"),
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


def session_adjudication(store, sid: str) -> dict:
    """`adjudicate` over one session's stored rows, as `reticle ability-glyphs`
    runs it: `{"result": ...}`, or `{"skipped": why}` where the stored
    `ability_glyph` rows are missing or stale. Writes nothing."""
    from ..lineup import load_lineup
    from .tray_kit import stored_kit_witness
    from .ult_cast import player_agent
    from ..input_stamps import head_row
    path = store.events_path("ability_glyph", sid)
    head = head_row(store, "ability_glyph", sid)
    if head is None:
        return {"skipped": f"no ability_glyph rows -- run `reticle scan {sid} --only ability "
                           f"--from cache`"}
    why = stale_reason(head)
    if why:
        return {"skipped": why}
    tables = VerdictTables.load(store.root)
    glyph = load_glyph_rows(path, tables.keys)
    verify = load_icon_verify(store.events_path("ability_icon", sid))
    lineup = load_lineup(sid, store.root)
    player = player_agent(lineup, sid)
    kit = stored_kit_witness(store.read_events("tray_kit", sid), agent=player)
    res = adjudicate(sid, glyph, verify, tables, lineup,
                     kit["spans"] if kit["reason"] is None else None, player,
                     kit_reason=kit["reason"],
                     stamps={"tray_kit": kit["version"]} if kit.get("version") else None)
    return {"result": res, "hz": float(head["hz"]) if head.get("hz") else None}


#: Verdict refusals that still place a glyph on the disc (`glyph_placement`),
#: each with why. Every other refusal places none.
PLACING_REFUSALS = {
    "pairwise_tie": "the best key beat its own cut and tied the runner-up (step 3): a "
                    "glyph is drawn and only which one is open",
    "pending": "Astra's placed star passed or tied its cut (step 4): a star is drawn and "
               "only the slot it turns into is open",
    "outside_candidate_set": "the full-set path (audit or surprise) named a key above its "
                             "own cut outside the lineup's set: a glyph is drawn, and its "
                             "caster is the surprise",
}


def glyph_placement(verdict: dict | None) -> dict:
    """Whether this owner's verdict on a disc track places an ability glyph
    there: `{"placed", "keys", "why"}`, `keys` the glyph keys the verdict
    holds open. For an owner that asks whether a drawn thing is a glyph
    (`round_lifetimes.detection_reality`), never which caster it names.

    - named (`ability` set): placed, its key.
    - `pairwise_tie`, `pending`, `outside_candidate_set` (`PLACING_REFUSALS`):
      placed; the tie's two keys, the best key (Astra:X for the star), the
      full-set path's key. Each passed a cut, so a glyph is drawn there.
    - `not_drawn_per_answer`: not placed. Its best key draws nothing on the
      minimap by the player's answer, so a disc that key fits best is
      unknown, not a glyph; the runner-up is not promoted (step 4).
    - `below_null`, `no_cut_for_key`, `view_excluded`, `no_clean_frame`:
      not placed; no key passed a cut on a clean sample.
    - `occluded`: not placed; every sample lay under a stored portrait, so
      this owner saw no glyph apart from a portrait there.
    - no verdict: not placed.
    """
    if not verdict:
        return {"placed": False, "keys": (), "why": "no verdict on the disc track"}
    if verdict.get("ability"):
        return {"placed": True, "keys": (verdict["ability"]["key"],), "why": "named"}
    reason = verdict.get("reason")
    if reason in PLACING_REFUSALS:
        if reason == "pairwise_tie":
            keys = (verdict.get("best"), verdict.get("second"))
        elif reason == "outside_candidate_set":
            keys = ((verdict.get("outside") or {}).get("best"),)
        else:
            keys = (verdict.get("best"),)
        return {"placed": True, "keys": tuple(k for k in keys if k),
                "why": f"{reason}: {PLACING_REFUSALS[reason]}"}
    return {"placed": False, "keys": (), "why": f"{reason}: places no glyph"}


def places_glyph(verdict: dict | None) -> bool:
    """`glyph_placement(verdict)["placed"]`."""
    return glyph_placement(verdict)["placed"]


def stored_verdicts_stale(store, sid: str) -> dict:
    """`{"why": reason or None, "stamp": content stamp}` of the stored disc
    tracks and verdicts: why they cannot be trusted now, or None. Asks the
    checks that already decide it, restating neither: `stale_reason` on the
    `ability_glyph` head the verdicts were adjudicated over, and `plan`'s
    recorded-input check (`plan.recorded_stale`) on the `ability_disc_track`
    and `ability_glyph_name` heads: a stamp behind the code's, a stored input
    (lineup, tray kit, drawing answers, glyph rows) moved since the verdicts
    read it, or an input they do not record. `stamp` is the stored verdicts'
    content stamp (`input_stamps.content_stamp`), what a reader records."""
    from ..input_stamps import NO_ROWS, content_stamp, head_row
    from ..plan import derived_streams, recorded_stale
    stamp = content_stamp(head_row(store, "ability_glyph_name", sid), "ability_glyph_name_version")
    run = f"run `reticle ability-glyphs {sid}`"
    glyph_head = head_row(store, "ability_glyph", sid)
    if glyph_head is None:
        return {"why": f"no ability_glyph rows -- run `reticle scan {sid} --only ability "
                       f"--from cache`", "stamp": stamp}
    why = stale_reason(glyph_head)
    if why:
        return {"why": f"{why} -- run `reticle scan {sid} --only ability --from cache`",
                "stamp": stamp}
    if stamp == NO_ROWS:
        return {"why": f"no stored ability_glyph_name -- {run}", "stamp": stamp}
    specs = {s["stream"]: s for s in derived_streams()}
    manifest, memo = store.read_manifest(sid), {}
    for stream in ("ability_disc_track", "ability_glyph_name"):
        head = head_row(store, stream, sid)
        if head is None:
            return {"why": f"no stored {stream} -- {run}", "stamp": stamp}
        behind, moved, missing = recorded_stale(store, manifest, specs[stream], head, memo)
        if behind:
            return {"why": f"{stream} is {head.get(specs[stream]['key'])}, current "
                           f"{specs[stream]['current']} -- {run}", "stamp": stamp}
        if moved:
            return {"why": f"{stream} read inputs that moved since ({', '.join(moved)}) -- {run}",
                    "stamp": stamp}
        if missing:
            return {"why": f"{stream} does not record its inputs {', '.join(missing)} -- {run}",
                    "stamp": stamp}
    return {"why": None, "stamp": stamp}


def disc_verdicts(store, sid: str, *, compute: bool = False) -> dict:
    """Where this owner places an ability glyph, for an owner that asks: the
    disc tracks (each with its fixes), the verdict on each, and the disc
    reader's sampling rate `hz`. Read from the stored `ability_disc_track` and
    `ability_glyph_name` streams when `stored_verdicts_stale` finds them
    current; `compute` adjudicates the stored `ability_glyph` rows in memory
    instead (an evaluation that writes nothing). `{"skipped": why, "stamp"}`
    when neither holds. `stamp` is the content stamp of the verdicts read or
    refused (`NO_ROWS` where none are stored), so a reader records which
    verdicts it weighed, or which stale ones it refused."""
    from ..input_stamps import NO_ROWS, content_stamp, head_row
    if compute:
        got = session_adjudication(store, sid)
        if "skipped" in got:
            return {**got, "stamp": NO_ROWS}
        res = got["result"]
        tracks, rows, hz, source = res["tracks"][1:], res["rows"], got["hz"], "computed"
        stamp = content_stamp(rows[0], "ability_glyph_name_version")
    else:
        check = stored_verdicts_stale(store, sid)
        stamp = check["stamp"]
        if check["why"] is not None:
            return {"skipped": check["why"], "stamp": stamp}
        tracks = [t for t in store.read_events("ability_disc_track", sid) or []
                  if t.get("kind") == "track"]
        rows = store.read_events("ability_glyph_name", sid) or []
        head = head_row(store, "ability_glyph", sid) or {}
        hz, source = (float(head["hz"]) if head.get("hz") else None), "stored"
    if not hz:
        return {"skipped": "the ability_glyph head records no sampling rate", "stamp": stamp}
    return {"tracks": tracks, "verdicts": {r["track"]: r for r in rows if r.get("kind") == "verdict"},
            "hz": hz, "source": source, "stamp": stamp,
            "versions": {"ability_disc_track": ABILITY_DISC_TRACK_VERSION,
                         "ability_glyph_name": ABILITY_GLYPH_NAME_VERSION}}
