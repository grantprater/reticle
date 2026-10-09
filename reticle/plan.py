"""What a code change leaves stale, and the least work that refreshes it.

Every stored stream carries the stamp of the code that wrote it; `stale`
compares each with the stamp the code carries now, per session. A stale
reader stream needs a reread, and `scan --only <channel>` rereads only that
channel's readers; the `audio` channel is `ult-lines`, which decodes only
the audio stream (`ACCEPT`). A reader with a trial (`trial.TRIAL_READERS`) reads only
cached ROIs: it can be checked first on stored windows, and `scan` feeds it
from the ROI crop cache instead of decoding when a cache holds its set
(`roi_cache.cache_for`). A stale adjudication rereads
nothing: it reruns from storage; `reticle tray` and `reticle ability-shapes`
reread the stored crops and decode nothing. A reader stream never written is
`absent`, which is not stale. A derived stream never written is listed as
`never run` (`NEVER_RUN`) with its command and how it reads, ordered with the
stale work; the rounds follow a never-run plant graphic, and other streams
built from one are named once it is written: a step that has never run
is work the session lacks, and skipping it hid the plant graphic on every new
capture of 2026-10-07 while `rounds` fell back to the clock-run rule.

A stored stamp the code declares acceptable in its place
(`version.STAMP_WAIVERS`, a testing-phase decision of the player's) is not
stale either, and not current: `stale` lists it under `waived`, as a stream
or as an input of a rerun, and `render` names it as accepted by waiver. A
conditional waiver accepts only on the sessions where its condition
(`WAIVER_CONDITIONS`) holds; elsewhere the stamp stays stale, `stale` lists
it under `declined` with the reason, and `render` names it as not waived.

A stamp is only as good as the bump: a code change that keeps its stamp is
invisible here, as it is to `scan`'s cache check.

Every stamped stream is declared
--------------------------------
Until 2026-09-30 `stale` compared a hand-picked list, and a stream outside it
never showed: `team_vision` at team-vision-0.3.0 under code at 0.6.0 and
`round_entity` at 0.8.0 under 0.9.0 both read as current on `bfad2778a372`.
Now each stream a command stores is declared: the readers
(`reader_streams`), the adjudications checked by hand below, and
`derived_streams`, which names each remaining stream's stamp key, its current
stamp, the stamps of its inputs it records, the streams it is built from, the
command that refreshes it and how that command reads (`storage`, `cache` for
the ROI crop cache, `decode` for the capture). `team_vision` casts its cones over the baked geometry's
occluder table, so it is stale too when the `occluders` it stored is not the
npz's `occ_built_by` today, as after an occluder rebuild. Every stream that
read the minimap widget's pixels (`widget_streams`) is stale too when the
session's stored placement moved since it read them (`placement_moved`): a
refit moves no stamp. An identity stream is stale
with the arbiter or with the stream it is written beside. The entity lanes
(`entity_events`) are checked by `entity_events.lane_status`. A stream on
disk that none of these declares is reported `undeclared`, and one written
with no stamp at all `unstamped` (`UNSTAMPED`), and one no command writes any
more by its retirement (`RETIRED_STREAMS`), and an experiment arm a pass
published under another name (`ARM_STREAMS`), so no stored stream is silent.

Crop caches deleted on purpose
------------------------------
The player deleted every crop cache on 2026-10-09 (`roi_cache.cache_retirement`).
`plan` proposes no `--from cache` step a stored cache cannot feed. On a
session with its video, a stale step that reads a crop cache the store does
not hold waits for its rebuild (`cache_rebuild`, `roi_cache.rebuild_command`),
a decode the player starts, listed first. On a session whose video is retired
and whose caches are gone (`roi_cache.pixel_source`, `no_pixels`), every step
that reads pixels is named `no_pixels` and never proposed; stored rows rerun.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

import pyarrow.parquet as pq


def _table_stamp(path, key: str) -> str | None:
    if not path.is_file():
        return None
    meta = pq.read_schema(path).metadata or {}
    return meta.get(key.encode(), b"").decode() or "unstamped"


def _round_stamps(store, manifest: dict) -> dict | None:
    """The stamps a stored round table was built from, or None where the
    session has no round table. A table written before the portrait stamp
    was recorded reads `unrecorded`."""
    path = store.rounds_path(manifest["session_id"], manifest["ingested_at"][:10])
    if not path.is_file():
        return None
    meta = pq.read_schema(path).metadata or {}
    get = lambda k, missing: meta.get(k.encode(), missing.encode()).decode()
    return {"round": get("round_version", "unstamped"), "hud": get("hud_version", "unknown"),
            "killfeed_portrait": get("killfeed_portrait_version", "unrecorded"),
            "plant_graphic": get("plant_graphic_version", "unrecorded")}


def _upright_placement(store, manifest: dict) -> tuple[bool | None, str]:
    from .widget_frame import upright_throughout
    return upright_throughout(store, manifest)


#: The per-session conditions a conditional waiver names in `when`: each
#: maps (store, manifest) to (holds, why), holds None where unknown.
WAIVER_CONDITIONS = {"upright_placement": _upright_placement}


def waiver_check(stored, current: str, store=None, manifest: dict | None = None,
                 memo: dict | None = None) -> tuple[str | None, str | None]:
    """(why `stored` counts as `current` by a declared waiver, why a declared
    waiver declined); at most one is set, both None where none is declared.

    A conditional waiver (`version.STAMP_WAIVERS` value with `when`) accepts
    only where its condition holds on this session; with no session, or where
    the condition is unknown, it declines. `memo` holds each condition's
    answer for the session."""
    from .version import STAMP_WAIVERS
    w = STAMP_WAIVERS.get((current, stored))
    if w is None or isinstance(w, str):
        return w, None
    cond = w["when"]
    if store is None or manifest is None:
        return None, f"{cond}: no session to evaluate it on"
    memo = {} if memo is None else memo
    key = ("waiver_condition", cond)
    if key not in memo:
        memo[key] = WAIVER_CONDITIONS[cond](store, manifest)
    holds, why = memo[key]
    if holds is True:
        return f"{w['why']} [{cond}: {why}]", None
    return None, f"{cond}: {why}"


def waiver(stored, current: str, store=None, manifest: dict | None = None,
           memo: dict | None = None) -> str | None:
    """Why `stored` counts as `current` by a declared waiver, or None
    (`waiver_check`)."""
    return waiver_check(stored, current, store, manifest, memo)[0]


#: The command that rereads a channel `scan` does not read.
ACCEPT = {"audio": "reticle ult-lines <sid>"}

#: Reader streams `plan` lists as work when a session never wrote them, each
#: with the stored stream that shows its pass can run there: `minimap_dark`
#: reads the minimap widget through the baked geometry's lighting reference,
#: so it is owed wherever the `minimap` pass ran. Another absent reader stays
#: in `absent` only.
NEVER_RUN_READERS = {"minimap_dark": "minimap"}

#: Reader streams whose `scan --only <channel> --from cache` reads the stored
#: crop cache set `roi_cache.channel_cache` names, so a reread decodes
#: nothing. `minimap_dark` reads `frame[box]` of the minimap ROI alone, on its
#: own grid (`DarkRegionReader.cache_resample`). Where the set is missing or
#: cannot feed the pass, the command decodes and `plan` says so.
CACHE_FED_READERS = ("minimap_dark",)


def reader_streams() -> list[tuple[str, str, str, str | None]]:
    """(stream, scan channel, current stamp, trial reader or None)."""
    from .killfeed import (KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION,
                           KILLFEED_WEAPON_VERSION)
    from .killfeed_numeral import KILLFEED_NUMERAL_VERSION
    from .version import (ALLY_ICON_VERSION, COMBAT_REPORT_VERSION, HUD_VERSION,
                          MINIMAP_DARK_VERSION, MINIMAP_VERSION, PING_VERSION,
                          ROSTER_VERSION, SCOREBOARD_VERSION, ULT_LINE_VERSION)
    return [("hud", "hud", HUD_VERSION, "hud"),
            ("killfeed_portrait", "hud", KILLFEED_PORTRAIT_VERSION, "killfeed"),
            ("killfeed_weapon", "hud", KILLFEED_WEAPON_VERSION, "killfeed"),
            ("killfeed_name", "hud", KILLFEED_NAME_VERSION, "killfeed"),
            ("killfeed_numeral", "hud", KILLFEED_NUMERAL_VERSION, "killfeed"),
            ("minimap", "minimap", MINIMAP_VERSION, None),
            ("roster", "roster", ROSTER_VERSION, None),
            ("ping", "ping", PING_VERSION, None),
            ("ally_icon", "ally_icon", ALLY_ICON_VERSION, "ally_icon"),
            ("minimap_dark", "minimap_dark", MINIMAP_DARK_VERSION, None),
            ("combat_report", "combat_report", COMBAT_REPORT_VERSION, None),
            ("scoreboard", "scoreboard", SCOREBOARD_VERSION, None),
            ("ult_line", "audio", ULT_LINE_VERSION, None)]


#: Streams a command writes with no stamp, and why; `stale` lists them as
#: `unstamped` rather than calling them current.
UNSTAMPED = {
    # Written since 2026-10-07 under a stamped coverage row, and then checked
    # with `combat_report_identity` (`written_with`); older files are named.
    "combat_report_rows": "written beside combat_report_identity by `reticle combat-report`, "
                          "with no stamp of its own",
}

#: Streams no command writes any more, and why. Their stored rows stay as
#: evidence, never rewritten; `stale` lists them as `unchecked` with the
#: retirement, so a stored file is never silent and never proposed as work.
RETIRED_STREAMS = {
    # docs/ABILITY_ENTITIES.md step 0: `prototypes/ability_cast.py --emit`
    # wrote it on demo sessions with no version key, and nothing reads it.
    "ability": "retired 2026-10-09: prototypes/ability_cast.py --emit wrote it with no "
               "version key and nothing reads it; tray_drop.player_cast and ability_shape "
               "answer its questions; stored rows kept, never rewritten",
    # docs/ABILITY_ENTITIES.md step 2: the player's Ruse casts while dead are
    # the player's Ruse children `slot_state` opens on a dead Clove's smokes
    # (`ability_timeline.dead_ruse_casts` stays their charge ledger).
    "dead_ruse_cast": "retired 2026-10-09: the player's Ruse children in `ability_child` "
                      "(opened_by `dead_clove_smoke`) answer it; `reticle smokes` no longer "
                      "writes it; stored rows kept, never rewritten",
}

#: Experiment arms: a reader's rows a pass published under another stream
#: name, kept apart from the production stream; `stale` lists them as
#: `unchecked` with why, and proposes no rerun.
ARM_STREAMS = {
    # `scan --only ally_icon --ally-gate on --ally-stream ally_icon_gatedN`
    # on cadaadeb2d8b, one per gate version, each beside its `_audit` rows;
    # `prototypes/real_reader_schedule.py hook` scores them (`HOOK_REAL`).
    re.compile(r"ally_icon_gated\d*(_audit)?"):
        "experiment arm: a gated ally_icon pass published apart (`scan --ally-stream`), "
        "scored by prototypes/real_reader_schedule.py hook; no consumer, never rerun",
}


def arm_reason(stream: str) -> str | None:
    """Why `stream` is an experiment arm (`ARM_STREAMS`), or None."""
    return next((why for pat, why in ARM_STREAMS.items() if pat.fullmatch(stream)), None)


#: Hand-checked streams whose command rereads the ROI crop cache.
_CACHE_READERS = {"scoreboard_strip": "cache", "self_icon": "cache"}

#: The streams `stale` checks by hand, before `derived_streams`.
_HAND_CHECKED = ("death", "ult_cast", "tray_drop", "ability_shape", "scoreboard_strip",
                 "scoreboard_presence", "ability_state", "self_icon")


def ability_streams() -> list[tuple[str, str, str]]:
    """(stream, stamp key, current stamp) of each stream the ability pass
    writes (`reticle scan <sid> --only ability`, `ability_scan`)."""
    from .version import (ABILITY_FIT_VERSION, ABILITY_GATE_VERSION, ABILITY_GLYPH_VERSION,
                          ABILITY_ICON_VERSION, ABILITY_SHAPE_VERSION, ABILITY_WALL_VERSION,
                          CLOVE_CIRCLE_VERSION)
    return [("ability_gate", "ability_gate_version", ABILITY_GATE_VERSION),
            ("ability_fit", "ability_fit_version", ABILITY_FIT_VERSION),
            ("ability_wall", "ability_wall_version", ABILITY_WALL_VERSION),
            ("ability_shape_scan", "ability_shape_scan_version", ABILITY_SHAPE_VERSION),
            ("ability_shape_audit", "ability_shape_audit_version", ABILITY_SHAPE_VERSION),
            ("ability_icon", "ability_icon_version", ABILITY_ICON_VERSION),
            ("ability_glyph", "ability_glyph_version", ABILITY_GLYPH_VERSION),
            ("clove_circle", "clove_circle_version", CLOVE_CIRCLE_VERSION)]


#: Streams the ability pass gained after it had run on stored sessions, each
#: with the sibling stream whose presence shows the pass ran there: `stale`
#: names such a stream absent beside its sibling. The glyph reader reads the
#: proposer's rows, so a stored `ability_icon` is the pass it should have joined.
PASS_ADDED = {"ability_glyph": "ability_icon", "clove_circle": "ability_icon"}


def _ability_inputs(stream: str) -> tuple[dict, tuple]:
    """(fields, upstream) of one ability-pass stream: the gate's samples feed
    every shape stream but the walls; the candidate streams also rest on the
    candidate table, its facts' values and the stored deaths. The glyph
    reader reads the proposer's rows, the stored portraits its gate reads
    (`ally_icon`), and its reference bank and tables
    (`minimap_glyph.GLYPH_BANK_STAMP`)."""
    from .ability_candidates import values_digest
    from .minimap_glyph import GLYPH_BANK_STAMP
    from .version import (ABILITY_CANDIDATES_VERSION, ABILITY_GATE_VERSION, ABILITY_ICON_VERSION,
                          ABILITY_SHAPE_VERSION)
    gate = {"ability_gate_version": ABILITY_GATE_VERSION}
    cand = {"ability_shape_version": ABILITY_SHAPE_VERSION,
            "ability_candidates_version": ABILITY_CANDIDATES_VERSION,
            "appearance_values": values_digest()}
    return {"ability_gate": ({}, ()), "ability_icon": ({}, ()),
            "ability_glyph": ({"glyph_bank": GLYPH_BANK_STAMP,
                               "ability_icon_version": ABILITY_ICON_VERSION},
                              ("ability_icon", "ally_icon")),
            "ability_shape_scan": (gate, ("ability_gate",)),
            "ability_shape_audit": (gate, ("ability_gate",)),
            "ability_fit": ({**gate, **cand}, ("ability_gate", "death")),
            "ability_wall": (cand, ("death",)),
            # The circle reads only the windows the stored deaths open.
            "clove_circle": ({}, ("death",))}[stream]


def _ability_light_applies(store, sid: str) -> tuple[str, str | None]:
    from .adjudication.ability import light_applies
    return light_applies(store, sid)


def derived_streams() -> list[dict]:
    """Every stored adjudication and derived stream `stale` does not check by
    hand. The list's order is not the build order: `build_order` derives
    that from the declared inputs (`order_graph`), so no hand-kept order
    can contradict them.

    `key` is the stamp in the stream's first row and `current` the code's.
    `fields` maps a stamp the first row records of an input (`a.b` descends
    a dict) to its current value; a stored None is an input not used.
    `upstream` names the streams it is built from: when one of them is
    stale, so is this, once that one is refreshed. `identity` streams hold
    `adjudication.identity`'s verdicts, stamped `producer_version`, and are
    written by `parent`'s command. `how` is what the command reads.

    `written_with` names a stream the same command writes beside an identity
    stream, whose coverage row stamps the run and counts its identity events:
    an identity stream with no event reads as run where that row counts none.
    `applies(store, sid)` is the owning rule's word on whether the stream
    applies to a session: ("applies" | "not_applicable" | "unknown", why), or
    None while its input is unwritten. A stream that does not apply is never
    work; `stale` lists it under `not_applicable` with its status and why.
    """
    from .adjudication.assist import ASSIST_ADJUDICATION_VERSION
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    from .adjudication.identity import AGENT_IDENTITY_VERSION, PLAYER_AGENT_VERSION
    from .adjudication.killstreak import KILLSTREAK_WITNESS_VERSION
    from .adjudication.self_entry import SELF_ENTRY_VERSION
    from .enemy_tracks import ENEMY_TRACK_VERSION
    from .killfeed_assist import KILLFEED_ASSIST_VERSION
    from .killfeed_numeral import KILLFEED_NUMERAL_VERSION
    from .lighting import LIGHTING_VERSION
    from .minimap_objects import minimap_object_version
    from .version import ALLY_PORTRAIT_FEATURES_VERSION, ENEMY_TEARDROP_VERSION
    from .minimap_diagnostics import DIAGNOSTICS_VERSION
    from .minimap_lifecycle import LIFECYCLE_VERSION
    from .roi_cache import ROI_CACHE_VERSION
    from .slot_state import ABILITY_CHILD_VERSION, ABILITY_EFFECT_VERSION
    from .round_entities import ROUND_ENTITY_VERSION
    from .round_lifetimes import DETECTION_REALITY_VERSION, ROUND_LIFETIME_VERSION
    from .stalls import STALL_VERSION
    from .track import TRACK_VERSION
    from .version import (ABILITY_LIGHT_VERSION, COMBAT_REPORT_ROUND_VERSION,
                          COMBAT_REPORT_VERSION, ICON_TEARDROP_VERSION, MENU_VERSION,
                          MINIMAP_DARK_VERSION, PLANT_GRAPHIC_VERSION, SMOKE_OWNER_VERSION,
                          SMOKE_VERSION, SPIKE_CARRIER_VERSION, SPIKE_VERSION, TEAM_VISION_VERSION,
                          TEARDROP_VERSION, TRAY_COUNTDOWN_VERSION, TRAY_FILL_VERSION,
                          TRAY_KIT_VERSION, TRAY_SEGMENT_VERSION)
    from .version import ABILITY_DISC_TRACK_VERSION, ABILITY_GLYPH_NAME_VERSION
    from .version import (ROUND_OUTCOME_CLAIM_VERSION, ROUND_OUTCOME_VERSION,
                          SCOREBOARD_STRIP_VERSION)
    roi = {"roi_cache_version": ROI_CACHE_VERSION}
    rows = [
        {"stream": "menu_open", "key": "menu_version", "current": MENU_VERSION,
         "command": "reticle menu {sid}", "how": "cache", "fields": roi, "upstream": ()},
        {"stream": "spike", "key": "spike_version", "current": SPIKE_VERSION,
         "command": "reticle spike {sid}", "how": "cache", "fields": roi, "upstream": ()},
        # How each round ended: the round-history cells reread from the
        # scoreboard crop cache on the strip's present frames, pooled into one
        # claim per stored round. The coverage row records the pooling stamp.
        {"stream": "round_outcome", "key": "round_outcome_version",
         "current": ROUND_OUTCOME_VERSION, "command": "reticle round-outcome {sid}",
         "how": "cache",
         "fields": {**roi, "scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                    "round_outcome_claim_version": ROUND_OUTCOME_CLAIM_VERSION},
         "upstream": ("scoreboard_strip", "rounds")},
        {"stream": "plant_graphic", "key": "plant_graphic_version",
         "current": PLANT_GRAPHIC_VERSION, "command": "reticle plant-graphic {sid}",
         "how": "cache", "fields": roi, "upstream": ()},
        {"stream": "spike_carrier", "key": "spike_carrier_version",
         "current": SPIKE_CARRIER_VERSION, "command": "reticle spike {sid} --from-store",
         "how": "storage", "fields": {"spike_version": SPIKE_VERSION},
         "upstream": ("spike", "rounds", "roster")},
        {"stream": "team_vision", "key": "team_vision_version", "current": TEAM_VISION_VERSION,
         "command": "reticle vision {sid}", "how": "cache",
         "fields": {**roi, "lighting_version": LIGHTING_VERSION, "track_version": TRACK_VERSION,
                    "teardrop_version": TEARDROP_VERSION,
                    "lifecycle_version": LIFECYCLE_VERSION,
                    "diagnostics_version": DIAGNOSTICS_VERSION, "stall_version": STALL_VERSION},
         # The cones stop at the geometry's occluder table: the stored
         # `occluders` must be the npz's `occ_built_by` today. The teammates
         # are the stored `ally_icon` stream's (team-vision-0.7.0), which
         # records its own teardrop stamps.
         "occluders": "geometry_key", "upstream": ("ally_icon",)},
        {"stream": "round_entity", "key": "round_entity_version", "current": ROUND_ENTITY_VERSION,
         "command": "reticle lifetimes {sid}", "how": "storage",
         "fields": {"round_lifetime_version": ROUND_LIFETIME_VERSION,
                    "agent_identity_version": AGENT_IDENTITY_VERSION, "menu_open": MENU_VERSION},
         "upstream": ("ally_icon", "hud", "roster", "death", "menu_open")},
        {"stream": "smoke", "key": "smoke_version", "current": SMOKE_VERSION,
         "command": "reticle smokes {sid}", "how": "storage",
         "fields": {"minimap_dark_version": MINIMAP_DARK_VERSION},
         "upstream": ("minimap_dark", "menu_open")},
        {"stream": "smoke_owner", "key": "smoke_owner_version", "current": SMOKE_OWNER_VERSION,
         "command": "reticle smokes {sid}", "how": "storage",
         "fields": {"smoke_version": SMOKE_VERSION},
         "upstream": ("smoke", "tray_drop", "rounds")},
        # The minimap glyph channel's stage 3 (docs/MINIMAP_GLYPH_CHANNEL.md,
        # section 4): the disc tracks joined from the stored glyph and icon
        # rows, and the verdict over them with its null and states tables.
        {"stream": "ability_disc_track", "key": "ability_disc_track_version",
         "current": ABILITY_DISC_TRACK_VERSION, "command": "reticle ability-glyphs {sid}",
         "how": "storage", "fields": {}, "upstream": ("ability_icon", "ability_glyph")},
        {"stream": "ability_glyph_name", "key": "ability_glyph_name_version",
         "current": ABILITY_GLYPH_NAME_VERSION, "command": "reticle ability-glyphs {sid}",
         "how": "storage", "fields": {},
         "upstream": ("ability_disc_track", "ability_glyph", "tray_kit")},
        # Every slot's ability children and effects (`slot_state`,
        # docs/ABILITY_ENTITIES.md step 3), built from the stored witnesses;
        # one command writes both, the children first.
        {"stream": "ability_child", "key": "ability_child_version",
         "current": ABILITY_CHILD_VERSION, "command": "reticle ability-children {sid} --write",
         "how": "storage", "fields": {},
         "upstream": ("ability_state", "ult_cast", "smoke_owner", "ability_shape",
                      "ability_glyph_name", "ability_disc_track", "tray_kit", "tray_drop",
                      "death", "assist", "rounds")},
        {"stream": "ability_effect", "key": "ability_effect_version",
         "current": ABILITY_EFFECT_VERSION, "command": "reticle ability-children {sid} --write",
         "how": "storage", "fields": {}, "upstream": ("ability_child", "death", "assist")},
        {"stream": "combat_report_round", "key": "combat_report_round_version",
         "current": COMBAT_REPORT_ROUND_VERSION, "command": "reticle combat-report {sid}",
         "how": "storage", "fields": {"combat_report_version": COMBAT_REPORT_VERSION},
         "upstream": ("combat_report", "rounds", "death")},
        {"stream": "tray_kit", "key": "tray_kit_version", "current": TRAY_KIT_VERSION,
         "command": "reticle tray-kit {sid}", "how": "cache",
         "fields": {"inputs.tray_fill": TRAY_FILL_VERSION, "inputs.roi_cache": ROI_CACHE_VERSION},
         "upstream": ()},
        # The restock countdown joins the tray's pass (`reticle tray`).
        {"stream": "tray_countdown", "key": "tray_countdown_version",
         "current": TRAY_COUNTDOWN_VERSION, "command": "reticle tray {sid}", "how": "cache",
         "fields": {"inputs.roi_cache": ROI_CACHE_VERSION,
                    "inputs.tray_segment": TRAY_SEGMENT_VERSION},
         "upstream": ()},
        {"stream": "ability_light", "key": "ability_light_version",
         "current": ABILITY_LIGHT_VERSION, "command": "reticle ability-light {sid}",
         "how": "decode", "fields": {"lighting_version": LIGHTING_VERSION}, "upstream": (),
         # It reads the light only at ability candidates' instants
         # (`adjudication.ability.light_applies`).
         "applies": _ability_light_applies},
        # The enemy lane: the minimap objects reread the crop cache, and each
        # fix that is on is part of the stamp; the tracks rerun from storage.
        {"stream": "minimap_object", "key": "minimap_object_version",
         "current": minimap_object_version(), "command": "reticle minimap-objects {sid}",
         "how": "cache",
         "fields": {**roi, "teardrop_version": TEARDROP_VERSION,
                    "enemy_teardrop_version": ENEMY_TEARDROP_VERSION,
                    "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION},
         "upstream": ()},
        # The assist panel [domain:killfeed/assist-panel], reread from the
        # killfeed crop cache on the stored deaths' killer views; its summary
        # row records its inputs.
        {"stream": "killfeed_assist", "key": "killfeed_assist_version",
         "current": KILLFEED_ASSIST_VERSION, "command": "reticle assists {sid}", "how": "cache",
         "fields": {"inputs.roi_cache": ROI_CACHE_VERSION},
         "upstream": ("killfeed_portrait", "death")},
        {"stream": "assist", "key": "assist_adjudication_version",
         "current": ASSIST_ADJUDICATION_VERSION, "command": "reticle assists {sid}",
         "how": "cache",
         "fields": {"inputs.killfeed_assist": KILLFEED_ASSIST_VERSION,
                    "inputs.agent_identity": AGENT_IDENTITY_VERSION},
         "upstream": ("killfeed_assist", "death")},
        {"stream": "enemy_track", "key": "enemy_track_version", "current": ENEMY_TRACK_VERSION,
         "command": "reticle enemy-tracks {sid}", "how": "storage",
         "fields": {"minimap_object_version": minimap_object_version(),
                    "round_lifetime_version": ROUND_LIFETIME_VERSION,
                    "detection_reality_version": DETECTION_REALITY_VERSION,
                    "agent_identity_version": AGENT_IDENTITY_VERSION},
         "upstream": ("minimap_object", "death", "rounds", "ability_glyph_name")},
        # The killstreak numeral [domain:killfeed/killstreak-indicator]
        # against the death stream's kill index: a
        # check over two stored streams, rerun from storage. Its summary row
        # records both inputs' stamps.
        {"stream": "killstreak_witness", "key": "killstreak_witness_version",
         "current": KILLSTREAK_WITNESS_VERSION, "command": "reticle killstreak {sid}",
         "how": "storage",
         "fields": {"inputs.killfeed_numeral": KILLFEED_NUMERAL_VERSION,
                    "inputs.death": DEATH_ADJUDICATION_VERSION},
         "upstream": ("death", "killfeed_numeral")},
        # The player's own killfeed roles (`adjudication.self_entry`): the
        # death stream's portrait claims against the lineup's player binding.
        {"stream": "self_entry", "key": "self_entry_version",
         "current": SELF_ENTRY_VERSION, "command": "reticle self-entries {sid} --record",
         "how": "storage",
         "fields": {"inputs.death": DEATH_ADJUDICATION_VERSION,
                    "inputs.player_agent": PLAYER_AGENT_VERSION},
         "upstream": ("death",)},
    ]
    # The ability pass's streams reread the minimap crop cache, each under its
    # own stamp; a stream that reads the gate's samples records the gate's
    # stamp and follows it (`_ability_inputs`).
    for stream, key, current in ability_streams():
        fields, upstream = _ability_inputs(stream)
        rows.append({"stream": stream, "key": key, "current": current,
                     "command": "reticle scan {sid} --only ability", "how": "cache",
                     "fields": fields, "upstream": upstream})
    for stream, parent, command, how, written_with in (
            ("death_identity", "death", "reticle deaths {sid}", "storage", None),
            ("combat_report_identity", "combat_report_round", "reticle combat-report {sid}",
             "storage", "combat_report_rows"),
            ("smoke_owner_identity", "smoke_owner", "reticle smokes {sid}", "storage", None),
            ("ability_glyph_identity", "ability_glyph_name", "reticle ability-glyphs {sid}",
             "storage", None),
            ("tray_kit_identity", "tray_kit", "reticle tray-kit {sid}", "cache", None),
            ("ult_cast_identity", "ult_cast", "reticle ult-cast {sid}", "storage", None),
            ("enemy_track_identity", "enemy_track", "reticle enemy-tracks {sid}", "storage",
             None),
            ("ability_child_identity", "ability_child", "reticle ability-children {sid} --write",
             "storage", None)):
        row = {"stream": stream, "key": "producer_version",
               "current": AGENT_IDENTITY_VERSION, "command": command, "how": how,
               "fields": {}, "upstream": (parent,), "identity": True}
        if written_with is not None:
            row["written_with"] = written_with
        rows.append(row)
    return rows


def rerun_commands() -> frozenset[str]:
    """The CLI commands that recompute a derived stream from storage or the
    crop cache, as `reticle usage` records them: each hand-checked stream's
    and each declared stream's command, less `scan` and any command whose
    `how` is `decode`, plus `rounds`, which `stale` names by hand."""
    found = {"rounds", "segment"}
    specs = [{"command": cmd, "how": _CACHE_READERS.get(s, "storage")}
             for s, (_, _, cmd) in _hand_specs().items()] + derived_streams()
    for spec in specs:
        words = spec["command"].split()
        if len(words) > 1 and words[1] != "scan" and spec["how"] != "decode":
            found.add(words[1])
    return frozenset(found)


def _head(store, stream: str, sid: str, needle: bytes | None = None) -> dict | None:
    """The first row of a stored stream (with `needle`, the first row whose
    line holds it), without reading the rest."""
    from .input_stamps import head_row
    return head_row(store, stream, sid, needle)


# ------------------------------------------------------------ stored inputs
#
# Each derived stream declares here, once, every stored input it reads: the
# path in its first row where the writer records the input's stamp, and the
# probe that reads the input's stamp as stored now (`input_head`). `stale`
# compares the two for every stream (`inputs_moved`), and a writer records
# through the same declaration (`record_inputs`), so what plan compares is
# what the writer read. A stamp the code carries for a rule rather than for a
# stored input (`lighting_version`, `player_cast`) stays a code field
# (`derived_streams`' `fields`, or the hand checks in `stale`).

def _in(path: str, probe: str, *, optional: bool = False, use_when: str | None = None,
        before: str | None = None) -> dict:
    """One declared input. `optional`: rows that never read it (a cast pass
    with no tray drops) leave its key out, and that is not `unrecorded`.
    `use_when`: an older writer recorded None where the stored input was not
    at this stamp and so went unread; it is stale once the input is.
    `before`: the stamp a head written before the input was recorded read, so
    such a head is compared as if it recorded it."""
    return {"path": path, "probe": probe, "optional": optional, "use_when": use_when,
            "before": before}


def _spans() -> dict:
    """The stored spans a minimap reader read (`segment.reader_spans`), as its
    head records them. Heads written before seg-0.3.0 record none and read
    seg-0.2.0's active spans."""
    return _in("inputs.spans", "spans", before="seg-0.2.0")


#: The reader streams `scan` reads over the stored spans (`cli._reader_spans`).
#: The ability pass's streams ride the same spans and declare `_spans` too.
SPAN_READERS = ("minimap", "ping", "ally_icon", "minimap_dark")


def _code(path: str, stamp: str, *, optional: bool = False, before: str | None = None) -> dict:
    """A rule's stamp the stream records beside its inputs: compared with the
    code's `stamp`, not with anything stored. `before`, as for `_in`: what a
    head written before the stamp was recorded is compared as."""
    return _in(path, "=" + stamp, optional=optional, before=before)


#: Keys a stream's head records that are not stored-input stamps, and why
#: plan does not compare them (`doctor` INPUTS reads this).
NOT_INPUTS = {
    "ability_channels_version": "the channel declaration `slot_state.CHANNELS` the child owner built under; code, not a stored input, and a change to it restamps `ABILITY_CHILD_VERSION`",
    "board_state": "folded into the lineup view, compared as `lineup`",
    "tray_kit_reason": "why the kit witness went unused, not a stamp",
    "tray_kit_own_basis": "which agent the kit witness judged `own` against (`stored` or "
                          "`consumer_agent`, `stored_kit_witness`): a label derived from the "
                          "tray_kit rows and the player agent, compared as `tray_kit` and "
                          "`lineup`, not a stamp",
    "geometry_key": "names the geometry; its `built_by` is compared as `geometry`",
    "ally_icon_revision": "the ally_icon bytes `reticle lifetimes` keys its cache on; "
                          "the stream's stamp is compared as `ally_icon`",
    "icon_teardrop_version": "the teammate teardrop stamp; `ally_icon` compares it as a rule "
                             "stamp, and `team_vision` heads before team-vision-0.7.0 recorded "
                             "it, which their own stamp now stales",
    "inputs_revision": "the byte digest `reticle lifetimes` keys its cache on; its parts "
                       "are compared one by one",
    "events_version": "the event contract's stamp, written by `store.write_events`",
    "stored_spike_version": "the spike stamp `spike_carrier` read, compared as `spike`",
    "candidate_revision": "the ally_icon candidate batch, carried on the rows built from it",
    "geometry": "round_outcome's column fit, measured from this session's cached scoreboard "
                "crops by `fit_columns`: the reader's own output, not a baked table",
    "ult_cast_reason": "why the gate's own ult lines went unused (`ability_timeline."
                       "stored_own_lines`), not a stamp",
    "pool_facts": "the keys of the domain facts that make a slot of the player's agent a pool "
                  "(`ability_timeline.pool_slots`): a rule read from domain/*.toml, which "
                  "moves with the gate's own stamp (`player_cast`), not a stored stream",
}


def _gate(prefix: str = "inputs.", optional: bool = False) -> dict:
    """The stored inputs of the player-cast gate (`ability_timeline.stored_gate_inputs`),
    and the two rule stamps it records beside them."""
    from .gametime import GAMETIME_VERSION
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .version import PLAYER_CAST_VERSION
    return {"player_cast": _code(prefix + "player_cast", PLAYER_CAST_VERSION, optional=optional),
            "gametime": _code(prefix + "gametime", GAMETIME_VERSION, optional=optional),
            "hud": _in(prefix + "hud", "hud", optional=optional),
            "killfeed_portrait": _in(prefix + "killfeed_portrait", "killfeed_portrait",
                                     optional=optional, use_when=KILLFEED_PORTRAIT_VERSION),
            "death": _in(prefix + "death", "death#death_adjudication_version", optional=optional),
            "combat_report_round": _in(prefix + "combat_report_round",
                                       "combat_report_round#combat_report_round_version",
                                       optional=optional),
            "tray_kit": _in(prefix + "tray_kit", "tray_kit#tray_kit_version", optional=optional),
            "menu_open": _in(prefix + "menu_open", "menu_open#menu_version", optional=optional),
            # The own ult lines that witness an X cast (`own_line_times`).
            "ult_cast": _in(prefix + "ult_cast", "ult_cast#ult_cast_version", optional=True),
            # The restock numerals that witness a co-occurring spend.
            "tray_countdown": _in(prefix + "tray_countdown",
                                  "tray_countdown#tray_countdown_version", optional=True)}


def _lineup_inputs(prefix: str = "inputs.", file_path: str | None = None) -> dict:
    """The lineup file's version and the view `load_lineup` folds over it."""
    return {"lineup_file": _in(file_path or prefix + "lineup", "lineup_file"),
            "lineup": _in(prefix + "lineup_view", "lineup")}


def _supply_inputs() -> dict:
    """The stored inputs a candidate supply rests on (`CandidateSupply.rests_on`)."""
    return {"death": _in("supply.death", "death#death_adjudication_version", optional=True),
            "lineup_file": _in("supply.lineup", "lineup_file", optional=True),
            "round": _in("supply.rounds", "rounds", optional=True)}


def stream_inputs() -> dict[str, dict[str, dict]]:
    """stream -> {input name: declared input}, for every stream that reads a
    stored input. The name is what `plan` reports as moved."""
    from .adjudication.identity import AGENT_IDENTITY_VERSION
    from .adjudication.self_entry import SELF_ENTRY_VERSION
    from .adjudication.killfeed_kits import KILLFEED_KITS_VERSION
    from .killfeed import KILLFEED_NAME_VERSION, KILLFEED_WEAPON_VERSION
    from .killfeed_assist import ICON_BUILD
    from .lighting import LIGHTING_VERSION
    from .version import TRAY_SEGMENT_VERSION
    from .adjudication.ability_glyph import STATES_TABLE as GLYPH_STATES_TABLE
    from .minimap_glyph import GLYPH_DATA
    from .version import ABILITY_DISC_TRACK_VERSION
    from .roi_cache import ROI_CACHE_VERSION
    from .ability_candidates import values_digest
    from .version import (ABILITY_AUDIO_PARAMS_VERSION, ABILITY_AUDIO_VERSION,
                          ABILITY_CANDIDATES_VERSION, ABILITY_FIT_VERSION, ABILITY_SHAPE_VERSION,
                          ICON_POSE_PRIOR_VERSION, STACK_FIT_VERSION,
                          ICON_TEARDROP_VERSION, ROUND_VERSION, TEARDROP_VERSION,
                          TRAY_FILL_VERSION)
    geo ={"geometry": _in("geometry_built_by", "geometry")}
    death = "death#death_adjudication_version"
    return {
        "death": {"hud": _in("inputs.hud", "hud"),
                  "killfeed_portrait": _in("inputs.killfeed_portrait", "killfeed_portrait"),
                  "killfeed_weapon": _in("inputs.killfeed_weapon", "killfeed_weapon",
                                         use_when=KILLFEED_WEAPON_VERSION),
                  "killfeed_name": _in("inputs.killfeed_name", "killfeed_name",
                                       use_when=KILLFEED_NAME_VERSION),
                  "scoreboard": _in("inputs.scoreboard", "scoreboard"),
                  "round": _in("inputs.round", "rounds"),
                  # The X marks are read only from current streams, and a table
                  # built before them records neither (`reticle deaths` records
                  # both, None where unread).
                  "minimap_object": _in("inputs.minimap_object",
                                        "minimap_object#minimap_object_version", optional=True),
                  "ally_icon": _in("inputs.ally_icon", "ally_icon", optional=True),
                  # The death panel's reads set aside (`panel_aside`): read only
                  # at the code's stamp; heads before death-adjudication-0.36.0
                  # record none.
                  "combat_report": _in("inputs.combat_report", "combat_report", optional=True),
                  "roster": _in("inputs.roster", "roster"),
                  # The assist verdicts the deaths join (`join_assists`); a head
                  # records `stale:<death rule>` or `no_rows` where it joined none.
                  "assist": _in("inputs.assist", "assist#assist_adjudication_version",
                                optional=True),
                  "reliability_table": _in("inputs.reliability_table", "reliability"),
                  # How each round ended: read only at the code's stamps, and
                  # heads before death-adjudication-0.34.0 record none.
                  "round_outcome": _in("inputs.round_outcome",
                                       "round_outcome#round_outcome_version", optional=True),
                  # The claims' pooling stamp, which the stream's first row
                  # carries (`stored_outcome_claims` reads claims only at it).
                  "round_outcome_claim": _in("inputs.round_outcome_claim",
                                             "round_outcome#round_outcome_claim_version",
                                             optional=True),
                  **_lineup_inputs()},
        "ult_cast": {"ult_line": _in("inputs.ult_line", "ult_line"),
                     "round": _in("inputs.round", "rounds"),
                     "agent_identity": _code("inputs.agent_identity", AGENT_IDENTITY_VERSION),
                     "tray_drop": _in("inputs.tray_drop", "tray_drop#tray_version",
                                      optional=True),
                     # Its own rows feed the gate back only as lines that
                     # rest on no tray cast, so it is not its own input.
                     **{k: v for k, v in _gate(optional=True).items() if k != "ult_cast"},
                     **_lineup_inputs()},
        "tray_drop": {"tray_kit": _in("tray_kit", "tray_kit#tray_kit_version"),
                      "menu_open": _in("menu_open", "menu_open#menu_version"),
                      **{k: v for k, v in _gate(optional=True).items()
                         if k not in ("tray_kit", "menu_open")},
                      "round": _in("inputs.round", "rounds"), **_lineup_inputs()},
        # The shapes are fitted after the gate's casts, over the stored rounds
        # and the arbiter's player agent, seeded from the minimap table. The
        # candidate table picks which casts are fitted (`TABLE`) and sizes and
        # colours each fit (`ability_descriptor`), so its stamp and its facts'
        # values are rules the rows rest on; `ability-shape-0.1.0` heads do
        # not record them.
        "ability_shape": {"tray_drop": _in("tray_version", "tray_drop#tray_version"),
                          "minimap": _in("minimap_version", "minimap"),
                          "round": _in("inputs.round", "rounds"),
                          "candidates": _code("ability_candidates_version",
                                              ABILITY_CANDIDATES_VERSION, optional=True),
                          "appearance_values": _code("appearance_values", values_digest(),
                                                     optional=True),
                          **_gate(), **_lineup_inputs()},
        # The candidate streams of the ability pass fit over the supply
        # `ability_candidates.for_session` built from the stored deaths, the
        # lineup file and the rounds, and record their stamps under `supply`.
        # Until 2026-10-01 nothing compared them: `death` was only an
        # `upstream`, followed while the deaths were stale and forgotten once
        # they were rerun, so a fit over `death-adjudication-0.20.0` read as
        # current beside deaths at 0.25.0. A pass with no supply (`supply:
        # null`, `supply_reason`) read none of them, hence `optional`.
        "ability_fit": _supply_inputs(),
        "ability_wall": _supply_inputs(),
        "scoreboard_presence": {"scoreboard_strip": _in("scoreboard_strip_version",
                                                        "scoreboard_strip#scoreboard_strip_version"),
                                "scoreboard": _in("scoreboard_version", "scoreboard")},
        "ability_state": {**_gate(), "tray_drop": _in("inputs.tray_drop", "tray_drop#tray_version"),
                          "tray_drop_player_cast": _in("inputs.tray_drop_player_cast",
                                                       "tray_drop#player_cast_version"),
                          "round": _in("inputs.round", "rounds"),
                          "catalogue": _in("inputs.catalogue", "catalogue"),
                          "tray_fill": _code("inputs.tray_fill", TRAY_FILL_VERSION),
                          # The bar's half classes it rereads beside the fills.
                          "tray_segment": _code("inputs.tray_segment", TRAY_SEGMENT_VERSION),
                          # The icon set the drawn test asks (`cli._tray_icon_witness`).
                          "tray_icons": _in("inputs.tray_icons", "catalogue_icons"),
                          "roi_cache": _code("inputs.roi_cache", ROI_CACHE_VERSION),
                          "agent_identity": _code("inputs.agent_identity", AGENT_IDENTITY_VERSION),
                          # The audio witness (`audio_cast_witness`): its rule,
                          # the fitted parameters it loads by the code's stamp,
                          # and the audio gate's stored log-mel and labels. A
                          # refused witness records the two files as None.
                          "ability_audio": _code("inputs.ability_audio", ABILITY_AUDIO_VERSION),
                          "ability_audio_params": _code("inputs.ability_audio_params",
                                                        ABILITY_AUDIO_PARAMS_VERSION),
                          "audio_features": _in("inputs.audio_features", "audio_features"),
                          "audio_labels": _in("inputs.audio_labels", "audio_labels"),
                          **_lineup_inputs()},
        "self_icon": {"roster": _in("roster_version", "roster"),
                      "portrait_refs": _in("reference_version", "portrait_refs"), **geo},
        "round_outcome": {"scoreboard_strip": _in("scoreboard_strip_version",
                                                  "scoreboard_strip#scoreboard_strip_version")},
        "spike_carrier": {"spike": _in("spike_version", "spike#spike_version"),
                          "rounds": _in("inputs.rounds", "rounds"),
                          "roster": _in("inputs.roster", "roster")},
        # The teammates' poses are the stored ally reader's (team-vision-0.7.0).
        "team_vision": {"ally_icon": _in("inputs.ally_icon", "ally_icon"), **geo},
        # `reticle lifetimes` builds the rounds in memory from the stored HUD
        # (`rounds.build_rounds`) rather than reading the round table, so the
        # round rule is a code stamp; a head written before it was recorded
        # read an unknown rule and is stale.
        "round_entity": {"round_rule": _code("inputs.round_rule", ROUND_VERSION,
                                             before="unrecorded"),
                         "menu_open": _in("menu_open", "menu_open#menu_version"),
                         "hud": _in("inputs.hud", "hud"), "roster": _in("inputs.roster", "roster"),
                         "ally_icon": _in("inputs.ally_icon", "ally_icon"),
                         "death": _in("inputs.death", death),
                         "scoreboard": _in("inputs.scoreboard", "scoreboard"),
                         "portrait_refs": _in("ally_portrait_refs_version", "portrait_refs_fit"),
                         "lineup": _in("inputs.lineup_view", "lineup")},
        "smoke": {"minimap_dark": _in("minimap_dark_version", "minimap_dark"),
                  "menu_open": _in("menu_open", "menu_open#menu_version"), **geo},
        # Stage 3 of the glyph channel: the tracks read the stored glyph rows
        # (and the bank they were scored on) and the proposer's verify; the
        # verdict reads the tracks, the tray kit, the lineup's slots, and the
        # null and states tables at the code's versions, and the player's drawing
        # answers, compared by a digest of what the rule reads from them
        # (`ability_glyph.drawing_answers_stamp`), so an unrelated answer does
        # not restale it.
        "ability_disc_track": {"ability_glyph": _in("inputs.ability_glyph",
                                                    "ability_glyph#ability_glyph_version"),
                               "glyph_bank": _in("inputs.glyph_bank", "ability_glyph#glyph_bank"),
                               "ability_icon": _in("inputs.ability_icon",
                                                   "ability_icon#ability_icon_version")},
        "ability_glyph_name": {"ability_glyph": _in("inputs.ability_glyph",
                                                    "ability_glyph#ability_glyph_version"),
                               "glyph_bank": _in("inputs.glyph_bank", "ability_glyph#glyph_bank"),
                               "ability_disc_track": _code("inputs.ability_disc_track",
                                                           ABILITY_DISC_TRACK_VERSION),
                               "null_table": _code("inputs.null_table", GLYPH_DATA["null"][1]),
                               "states_table": _code("inputs.states_table", GLYPH_STATES_TABLE[1]),
                               "tray_kit": _in("inputs.tray_kit", "tray_kit#tray_kit_version"),
                               "drawing_answers": _in("inputs.drawing_answers",
                                                      "glyph_drawing_answers"),
                               **_lineup_inputs()},
        # The child owner reads every witness it may (`slot_state.CHANNELS`);
        # a dead Clove's smokes also read the player-cast gate's deaths and
        # revives, recorded only on a Clove player's session.
        "ability_child": {"ability_state": _in("inputs.ability_state",
                                               "ability_state#ability_state_version"),
                          "ult_cast": _in("inputs.ult_cast", "ult_cast#ult_cast_version"),
                          "smoke_owner": _in("inputs.smoke_owner",
                                             "smoke_owner#smoke_owner_version"),
                          "ability_shape": _in("inputs.ability_shape",
                                               "ability_shape#ability_shape_version"),
                          "ability_glyph_name": _in("inputs.ability_glyph_name",
                                                    "ability_glyph_name#ability_glyph_name_version"),
                          "ability_disc_track": _in("inputs.ability_disc_track",
                                                    "ability_disc_track#ability_disc_track_version",
                                                    optional=True),
                          "tray_kit": _in("inputs.tray_kit", "tray_kit#tray_kit_version",
                                          optional=True),
                          "tray_drop": _in("inputs.tray_drop", "tray_drop#tray_version",
                                           optional=True),
                          "death": _in("inputs.death", death),
                          "assist": _in("inputs.assist", "assist#assist_adjudication_version"),
                          "round": _in("inputs.round", "rounds"),
                          # the spawn tree and each node's sheet answers
                          # (`slot_state.ability_objects`): an answer edit restales it
                          "mechanics_sheet": _in("inputs.mechanics_sheet", "mechanics_sheet"),
                          **{f"dead_ruse_{k}": v for k, v in
                             _gate("inputs.dead_ruse_gate.", optional=True).items()},
                          **_lineup_inputs()},
        "ability_effect": {"ability_child": _in("inputs.ability_child",
                                                "ability_child#ability_child_version"),
                           "death": _in("inputs.death", death),
                           "assist": _in("inputs.assist", "assist#assist_adjudication_version"),
                           **_lineup_inputs()},
        "smoke_owner": {"smoke": _in("smoke_version", "smoke#smoke_version"),
                        "tray_drop": _in("inputs.tray_drop", "tray_drop#tray_version"),
                        "round": _in("inputs.round", "rounds"),
                        "clove_circle": _in("inputs.clove_circle",
                                            "clove_circle#clove_circle_version", optional=True),
                        **_gate(optional=True), **_lineup_inputs()},
        # The same command names the rows (`combat_report_identity`) over the
        # deaths, the killfeed portraits, the scoreboard and the lineup.
        "combat_report_round": {"combat_report": _in("combat_report_version", "combat_report"),
                                "round": _in("inputs.round", "rounds"),
                                "hud": _in("inputs.hud", "hud"),
                                "death": _in("inputs.death", death),
                                "killfeed_portrait": _in("inputs.killfeed_portrait",
                                                         "killfeed_portrait"),
                                "scoreboard": _in("inputs.scoreboard", "scoreboard"),
                                # The self-entry rule a reportless round's
                                # verdict was read by (`own_counts`).
                                "self_entry": _code("inputs.self_entry", SELF_ENTRY_VERSION,
                                                    optional=True),
                                **_lineup_inputs()},
        "self_entry": {"death": _in("inputs.death", "death#death_adjudication_version"),
                       **_lineup_inputs()},
        "tray_kit": {"catalogue": _in("inputs.catalogue", "catalogue_icons"), **_lineup_inputs()},
        "ability_light": geo,
        # The owner gate reads the stored pings (`minimap_objects.stored_pings`);
        # heads before minimap-object-0.2.0 read none.
        # From minimap-object-0.7.0 the portrait gate reads the lineup's enemy
        # candidate set and the rendered-art references.
        "minimap_object": {**geo, "ping": _in("inputs.ping", "ping", optional=True),
                           "lineup_file": _in("inputs.lineup_file", "lineup_file", optional=True),
                           "lineup": _in("inputs.lineup_view", "lineup", optional=True),
                           "portrait_refs": _in("inputs.portrait_refs", "portrait_refs",
                                                optional=True)},
        "minimap_dark": {"lighting": _code("lighting_version", LIGHTING_VERSION),
                         "spans": _spans(), **geo},
        # Pings are formal entity events: the first event's metadata carries
        # the spans. A read that confirmed none writes one coverage row in
        # their place (`PingReader.events`), and its `metadata` carries them.
        "ping": {"spans": _in("metadata.spans", "spans", before="seg-0.2.0")},
        # The ally icons are read through the teardrop; heads before
        # `ally-icon-0.6.0` do not record it.
        "ally_icon": {"teardrop": _code("teardrop_version", TEARDROP_VERSION, optional=True),
                      "icon_teardrop": _code("icon_teardrop_version", ICON_TEARDROP_VERSION,
                                             optional=True),
                      # Heads before `ally-icon-0.7.0` searched every image in full.
                      "icon_pose_prior": _code("icon_pose_prior_version",
                                               ICON_POSE_PRIOR_VERSION, optional=True),
                      # From `ally-icon-0.11.0` the stacked-icon search runs
                      # where the stored roster's capacity exceeds the ring
                      # fits (`minimap.StackGate`); a head whose gate read no
                      # roster records neither.
                      "stack_fit": _code("stack_fit_version", STACK_FIT_VERSION, optional=True),
                      "roster": _in("inputs.roster", "roster", optional=True),
                      "spans": _spans()},
        "ability_gate": {"spans": _spans(), **geo}, "ability_icon": {"spans": _spans(), **geo},
        # The circle's windows are the stored deaths' and rounds'
        # (`clove_circle.stored_windows`).
        "clove_circle": {"death": _in("inputs.death", death),
                         "round": _in("inputs.round", "rounds"), **geo},
        # The glyph reader's context set is the lineup's (`lineup.glyph_candidates`).
        "ability_glyph": {"spans": _spans(), **geo, **_lineup_inputs()},
        "ability_shape_scan": {"shape_model": _code("ability_shape_version", ABILITY_SHAPE_VERSION),
                               "spans": _spans(), **geo},
        # The audit also runs the candidate path's fit on each sample to count
        # `candidate_accepted`, so the fit rule is an input beside the shape model.
        "ability_shape_audit": {"shape_model": _code("ability_shape_version",
                                                     ABILITY_SHAPE_VERSION),
                                "candidate_fit": _code("ability_fit_version", ABILITY_FIT_VERSION),
                                **geo},
        # The assist panel [domain:killfeed/assist-panel] reads the stored
        # deaths' killer views and the killfeed reader's anchors, matched to
        # one game build's art; its verdicts rest on the same deaths and name
        # icons from the kits table.
        "killfeed_assist": {"death": _in("inputs.death", death),
                            "killfeed_portrait": _in("inputs.killfeed_portrait",
                                                     "killfeed_portrait"),
                            "game_build": _code("inputs.game_build", ICON_BUILD),
                            **_lineup_inputs()},
        "assist": {"death": _in("inputs.death", death),
                   "killfeed_kits": _code("inputs.killfeed_kits", KILLFEED_KITS_VERSION),
                   **_lineup_inputs()},
        "enemy_track": {"minimap_object": _in("minimap_object_version",
                                              "minimap_object#minimap_object_version"),
                        # The glyph verdicts `detection_reality` weighs, by
                        # their content stamp (`input_stamps.content_stamp`):
                        # the verdict's code stamp alone would miss a rerun of
                        # `reticle ability-glyphs` over moved inputs, the
                        # `ability_fit` failure above. A head written before
                        # enemy-track-0.3.0 read none.
                        "ability_glyph_name": _in("inputs.ability_glyph_name",
                                                  "ability_glyph_name#ability_glyph_name_version"
                                                  "+inputs", before="no_rows"),
                        "death": _in("death_adjudication_version", death),
                        "portrait_refs": _in("references_version", "portrait_refs"),
                        **_lineup_inputs(file_path="lineup_version")},
    }


def _probe_stream(probe: str) -> str | None:
    """The stored stream (or table) a probe reads, for staleness to follow."""
    if probe.startswith("="):
        return None
    if "#" in probe:
        return probe.split("#", 1)[0]
    if probe in ("geometry", "lineup_file", "reliability", "catalogue", "catalogue_icons",
                 "portrait_refs", "portrait_refs_fit", "audio_features", "audio_labels",
                 "glyph_drawing_answers", "mechanics_sheet"):
        return None
    return probe


def input_streams(stream: str) -> set[str]:
    """The stored streams a stream's declared inputs read (`lineup` stands for
    the view, which moves with `self_icon` and `scoreboard`)."""
    return {s for d in stream_inputs().get(stream, {}).values()
            if (s := _probe_stream(d["probe"])) is not None}


#: The stored tables a probe reads that are built from stored streams, and
#: the streams (or tables) each folds. A table no entry names is built from
#: no stored stream (geometry, the lineup file, the catalogue, the rendered
#: portrait art).
TABLE_SOURCES = {
    # The plants are read from a current `plant_graphic` stream (`_round_stamps`).
    "rounds": ("hud", "killfeed_portrait", "plant_graphic"),
    "lineup": ("lineup_file", "self_icon", "scoreboard"),
    "reliability": ("death",),
    # `prototypes/ally_teammate_fit.py` fits the threshold on the deaths
    # bound to the ally icons.
    "portrait_refs_fit": ("portrait_refs", "hud", "roster", "death", "ally_icon", "lineup"),
}

#: (stream, input name) -> why the stream reads a table built from its own
#: output. Each runs once: its probe stamps the table by the rule of the
#: stream it was built over, never by its bytes, so one rebuild and one rerun
#: agree. Every other loop in the input graph is an error (`input_cycles`).
FEEDBACK = {
    ("death", "reliability_table"): "the channel reliabilities are measured on the stored "
                                    "deaths and weigh the name clusters; compared by the "
                                    "death rule they were measured on "
                                    "(`reliability.built_from`)",
    ("death", "assist"): "the assist verdicts are read over the stored deaths and joined "
                         "back by death id only when they rest on this death rule "
                         "(`death.assist_stamp`); a head that joined none records why, "
                         "so deaths, then assists, then deaths once more agree",
    ("tray_drop", "ult_cast"): "the cast gate reads the player's own ult lines that rest on "
                               "no tray cast (`ability_timeline.own_line_times`), which "
                               "`ult_cast` selects by score before it binds any tray cast; "
                               "compared by the ult-cast rule, so tray, then ult-cast, "
                               "then tray once more agree",
}


def _probe_node(probe: str) -> str | None:
    """The node a probe reads in the input graph: a stream or a table."""
    return None if probe.startswith("=") else probe.split("#", 1)[0]


def input_graph(feedback: bool = False) -> dict[str, set[str]]:
    """node -> the nodes it is built from: each stream's declared inputs and
    `upstream`, and each table's `TABLE_SOURCES`. The `FEEDBACK` edges are
    left out unless `feedback`."""
    graph: dict[str, set[str]] = {}
    for stream, inputs in stream_inputs().items():
        for name, d in inputs.items():
            node = _probe_node(d["probe"])
            if node is not None and (feedback or (stream, name) not in FEEDBACK):
                graph.setdefault(stream, set()).add(node)
    for spec in derived_streams():
        graph.setdefault(spec["stream"], set()).update(spec.get("upstream", ()))
    for table, sources in TABLE_SOURCES.items():
        graph.setdefault(table, set()).update(sources)
    return graph


def input_cycles(graph: dict[str, set[str]] | None = None) -> list[list[str]]:
    """Every simple cycle of `graph` (default `input_graph()`), each from its
    least node and back to it. A cycle is a stream whose rerun moves its own
    input, so `plan` never comes clean."""
    graph = input_graph() if graph is None else graph
    nodes = sorted(set(graph) | {m for v in graph.values() for m in v})
    order = {n: i for i, n in enumerate(nodes)}
    cycles = []
    for start in nodes:
        stack = [(start, [start])]
        while stack:
            at, path = stack.pop()
            for nxt in sorted(graph.get(at, ()), reverse=True):
                if nxt == start:
                    cycles.append(path + [start])
                elif order[nxt] > order[start] and nxt not in path:
                    stack.append((nxt, path + [nxt]))
    return cycles


def order_graph() -> tuple[dict[str, set[str]], dict[str, str]]:
    """(graph, fold): `input_graph` with each entity lane's consumer stream
    built from its lane's inputs, and each identity stream folded into the
    stream whose command writes it (`fold`: identity stream -> parent), so
    the two order as one."""
    from .entity_events import ENTITY_LANES, lane_streams
    graph = input_graph()
    for spec in ENTITY_LANES:
        graph.setdefault(lane_streams(spec["lane"])[0], set()).update(spec["inputs"])
    graph.setdefault("replay_layer", set()).update(REPLAY_LAYER_INPUTS)
    graph.setdefault("episodes", set()).update(EPISODES_INPUTS)
    fold = {s["stream"]: s["upstream"][0] for s in derived_streams() if s.get("identity")}
    out: dict[str, set[str]] = {}
    for node, deps in graph.items():
        at = fold.get(node, node)
        out.setdefault(at, set()).update(fold.get(d, d) for d in deps)
        out[at].discard(at)
    return out, fold


def build_order(streams: list[str], graph: dict[str, set[str]] | None = None) -> list[str]:
    """`streams` reordered so each follows every listed stream it is built
    from, directly or through streams not listed (default graph
    `order_graph`). Streams with no such tie keep their given order, and so
    do the members of a loop: `input_cycles` fails the tests on one, never
    the user."""
    graph = order_graph()[0] if graph is None else graph
    streams = list(dict.fromkeys(streams))
    ancestors: dict[str, set[str]] = {}
    for s in streams:
        seen, stack = set(), list(graph.get(s, ()))
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(graph.get(n, ()))
        ancestors[s] = seen
    # Ancestry is transitive, so dropping the mutual pairs (a loop) leaves a
    # strict partial order, and the scan below always finds a ready stream.
    before = {s: {a for a in streams if a != s and a in ancestors[s]
                  and s not in ancestors[a]} for s in streams}
    out: list[str] = []
    left = list(streams)
    while left:
        ready = next(s for s in left if before[s] <= set(out))
        out.append(ready)
        left.remove(ready)
    return out


_MISSING = object()


def _dig_missing(row: dict, path: str):
    for part in path.split("."):
        if not isinstance(row, dict) or part not in row:
            return _MISSING
        row = row[part]
    return row


def input_head(store, manifest: dict, probe: str, head: dict | None = None,
               memo: dict | None = None) -> str:
    """The stamp the input `probe` carries as stored now, `no_rows` where it
    holds none. `head` is the reading stream's first row (its `geometry_key`
    names the geometry); `memo` caches across one session's checks."""
    from . import input_stamps as ist
    if probe.startswith("="):
        return probe[1:]
    key = (probe, (head or {}).get("geometry_key") if probe == "geometry" else None)
    if memo is not None and key in memo:
        return memo[key]
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    root = getattr(store, "root", None)
    if "#" in probe:
        stream, field = probe.split("#", 1)
        row = ist.head_row(store, stream, sid)
        if field.endswith(ist.CONTENT):
            now = ist.content_stamp(row, field[:-len(ist.CONTENT)])
        else:
            now = ist.NO_ROWS if row is None else (row.get(field) or "unstamped")
    elif probe == "rounds":
        now = ist.table_stamp(store.rounds_path(sid, date), "round_version")
    elif probe == "spans":
        path_of = getattr(store, "spans_path", None)   # a test store may hold none
        now = (ist.table_stamp(path_of(sid, date), "segmenter_version") if path_of is not None
               else ist.NO_ROWS)
    elif probe == "geometry":
        from . import geometry
        gkey = (head or {}).get("geometry_key")
        if gkey is None and root is not None:
            gkey = geometry.key_of(sid, root)
        now = ist.geometry_stamp(root, gkey)
    elif probe == "lineup":
        from .lineup import view_stamp
        now = view_stamp(sid, root) if root is not None else ist.NO_ROWS
    elif probe == "lineup_file":
        f = root / "lineups" / f"{sid}.json" if root is not None else None
        now = (json.loads(f.read_text(encoding="utf-8")).get("version") or "unstamped"
               if f is not None and f.is_file() else ist.NO_ROWS)
    elif probe == "reliability":
        # Built from the deaths that read it: compared by the death rule it
        # was built over, not by its bytes (`FEEDBACK`).
        from .adjudication.reliability import built_from
        now = (built_from(root) if root is not None else None) or ist.NO_ROWS
    elif probe == "catalogue":
        from .adjudication.ability_state import CATALOGUE_PATH
        f = root / CATALOGUE_PATH if root is not None else None
        now = (f"{CATALOGUE_PATH}@{json.loads(f.read_text(encoding='utf-8')).get('harvested')}"
               if f is not None and f.is_file() else f"absent:{CATALOGUE_PATH}")
    elif probe == "catalogue_icons":
        f = root / "reference" / "abilities.json" if root is not None else None
        if f is not None and f.is_file():
            from .tray_icons import reference_key
            now = f"reference/abilities.json#{reference_key(root)}"
        else:
            now = ist.NO_ROWS
    elif probe == "mechanics_sheet":
        from .mechanics_sheet import sheet_stamp
        now = sheet_stamp(root) if root is not None else ist.NO_ROWS
    elif probe == "glyph_drawing_answers":
        from .adjudication.ability_glyph import drawing_answers_stamp
        now = drawing_answers_stamp(root) if root is not None else ist.NO_ROWS
    elif probe in ("audio_features", "audio_labels"):
        from .ability_timeline import audio_input_stamps
        now = audio_input_stamps(root, sid)[probe] if root is not None else ist.NO_ROWS
    elif probe in ("portrait_refs", "portrait_refs_fit"):
        table = None
        if root is not None:
            from .adjudication.identity import load_ally_portrait_references
            table = load_ally_portrait_references(root)
        now = (table or {}).get("version") or ist.NO_ROWS
        if probe == "portrait_refs_fit" and (table or {}).get("teammate_fit"):
            now = f"{now}+{table['teammate_fit'].get('version')}"
    else:
        now = stored_stamp(store, manifest, probe) or ist.NO_ROWS
    if memo is not None:
        memo[key] = now
    return now


def inputs_moved(store, manifest: dict, stream: str, head: dict, memo: dict | None = None,
                 accepted=None) -> tuple[list[str], list[str]]:
    """(the declared inputs of `stream` whose stamp recorded in `head` no
    longer matches the input as stored now, the declared inputs `head` does
    not record). The one comparison of recorded inputs `stale` makes.

    A recorded stamp moved when it differs from the stored head, and a
    recorded `no_rows` once rows exist. A recorded None is an input the writer
    did not read, except where an older writer recorded None for an input
    that was not at the code's stamp (`use_when`) and now is. `accepted`
    (`stale`'s waiver check) may accept a recorded stamp as the stored one."""
    from .input_stamps import NO_ROWS, moved as stamp_moved, normalize
    moved, unrecorded = [], []
    for name, d in stream_inputs().get(stream, {}).items():
        rec = _dig_missing(head, d["path"])
        if rec is _MISSING and d.get("before") is not None:
            # A head older than the record read the input at `before`, where
            # the input is stored at all.
            if input_head(store, manifest, d["probe"], head, memo) == NO_ROWS:
                continue
            rec = d["before"]
        if rec is _MISSING:
            if not d["optional"]:
                unrecorded.append(name)
            continue
        now = input_head(store, manifest, d["probe"], head, memo)
        if normalize(rec) is None:
            if d["use_when"] is not None and normalize(now) == d["use_when"]:
                moved.append(name)
            continue
        if stamp_moved(rec, now) and not (accepted is not None and accepted(
                f"{stream} input {name}", normalize(rec), normalize(now))):
            moved.append(name)
    return moved, unrecorded


def record_inputs(store, manifest: dict, stream: str, head: dict) -> dict:
    """Record in `head`, a stream's first row about to be written, the stored
    stamp of every declared input of `stream` the writer did not record
    itself, and the widget placement a widget-reading stream read through
    (`record_placement`). An optional input is recorded only by the writer,
    where it read it. Returns `head`."""
    for d in stream_inputs().get(stream, {}).values():
        if d["optional"] or _dig_missing(head, d["path"]) is not _MISSING:
            continue
        *parents, leaf = d["path"].split(".")
        at = head
        for part in parents:
            at = at.setdefault(part, {})
        at[leaf] = input_head(store, manifest, d["probe"], head)
    return record_placement(manifest, stream, head)


def recorded_stale(store, manifest: dict, spec: dict, head: dict, memo: dict | None = None,
                   accepted=None) -> tuple[bool, list[str], list[str]]:
    """(behind, moved, unrecorded) of one `derived_streams` spec by what its
    stored first row `head` records alone: its own stamp behind the code's,
    each rule stamp in `spec["fields"]` the code has moved past, each declared
    stored input that moved since it was read (`inputs_moved`) and, for a cone
    stream, the occluder table. `unrecorded` names the declared inputs `head`
    does not record.

    `stale` adds the inputs still waiting on a rerun (`upstream_names`);
    `scan` asks this alone before it rereads, so the command `plan` prints
    rereads what `plan` calls stale once the inputs ahead of it are rerun.
    `accepted` is `stale`'s waiver check; by default a declared waiver accepts."""
    if accepted is None:
        accepted = lambda where, stored, current: waiver(stored, current, store, manifest,
                                                         memo) is not None
    stream = spec["stream"]
    moved = sorted(k for k, v in spec["fields"].items() if _dig(head, k) not in (v, None)
                   and not accepted(f"{stream} input {k}", _dig(head, k), v))
    got, missing = inputs_moved(store, manifest, stream, head, memo, accepted)
    moved += [k for k in got if k not in moved]
    if spec.get("occluders"):
        # A stream cast over an older occluder table, or over none where the
        # geometry now holds one, is stale.
        now = geometry_occluders(store, head.get(spec["occluders"]))
        if now is not None and head.get("occluders") != now:
            moved.append("occluders")
    version = head.get(spec["key"])
    behind = version != spec["current"] and not accepted(stream, version, spec["current"])
    return behind, moved, missing


def spans_read_moved(store, manifest: dict, stream: str, memo: dict | None = None) -> bool:
    """Whether a span reader's stored stream (`SPAN_READERS`) read other spans
    than the stored spans table holds now. The minimap table records the
    stamp in its schema metadata, the event streams in their head
    (`_spans`); a stream written before either read `before`."""
    from .input_stamps import NO_ROWS
    now = input_head(store, manifest, "spans", None, memo)
    if now == NO_ROWS:
        return False
    if stream == "minimap":
        read = _table_stamp(store.minimap_path(manifest["session_id"],
                                               manifest["ingested_at"][:10]), "segmenter_version")
        if read is None:
            return False
        return (_spans()["before"] if read == "unstamped" else read) != now
    head = _head(store, stream, manifest["session_id"])
    return head is not None and "spans" in inputs_moved(store, manifest, stream, head, memo)[0]


def geometry_occluders(store, key: str | None) -> str | None:
    """The `occ_built_by` of the baked geometry `key` holds now, or None when
    the npz or its occluder table is missing."""
    root = getattr(store, "root", None)
    if key is None or root is None:
        return None
    from . import geometry
    path = geometry.path(key, root)
    if not path.is_file():
        return None
    import numpy as np
    with np.load(path, allow_pickle=False) as z:
        if "occ" not in z.files:
            return None
        return str(z["occ_built_by"]) if "occ_built_by" in z.files else "unstamped"


def _dig(row: dict, path: str):
    for part in path.split("."):
        row = row.get(part) if isinstance(row, dict) else None
    return row


def stored_streams(store, sid: str) -> list[str]:
    """The event streams stored for a session, from the store's own layout."""
    root = getattr(store, "root", None)
    events = root / "events" if root is not None else None
    if events is None or not events.is_dir():
        return []
    return sorted(d.name for d in events.iterdir() if (d / f"{sid}.jsonl").is_file())


def stored_stamp(store, manifest: dict, stream: str) -> str | None:
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    if stream == "hud":
        return _table_stamp(store.hud_path(sid, date), "hud_version")
    if stream == "minimap":
        return _table_stamp(store.minimap_path(sid, date), "minimap_version")
    if stream == "roster":
        return _table_stamp(store.roster_path(sid, date), "roster_version")
    return store.events_version(stream, sid)


def upstream_names(stream: str, upstream, moving: set[str], head: dict | None) -> list[str]:
    """The inputs of `stream` that are stale now, so it will move once they are
    refreshed: each declared input (by its name) whose stream is in `moving`
    and which `head` read, and each further stream named in `upstream`. The
    lineup view moves with the `self_icon` rows and the scoreboard it folds in."""
    from .input_stamps import normalize
    moving = moving | ({"lineup"} if moving & {"self_icon", "scoreboard"} else set())
    declared = stream_inputs().get(stream, {})
    names, covered = [], set()
    for name, d in declared.items():
        s = _probe_stream(d["probe"])
        if s is None:
            continue
        covered.add(s)
        rec = _dig_missing(head or {}, d["path"])
        # An input the head records as not read, or an optional one it does
        # not record, is not followed.
        if (rec is _MISSING and d["optional"]) or (rec is not _MISSING and normalize(rec) is None):
            continue
        if s in moving and name not in names:
            names.append(name)
    names += [u for u in upstream if u in moving and u not in covered and u not in names]
    return sorted(names)


def _hand_specs() -> dict[str, dict]:
    """The key, current stamp, command and reads of each hand-checked stream,
    for `_follow`."""
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    from .adjudication.scoreboard import SCOREBOARD_AGENT_VERSION
    from .version import (ABILITY_SHAPE_VERSION, ABILITY_STATE_VERSION, SCOREBOARD_STRIP_VERSION,
                          SELF_ICON_VERSION, TRAY_VERSION, ULT_CAST_VERSION)
    return {
        "death": ("death_adjudication_version", DEATH_ADJUDICATION_VERSION, "reticle deaths {sid}"),
        "ult_cast": ("ult_cast_version", ULT_CAST_VERSION, "reticle ult-cast {sid}"),
        "tray_drop": ("tray_version", TRAY_VERSION, "reticle tray {sid}"),
        "ability_shape": ("ability_shape_version", ABILITY_SHAPE_VERSION,
                          "reticle ability-shapes {sid}"),
        "scoreboard_strip": ("scoreboard_strip_version", SCOREBOARD_STRIP_VERSION,
                             "reticle strip {sid}"),
        "scoreboard_presence": ("scoreboard_presence_version", SCOREBOARD_AGENT_VERSION,
                                "reticle openings {sid}"),
        "ability_state": ("ability_state_version", ABILITY_STATE_VERSION,
                          "reticle ability-state {sid}"),
        "self_icon": ("self_icon_version", SELF_ICON_VERSION, "reticle self-icon {sid}"),
    }


def hand_code_fields() -> dict[str, dict[str, tuple[str, str]]]:
    """stream -> {name: (head path, the code's stamp)}: the rule stamps each
    hand-checked stream records beside its inputs, which `stale` compares with
    the code rather than with anything stored."""
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    from .adjudication.identity import AGENT_IDENTITY_VERSION
    from .adjudication.killfeed_names import KILLFEED_NAME_CLUSTER_VERSION
    from .adjudication.reliability import RELIABILITY_VERSION
    from .adjudication.scoreboard import SCOREBOARD_AGENT_VERSION
    from .adjudication.weapon import WEAPON_ADJUDICATION_VERSION, WEAPON_GALLERY_VERSION
    from .killfeed import KILLFEED_NAME_VERSION, KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
    from .minimap_objects import minimap_object_version
    from .roi_cache import ROI_CACHE_VERSION
    from .blinds import BLIND_VERSION
    from .stalls import STALL_VERSION
    from .version import (ALLY_ICON_VERSION, ALLY_PORTRAIT_FEATURES_VERSION,
                          COMBAT_REPORT_ROUND_VERSION, HUD_VERSION, PLAYER_CAST_VERSION,
                          ROUND_VERSION, SCOREBOARD_STRIP_VERSION, SCOREBOARD_VERSION,
                          SPIKE_VERSION, TEARDROP_VERSION, TRAY_SEGMENT_VERSION, TRAY_VERSION,
                          ULT_LINE_VERSION)
    gate = {"player_cast": ("player_cast_version", PLAYER_CAST_VERSION)}
    tray = {"tray_drop": ("tray_version", TRAY_VERSION)}
    roi = {"roi_cache": ("roi_cache_version", ROI_CACHE_VERSION)}
    death = {"hud": HUD_VERSION, "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
             "killfeed_weapon": KILLFEED_WEAPON_VERSION,
             "killfeed_name": KILLFEED_NAME_VERSION, "round": ROUND_VERSION,
             "scoreboard": SCOREBOARD_VERSION, "agent_identity": AGENT_IDENTITY_VERSION,
             "minimap_object": minimap_object_version(), "ally_icon": ALLY_ICON_VERSION,
             # The rules the verdicts pass through, recorded since 2026-09-30.
             "weapon_adjudication": WEAPON_ADJUDICATION_VERSION,
             "weapon_gallery": WEAPON_GALLERY_VERSION,
             "killfeed_name_cluster": KILLFEED_NAME_CLUSTER_VERSION,
             "scoreboard_agent": SCOREBOARD_AGENT_VERSION,
             "reliability": RELIABILITY_VERSION,
             # The stall rule over the stored motion and clock; the deaths it
             # infers come from the stalls (recorded None where unread).
             "stalls": STALL_VERSION,
             # The blind rule over the stored primitives: a wash hides the
             # killfeed without expiring an entry (recorded None where unread).
             "blinds": BLIND_VERSION}
    ult = {"ult_line": ULT_LINE_VERSION, "round": ROUND_VERSION, "tray_drop": TRAY_VERSION,
           "hud": HUD_VERSION, "player_cast": PLAYER_CAST_VERSION,
           "death": DEATH_ADJUDICATION_VERSION, "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
           "combat_report_round": COMBAT_REPORT_ROUND_VERSION}
    return {
        "death": {k: ("inputs." + k, v) for k, v in death.items()},
        "ult_cast": {k: ("inputs." + k, v) for k, v in ult.items()},
        # The stream's `segments` rows carry the half classes' own stamp.
        "tray_drop": {**gate, "tray_segment": ("tray_segment_version", TRAY_SEGMENT_VERSION)},
        "ability_shape": {**gate, **tray},
        "scoreboard_strip": roi,
        "scoreboard_presence": {"scoreboard_strip": ("scoreboard_strip_version",
                                                     SCOREBOARD_STRIP_VERSION),
                                "scoreboard": ("scoreboard_version", SCOREBOARD_VERSION)},
        "ability_state": {**gate, **tray},
        # The self icon rereads the stored minimap crops over the roster's
        # alive gate; a reread roster moves its gate.
        "self_icon": {**roi, "portrait_features": ("portrait_features_version",
                                                   ALLY_PORTRAIT_FEATURES_VERSION),
                      "spike": ("spike_version", SPIKE_VERSION),
                      "teardrop": ("teardrop_version", TEARDROP_VERSION)},
    }


def compared_paths() -> dict[str, set[str]]:
    """stream -> every head path `stale` compares for it: its own stamp, its
    declared inputs (`stream_inputs`), and the code stamps it records
    (`hand_code_fields`, `derived_streams`' fields). `doctor` INPUTS reads it."""
    out: dict[str, set[str]] = defaultdict(set)
    for stream, *_ in reader_streams():
        # A reader that writes formal entity events (`ping`) carries its stamp
        # as `producer_version`, which `Store.events_version` reads in place
        # of the absent `<stream>_version`.
        out[stream] |= {f"{stream}_version", "producer_version"}
    for stream, (key, _, _) in _hand_specs().items():
        out[stream].add(key)
    for stream, fields in hand_code_fields().items():
        out[stream] |= {path for path, _ in fields.values()}
    for spec in derived_streams():
        out[spec["stream"]] |= {spec["key"], *spec["fields"]}
        if spec.get("occluders"):
            out[spec["stream"]] |= {"occluders", spec["occluders"]}
    for stream, declared in stream_inputs().items():
        out[stream] |= {d["path"] for d in declared.values()}
    for stream in widget_streams():
        out[stream].add(WIDGET_INPUT)
    return dict(out)


def _follow(store, sid: str, derived: list[dict], moving: set[str]) -> None:
    """Carry staleness along every declared input until nothing more moves.

    The hand checks run before the declared streams, so `ability_state`
    (checked by hand) once never saw that `tray_kit` (declared later) was
    stale. Here each stream with a stale input is listed, or its listed entry
    names the input, whatever order the checks ran in."""
    hand = {s: {"key": k, "current": c, "command": cmd, "how": _CACHE_READERS.get(s, "storage"),
                "upstream": ()} for s, (k, c, cmd) in _hand_specs().items()}
    specs = {**hand, **{s["stream"]: s for s in derived_streams()}}
    by_stream = {d["stream"]: d for d in derived}
    heads: dict[str, dict | None] = {}
    changed = True
    while changed:
        changed = False
        for stream, spec in specs.items():
            if stream not in heads:
                heads[stream] = (_head(store, stream, sid, b'"event_kind":"identity_distribution"')
                                 if spec.get("identity") else _head(store, stream, sid))
            head = heads[stream]
            if head is None:
                continue
            names = upstream_names(stream, spec.get("upstream", ()), moving, head)
            if not names:
                continue
            entry = by_stream.get(stream)
            if entry is not None:
                entry["inputs_moved"] += [n for n in names if n not in entry["inputs_moved"]]
                continue
            entry = {"stream": stream, "stored": head.get(spec["key"]),
                     "current": spec["current"], "inputs_moved": names, "how": spec["how"],
                     "command": spec["command"].format(sid=sid)}
            derived.append(entry)
            by_stream[stream] = entry
            moving.add(stream)
            changed = True


#: The `inputs_moved` reason of a derived stream the session never wrote.
NEVER_RUN = "never run"


def _coverage_head(store, sid: str, stream: str) -> dict | None:
    """The stamped coverage row heading a stored stream, or None."""
    head = _head(store, stream, sid)
    if head is None or head.get("kind") != "coverage" or "producer_version" not in head:
        return None
    return head


def _empty_run_head(store, sid: str, spec: dict) -> dict | None:
    """The coverage row of `spec["written_with"]` where it counts no identity
    event, standing for the empty identity stream's head; None where that
    stream holds none or counts events the identity stream lacks."""
    head = _coverage_head(store, sid, spec["written_with"])
    if head is None or head.get("identity_events") != 0:
        return None
    return head


def stale(store, sessions: list[str], never_run: bool = True) -> dict:
    """Per session: stale reader streams (decode), stale adjudications
    (storage only), and absent streams. With `never_run` (every command's
    default) a derived stream the session never wrote is listed as work too,
    and the streams built from it follow it; tests of one staleness rule turn
    it off to read that rule alone."""
    from .adjudication.death import DEATH_ADJUDICATION_VERSION
    from .input_stamps import NO_ROWS
    from .killfeed import KILLFEED_PORTRAIT_VERSION
    from .minimap_objects import minimap_object_version
    from .version import (HUD_VERSION, PLANT_GRAPHIC_VERSION, ROUND_VERSION, SEGMENTER_VERSION,
                          TRAY_VERSION, ULT_CAST_VERSION)
    code_fields = hand_code_fields()
    out = {}
    for sid in sessions:
        man = store.read_manifest(sid)
        decode, derived, absent, waived, unrecorded, declined = [], [], [], [], [], []
        not_applicable = []
        memo: dict = {}

        def accepted(where: str, stored, current: str) -> bool:
            """True where a waiver accepts `stored` as `current`, and records
            it; a conditional waiver that declines here is recorded too."""
            why, no = waiver_check(stored, current, store, man, memo)
            if why is not None:
                waived.append({"stream": where, "stored": stored, "current": current,
                               "why": why})
            elif no is not None:
                declined.append({"stream": where, "stored": stored, "current": current,
                                 "why": no})
            return why is not None

        def recorded_moved(stream: str, head: dict | None, moved: list[str]) -> list[str]:
            """`moved` with every declared input of `stream` whose recorded
            stamp no longer matches the stored input (`inputs_moved`); the
            inputs `head` does not record go to `unrecorded`."""
            if head is None:
                return moved
            got, missing = inputs_moved(store, man, stream, head, memo, accepted)
            if missing:
                unrecorded.append({"stream": stream, "inputs": missing})
            return moved + [k for k in got if k not in moved]

        # The spans the minimap readers read: a table stamped by the segmenter
        # that wrote it, rebuilt from stored L1 by `reticle segment`. Each
        # span reader is stale while they are, and once rebuilt it reads as
        # moved against the stamp its head recorded (`_spans`).
        spans_now = input_head(store, man, "spans", None, memo)
        spans_stale = spans_now not in (SEGMENTER_VERSION, NO_ROWS)
        if spans_stale:
            derived.append({"stream": "spans", "stored": spans_now, "current": SEGMENTER_VERSION,
                            "inputs_moved": [], "how": "storage",
                            "command": f"reticle segment {sid}"})
        for stream, channel, now, trial in reader_streams():
            got = stored_stamp(store, man, stream)
            if got is None:
                absent.append(stream)
            elif got != now and not accepted(stream, got, now):
                decode.append({"stream": stream, "channel": channel, "stored": got,
                               "current": now, "trial": trial})
            elif stream == "minimap":
                # A table: its schema metadata records the spans' stamp.
                if spans_stale or spans_read_moved(store, man, stream, memo):
                    decode.append({"stream": stream, "channel": channel, "stored": got,
                                   "current": now, "trial": trial, "inputs_moved": ["spans"]})
            elif stream in stream_inputs():
                # A reader that read a stored input (`minimap_dark`, the baked
                # geometry) rereads when that input moved.
                moved = recorded_moved(stream, _head(store, stream, sid), [])
                if spans_stale and stream in SPAN_READERS and "spans" not in moved:
                    moved.append("spans")
                if moved:
                    decode.append({"stream": stream, "channel": channel, "stored": got,
                                   "current": now, "trial": trial, "inputs_moved": moved})
        # A side-based widget read without its placement, or through a crop
        # that cannot hold it (`widget_work`): every stored stream that read
        # the widget's pixels rereads after the placement and the crop are fixed.
        widget = widget_work(store, man)
        # A stream read through another placement than the stored one moved
        # with it, though no stamp moved (`placement_moved`).
        placed = {s: why for s in widget_streams()
                  if (why := placement_moved(store, man, s)) is not None}
        if widget is not None or placed:
            by = {s["stream"]: s for s in decode}
            for stream, channel, now, trial in reader_streams():
                if stream not in WIDGET_PIXEL_READERS or stream in absent:
                    continue
                if widget is None and stream not in placed:
                    continue
                if WIDGET_INPUT in by.get(stream, {}).get("inputs_moved", ()):
                    continue
                if stream in by:
                    by[stream].setdefault("inputs_moved", []).append(WIDGET_INPUT)
                else:
                    decode.append({"stream": stream, "channel": channel,
                                   "stored": stored_stamp(store, man, stream), "current": now,
                                   "trial": trial, "inputs_moved": [WIDGET_INPUT]})
        # A reader stream never written where its pass can run is owed
        # (`NEVER_RUN_READERS`); like a derived stream never run, it moves
        # nothing downstream until it is written.
        for stream, channel, now, trial in reader_streams():
            needs = NEVER_RUN_READERS.get(stream)
            if (never_run and needs is not None and stream in absent
                    and stored_stamp(store, man, needs) is not None):
                absent.remove(stream)
                decode.append({"stream": stream, "channel": channel, "stored": None,
                               "current": now, "trial": trial, "inputs_moved": [NEVER_RUN]})
        # A cache-fed reader's reread reads the stored crop cache, no decode.
        fed: dict[str, tuple[str | None, str]] = {}
        for s in decode:
            if s["stream"] in CACHE_FED_READERS:
                if s["channel"] not in fed:
                    fed[s["channel"]] = (_channel_cache(store, man, s["channel"])
                                         if man.get("source_profile")
                                         else (None, "no_source_profile"))
                if fed[s["channel"]][0] is not None:
                    s["cache_fed"] = fed[s["channel"]][0]
        rescanned = {s["stream"] for s in decode if s.get("inputs_moved") != [NEVER_RUN]}
        rounds_stale = False
        r = _round_stamps(store, man)
        if r is not None:
            # Second lives are read only from a current portrait stream, so a
            # rebuild now would record the current stamp or none.
            portrait = (KILLFEED_PORTRAIT_VERSION if store.events_version("killfeed_portrait", sid)
                        == KILLFEED_PORTRAIT_VERSION else "none")
            # Plants are read only from a current graphic stream, likewise.
            graphic = (PLANT_GRAPHIC_VERSION if store.events_version("plant_graphic", sid)
                       == PLANT_GRAPHIC_VERSION else "none")
            moved = [k for k, v in (("hud", HUD_VERSION), ("killfeed_portrait", portrait),
                                    ("plant_graphic", graphic))
                     if r[k] != v or k in rescanned]
            if r["round"] != ROUND_VERSION or moved:
                rounds_stale = True
                derived.append({"stream": "rounds", "stored": r["round"], "current": ROUND_VERSION,
                                "inputs_moved": moved, "command": f"reticle rounds {sid}"})
        hand = _hand_specs()

        def list_never_run(stream: str) -> None:
            """A hand-checked stream the session never wrote, as work."""
            if not never_run:
                return
            _key, current, command = hand[stream]
            derived.append({"stream": stream, "stored": None, "current": current,
                            "inputs_moved": [NEVER_RUN], "command": command.format(sid=sid),
                            "how": _CACHE_READERS.get(stream, "storage")})

        dhead = _head(store, "death", sid)
        if dhead is None:
            list_never_run("death")
        else:
            version, inputs = dhead.get("death_adjudication_version"), dhead.get("inputs") or {}
            # The scoreboard stream feeds `scoreboard_dim`, and the identity
            # rules name every role; a deaths table read from older ones is
            # stale although no killfeed stream moved.
            want = {k: v for k, (_, v) in code_fields["death"].items()}
            moved = sorted(k for k, v in want.items() if inputs.get(k) not in (v, None, NO_ROWS)
                           and not accepted(f"death input {k}", inputs.get(k), v))
            # The X marks place deaths only from a current `minimap_object`
            # stream; a table built without one is stale once one is stored.
            if (inputs.get("minimap_object") is None and "minimap_object" not in moved
                    and store.events_version("minimap_object", sid) == minimap_object_version()):
                moved.append("minimap_object")
            # An input the rescan or the round rebuild will rewrite moves too,
            # once it has run.
            moved += sorted(s for s in rescanned | ({"round"} if rounds_stale else set())
                            if s in want and s not in moved
                            # the X inputs only where the table read them
                            and (s not in ("ally_icon", "minimap_object") or inputs.get(s)))
            moved = recorded_moved("death", dhead, moved)
            if version != DEATH_ADJUDICATION_VERSION or moved:
                derived.append({"stream": "death", "stored": version,
                                "current": DEATH_ADJUDICATION_VERSION, "inputs_moved": moved,
                                "command": f"reticle deaths {sid}"})
        deaths_stale = any(x["stream"] == "death" for x in derived)
        uhead = _head(store, "ult_cast", sid)
        if uhead is None:
            list_never_run("ult_cast")
        else:
            version, inputs = uhead.get("ult_cast_version"), uhead.get("inputs") or {}
            moved = sorted(k for k, (_, v) in code_fields["ult_cast"].items()
                           if inputs.get(k) not in (v, None, NO_ROWS))
            # A tray binding stamped before the gate had a stamp of its own
            # was decided by the first gate.
            if inputs.get("tray_drop") == TRAY_VERSION and "player_cast" not in inputs:
                moved = sorted(moved + ["player_cast"])
            # The tray binding reads the HUD and the gate's inputs only where it
            # read tray drops.
            moved += sorted(k for k, again in (("ult_line", "ult_line" in rescanned),
                                               ("round", rounds_stale),
                                               ("hud", "hud" in rescanned and "hud" in inputs),
                                               ("killfeed_portrait", "killfeed_portrait" in rescanned
                                                and "killfeed_portrait" in inputs),
                                               ("death", deaths_stale and "death" in inputs))
                            if again and k not in moved)
            moved = recorded_moved("ult_cast", uhead, moved)
            if version != ULT_CAST_VERSION or moved:
                derived.append({"stream": "ult_cast", "stored": version,
                                "current": ULT_CAST_VERSION, "inputs_moved": moved,
                                "command": f"reticle ult-cast {sid}"})
        # Which drops are the player's casts is the gate's decision
        # (`ability_timeline.player_tray_casts`, PLAYER_CAST_VERSION). `tray`
        # stores the verdict it gave beside its drops, for the prototypes that
        # read it, and `ability-shapes` fits a shape after each cast; a row
        # without the gate's stamp was decided by the first gate. The kit state
        # (`ability-state`) reads the drops, the gate and the deaths the gate
        # reads, so a rescan of the HUD or a moved rounds or death table stales it.
        # The round-history strip rereads the stored centre crops; the
        # openings rerun from the slab test's rows and the strip's.
        specs = _hand_specs()
        for stream in ("tray_drop", "ability_shape", "scoreboard_strip", "scoreboard_presence",
                       "ability_state", "self_icon"):
            stamp, current, command = specs[stream]
            command, want = command.replace(" {sid}", ""), code_fields[stream]
            head = _head(store, stream, sid)
            if head is None:
                list_never_run(stream)
                continue
            version = head.get(stamp)
            moved = sorted(k for k, (field, v) in want.items() if head.get(field) != v
                           and not accepted(f"{stream} input {k}", head.get(field), v))
            if stream == "ability_state":
                moved += sorted(k for k, again in (("round", rounds_stale),
                                                   ("hud", "hud" in rescanned),
                                                   ("death", deaths_stale)) if again)
            if stream == "self_icon" and "roster" in rescanned:
                moved.append("roster")
            moved = recorded_moved(stream, head, moved)
            if version != current or moved:
                derived.append({"stream": stream, "stored": version, "current": current,
                                "inputs_moved": moved, "command": f"{command} {sid}",
                                "how": _CACHE_READERS.get(stream, "storage")})
        # Every other stamped stream, declared with its command.
        # A stream never run moves nothing downstream until it is written: its
        # command may write nothing (`ult-cast` without voice-line peaks), and
        # the streams built from it would stay stale for ever. Plan again
        # after it runs; the rounds alone follow it below.
        moving = rescanned | {x["stream"] for x in derived if x["inputs_moved"] != [NEVER_RUN]}
        stored = set(stored_streams(store, sid))
        for spec in derived_streams():
            stream = spec["stream"]
            head = (_head(store, stream, sid, b'"event_kind":"identity_distribution"') if spec.get("identity")
                    else _head(store, stream, sid))
            if head is None and spec.get("written_with"):
                # A run that named nothing writes no identity event; the
                # coverage row written beside it stamps the run and says why.
                head = _empty_run_head(store, sid, spec)
            # The owning rule's word is asked only where the absence would
            # be listed: turned off, a never-run stream is no work to excuse.
            if (head is None and spec.get("applies") is not None
                    and (never_run or PASS_ADDED.get(stream) in stored)):
                said = spec["applies"](store, sid)
                if said is not None and said[0] != "applies":
                    not_applicable.append({"stream": stream, "status": said[0],
                                           "why": said[1]})
                    continue
            if head is None:
                # A stream the ability pass gained after it ran on stored
                # sessions (`PASS_ADDED`), absent beside the sibling whose
                # presence shows the pass ran, is stale; any other absent
                # stream has never run. Both are listed: a skipped step hides
                # the work a session lacks.
                why = ("absent from a pass that ran" if PASS_ADDED.get(stream) in stored
                       else NEVER_RUN)
                if why == NEVER_RUN and not never_run:
                    continue
                derived.append({"stream": stream, "stored": None, "current": spec["current"],
                                "inputs_moved": [why], "how": spec["how"],
                                "command": spec["command"].format(sid=sid)})
                if why != NEVER_RUN:
                    moving.add(stream)
                continue
            version = head.get(spec["key"])
            behind, moved, missing = recorded_stale(store, man, spec, head, memo, accepted)
            if missing:
                unrecorded.append({"stream": stream, "inputs": missing})
            moved += sorted(u for u in upstream_names(stream, spec["upstream"], moving, head)
                            if u not in moved)
            if behind or moved:
                derived.append({"stream": stream, "stored": version, "current": spec["current"],
                                "inputs_moved": moved, "how": spec["how"],
                                "command": spec["command"].format(sid=sid)})
                moving.add(stream)
        # The rounds read the plant graphic and the portrait stream's second
        # lives; one never run, written now, moves them once it lands.
        if never_run and r is not None and not rounds_stale:
            listed = moving | {x["stream"] for x in derived}
            first = sorted(k for k in ("killfeed_portrait", "plant_graphic") if k in listed)
            if first:
                derived.append({"stream": "rounds", "stored": r["round"], "current": ROUND_VERSION,
                                "inputs_moved": first, "command": f"reticle rounds {sid}"})
                moving.add("rounds")
        if widget is not None:
            _widget_derived(store, sid, derived, moving)
        elif placed:
            _widget_derived(store, sid, derived, moving, set(placed))
        # A stream checked above before one of its inputs was found stale
        # follows it now: staleness follows every declared input, in any order.
        _follow(store, sid, derived, moving)
        # The capture's replay (`replay_keep.missing_steps`): unkept,
        # unlinked, unparsed, or its Riot record unwrapped; a record the
        # player has not fetched is named as the player's step.
        derived += replay_keep_work(store.root, sid, man)
        # The replay layer of a session whose kept replay names it
        # (`replay_layer.session_status`): absent or stale against its parse,
        # the stored deaths its clock is fitted on, the geometry, the frame
        # grid, the lineup and the code; a death rerun planned here moves it.
        rl = replay_layer_work(store.root, sid, moving)
        if rl is not None:
            derived.append(rl)
            moving.add(rl["stream"])
        # Its episodes (`episodes.session_status`): absent, or stale against
        # the layer, the sightline table, the region labels and the code; a
        # layer planned here moves them.
        ew = episodes_work(store.root, sid, moving)
        if ew is not None:
            derived.append(ew)
            moving.add(ew["stream"])
        # The entity lanes: the projection records each input's stamp.
        from .entity_events import lane_status
        lanes = lane_status(store, sid, moving)
        derived += lanes["derived"]
        # A stored stream no check declares is named, never silently current.
        declared = ({s for s, *_ in reader_streams()} | set(_HAND_CHECKED)
                    | {s["stream"] for s in derived_streams()} | _lane_streams()
                    | {s["written_with"] for s in derived_streams() if s.get("written_with")
                       and _coverage_head(store, sid, s["written_with"]) is not None})
        unchecked = [{"stream": s, "why": RETIRED_STREAMS.get(s) or arm_reason(s)
                      or UNSTAMPED.get(s, "undeclared: no check in plan")}
                     for s in stored_streams(store, sid) if s not in declared]
        caches = cache_work(store, man)
        from .roi_cache import pixel_source
        pixels = pixel_source(store.root, man)
        rebuild = cache_rebuild(store, man, decode, derived) if pixels["state"] == "video" else []
        unbuilt = (retired_caches(store, man, {b["set"] for b in rebuild})
                   if pixels["state"] == "video" else [])
        decode, derived, widget, caches, retired = source_retired(
            sid, man, decode, derived, widget, caches,
            feeds=lambda ch, m=man: _channel_cache(store, m, ch), pixels=pixels)
        out[sid] = {"decode": decode, "derived": derived, "absent": absent, "waived": waived,
                    "declined": declined,
                    "unchecked": unchecked, "held": lanes["held"], "unrecorded": unrecorded,
                    "not_applicable": not_applicable,
                    "widget": widget, "placement": placed, "caches": caches,
                    "source_retired": retired, "rebuild": rebuild, "pixels": pixels,
                    "retired_caches": unbuilt}
    return out


#: The streams the replay layer is built from, for the build order: its clock
#: is fitted on the stored deaths, and its replay is kept by `replay-keep`.
REPLAY_LAYER_INPUTS = {"death", "replay_keep"}


def replay_keep_work(root, sid: str, manifest: dict) -> list[dict]:
    """One `replay_keep` entry per step of the capture's replay hook the
    session lacks (`replay_keep.missing_steps`), or none."""
    from .replay_keep import missing_steps
    return [{"stream": "replay_keep", "stored": None, "current": None,
             "inputs_moved": [f"{m['step']}: {m['why']}"], "how": m["how"],
             "command": m["command"]}
            for m in missing_steps(sid, manifest, root)]


def replay_layer_work(root, sid: str, moving: set[str] = frozenset()) -> dict | None:
    """The replay layer's entry for a session, or None where it is current,
    the session names no kept replay, or the replay is unparsed (`status`
    names that apart)."""
    from .replay_layer import REPLAY_LAYER_VERSION, session_status
    st = session_status(sid, root)
    if st is None or st["state"] == "unparsed":
        return None
    if st["state"] == "current" and not (REPLAY_LAYER_INPUTS & set(moving)):
        return None
    moved = list(st.get("moved") or [])
    if st["state"] == "absent":
        moved = ["absent"]
    moved += sorted(m for m in REPLAY_LAYER_INPUTS & set(moving) if m not in moved)
    return {"stream": "replay_layer", "stored": st.get("stored"), "current": REPLAY_LAYER_VERSION,
            "inputs_moved": moved, "how": "storage", "command": st["command"]}


#: The streams episodes are derived from, for the build order.
EPISODES_INPUTS = {"replay_layer"}


def episodes_work(root, sid: str, moving: set[str] = frozenset()) -> dict | None:
    """The episodes entry for a session whose kept replay names it, or None
    where they are current and no input moves, or no replay is kept."""
    from .episodes import EPISODES_VERSION, session_status
    st = session_status(sid, root)
    if st is None:
        return None
    upstream = sorted(EPISODES_INPUTS & set(moving))
    if st["state"] == "current" and not upstream:
        return None
    moved = ["absent"] if st["state"] == "absent" else list(st.get("moved") or [])
    moved += [m for m in upstream if m not in moved]
    return {"stream": "episodes", "stored": st.get("stored"), "current": EPISODES_VERSION,
            "inputs_moved": moved, "how": "storage", "command": st["command"]}


def _channel_cache(store, manifest: dict, channel: str) -> tuple[str | None, str]:
    from .profiles import get_profile
    from .roi_cache import channel_cache
    return channel_cache(store.root, manifest, get_profile(manifest["source_profile"]), channel)


def source_retired(sid: str, manifest: dict, decode: list, derived: list, widget, caches: list,
                   feeds=None, pixels: dict | None = None):
    """(decode, derived, widget, caches, retired): on a session whose video
    is retired and gone (`audio_source.video_state`), the crop caches are the
    evidence that stays, and a reread they feed stays proposed.

    A reader stream stays in `decode`, marked `from_cache` with the set,
    where `feeds(channel)` (`roi_cache.channel_cache`) finds a stored crop
    cache that holds the channel's ROIs: `scan` reads it with no decode, and
    refuses `source_retired_no_cache` where the readers' rates or spans do
    not fit it. The `audio` channel stays too, since `ult-lines` reads the
    retained audio. Every other step that opens the capture -- a reader no
    cache feeds, a derived decode, a crop cache to write -- moves to
    `retired`, reason `source_retired`, with why, and is never proposed.

    Where `pixels` (`roi_cache.pixel_source`) says `no_pixels` -- the video
    retired and no crop cache stored -- every step that reads pixels, a
    cache-fed reread or derived step included, moves to `retired` with
    reason `no_pixels` and its why; only the audio and storage steps stay."""
    from .audio_source import video_state
    if video_state(manifest) != "retired":
        return decode, derived, widget, caches, []
    if pixels is not None and pixels["state"] == "no_pixels":
        why = pixels["why"]
        gone = [{"stream": s["stream"], "command": f"reticle scan {sid} --only {s['channel']}",
                 "reason": "no_pixels", "why": why}
                for s in decode if s["channel"] not in ACCEPT]
        gone += [{"stream": d["stream"], "command": d["command"], "reason": "no_pixels",
                  "why": why} for d in derived if d.get("how") in ("decode", "cache")]
        if widget and "cache" in widget:
            gone.append({"stream": "roi_cache:minimap", "command": widget["cache"]["command"],
                         "reason": "no_pixels", "why": why})
            widget = {k: v for k, v in widget.items() if k != "cache"} or None
        gone += [{"stream": f"roi_cache:{c['set']}", "command": c["command"],
                  "reason": "no_pixels", "why": why} for c in caches]
        return ([s for s in decode if s["channel"] in ACCEPT],
                [d for d in derived if d.get("how") not in ("decode", "cache")],
                widget, [], gone)
    retired = []
    keep_decode = []
    memo: dict[str, tuple[str | None, str]] = {}
    for s in decode:
        if s["channel"] in ACCEPT:
            keep_decode.append(s)
            continue
        if s["channel"] not in memo:
            memo[s["channel"]] = (feeds(s["channel"]) if feeds is not None
                                  else (None, "no cache check"))
        held, why = memo[s["channel"]]
        if held is not None:
            keep_decode.append({**s, "from_cache": held})
        else:
            retired.append({"stream": s["stream"], "command": f"reticle scan {sid} --only "
                            f"{s['channel']}", "reason": "source_retired", "why": why})
    keep_derived = []
    for d in derived:
        if d.get("how") == "decode":
            retired.append({"stream": d["stream"], "command": d["command"],
                            "reason": "source_retired", "why": "decodes the capture"})
        else:
            keep_derived.append(d)
    if widget and "cache" in widget:
        retired.append({"stream": "roi_cache:minimap", "command": widget["cache"]["command"],
                        "reason": "source_retired", "why": "writes crops from the capture"})
        widget = {k: v for k, v in widget.items() if k != "cache"} or None
    retired += [{"stream": f"roi_cache:{c['set']}", "command": c["command"],
                 "reason": "source_retired", "why": "writes crops from the capture"}
                for c in caches]
    return keep_decode, keep_derived, widget, [], retired


#: The crop cache sets each derived stream whose command reads the cache
#: (`how` `cache`) loads, by the command's `RoiCache.load` calls; the ability
#: pass's streams (`ability_streams`) read the minimap set.
CACHE_STREAM_SETS = {
    "menu_open": ("hud", "minimap"), "spike": ("minimap", "hud"),
    "round_outcome": ("scoreboard",), "plant_graphic": ("hud",),
    "scoreboard_strip": ("hud",), "self_icon": ("minimap",), "team_vision": ("minimap",),
    "tray_kit": ("minimap",), "tray_kit_identity": ("minimap",),
    "tray_countdown": ("minimap",), "minimap_object": ("minimap",),
    "killfeed_assist": ("hud",), "assist": ("hud",),
}


def cache_stream_sets(stream: str) -> tuple[str, ...]:
    """The crop cache sets a cache-reading derived stream's command loads."""
    if stream in CACHE_STREAM_SETS:
        return CACHE_STREAM_SETS[stream]
    if stream in {s for s, _, _ in ability_streams()}:
        return ("minimap",)
    raise KeyError(f"{stream}: no crop cache set declared in plan.CACHE_STREAM_SETS")


def cache_rebuild(store, manifest: dict, decode: list, derived: list) -> list[dict]:
    """The crop cache sets a session with its video must rebuild before its
    stale cache-fed work: each set a trial-checked reader channel
    (`roi_cache.SCAN_CHANNEL_SETS`; `trial --from cache` reads only the
    cache, while `scan` decodes where none is stored) or a cache-reading derived step
    (`CACHE_STREAM_SETS`) reads and the store does not hold. Each work entry
    that waits gains `rebuild`; each set comes back with the decode that
    writes it (`roi_cache.rebuild_command`), the reason it is absent
    (`no_cache`, or `cache_retired` where a retirement row names the
    session), and the streams it feeds."""
    from .roi_cache import (CACHE_RETIRED, CACHE_SETS, SCAN_CHANNEL_SETS, cache_retirement,
                            holding_sets, rebuild_command, stored_sets)
    sid = manifest["session_id"]
    held = set(stored_sets(store.root, sid))
    need: dict[str, set[str]] = defaultdict(set)
    for s in decode:
        sets = SCAN_CHANNEL_SETS.get(s["channel"])
        if sets is None or not s.get("trial"):
            continue
        names = holding_sets(set().union(*(CACHE_SETS[x] for x in sets)))
        if names and not held & set(names):
            s["rebuild"] = names[0]
            need[names[0]].add(s["stream"])
    for d in derived:
        if d.get("how") != "cache":
            continue
        lack = [n for n in cache_stream_sets(d["stream"]) if n not in held]
        if lack:
            d["rebuild"] = lack
            for n in lack:
                need[n].add(d["stream"])
    why = CACHE_RETIRED if cache_retirement(store.root, sid) is not None else "no_cache"
    return [{"set": n, "command": rebuild_command(sid, n), "reason": why, "feeds": sorted(v)}
            for n, v in sorted(need.items())]


#: The sets the ingest writes (`cli.cmd_ingest_passes`), in the order a
#: rebuild runs them: the killfeed panel strip pairs with the `hud` set, and
#: the scoreboard set is written only at `scoreboard_strip.MEASURED_WH`.
INGEST_SETS = ("hud", "minimap", "killfeed_panel", "scoreboard")


def retired_caches(store, manifest: dict, listed=frozenset()) -> list[dict]:
    """The crop cache sets a retirement row (`roi_cache.cache_retirement`)
    names for a session with its video that the store does not hold and no
    stale step reads now (`listed` is `cache_rebuild`'s): named with the
    decode that rebuilds each, never proposed as work."""
    from .roi_cache import cache_retirement, rebuild_command, stored_sets
    from .scoreboard_strip import MEASURED_WH
    sid = manifest["session_id"]
    row = cache_retirement(store.root, sid)
    if row is None:
        return []
    held = set(stored_sets(store.root, sid)) | set(listed)
    wh = (int(manifest["source"]["width"]), int(manifest["source"]["height"]))
    return [{"set": n, "command": rebuild_command(sid, n), "at": str(row["at"])[:10]}
            for n in INGEST_SETS if n in (row.get("rois") or ()) and n not in held
            and (n != "scoreboard" or wh == MEASURED_WH)]


#: Crop cache sets a session should hold, each where the stored inputs it is
#: written from exist: the stored crop cache set it pairs with, and the
#: stream its gate reads. The killfeed panel strip pairs with the `hud` set
#: (`roi_cache.WIDE_ROIS`) and gates on `killfeed_portrait`.
EXPECTED_CACHES = {"killfeed_panel": ("hud", "killfeed_portrait")}


def cache_work(store, manifest: dict) -> list[dict]:
    """Each expected crop cache set (`EXPECTED_CACHES`) the session lacks or
    cannot load, with why and the decode that writes it, which only the
    player starts."""
    from .profiles import get_profile
    from .roi_cache import RoiCache, rewrite_command, stored_record
    sid = manifest["session_id"]
    out = []
    for name, (pair, witness) in EXPECTED_CACHES.items():
        if stored_record(store.root, sid, pair) is None or not store.has_events(witness, sid):
            continue
        if stored_record(store.root, sid, name) is None:
            why = "missing"
        else:
            why = RoiCache.load(store.root, manifest, get_profile(manifest["source_profile"]),
                                name)[1]
        if why is not None:
            out.append({"set": name, "reason": why, "witness": witness,
                        "command": rewrite_command(sid, name)})
    return out


#: The name a stream's `inputs_moved` gives the session's widget placement.
WIDGET_INPUT = "widget_placement"
#: The reader streams that read the minimap widget's pixels (`scan`'s
#: `_normalise_decoded` set), and the cache-reading streams that do.
WIDGET_PIXEL_READERS = ("minimap", "ping", "ally_icon", "minimap_dark")
#: `ability_shape` fits its shapes on the cached minimap crops too. The tray
#: and menu streams read the tray ROI of the same cache, never the widget;
#: `ability_light` decodes the profile's ROI and never reads the placement.
WIDGET_PIXEL_DERIVED = ("team_vision", "spike", "minimap_object", "self_icon", "ability_shape")


def widget_streams() -> tuple[str, ...]:
    """Every stream that reads the minimap widget's pixels through the
    session's stored placement: the readers, the cache-reading streams and
    the ability pass's streams."""
    return (WIDGET_PIXEL_READERS + WIDGET_PIXEL_DERIVED
            + tuple(s for s, _, _ in ability_streams()))


def record_placement(manifest: dict, stream: str, head: dict) -> dict:
    """Record in `head`, a widget-reading stream's first row about to be
    written, the placement it read the widget through
    (`widget_frame.placement_identity`) under `WIDGET_INPUT`. Returns `head`."""
    if stream in widget_streams():
        from .widget_frame import placement_identity
        head[WIDGET_INPUT] = placement_identity(manifest)
    return head


def _placement_stored(store, manifest: dict, stream: str):
    """(the placement identity a stored widget stream recorded, or `_MISSING`;
    the stream's file, or None where the store keeps no files or the stream
    holds no rows)."""
    sid, date = manifest["session_id"], manifest["ingested_at"][:10]
    if stream == "minimap":
        path_of = getattr(store, "minimap_path", None)
        path = path_of(sid, date) if path_of is not None else None
        if path is None or not path.is_file():
            return _MISSING, None
        meta = pq.read_schema(path).metadata or {}
        got = meta.get(WIDGET_INPUT.encode())
        return (_MISSING if got is None else got.decode()), path
    head = _head(store, stream, sid)
    path_of = getattr(store, "events_path", None)
    # A file with no rows holds no reading, as `stale` calls it absent.
    path = path_of(stream, sid) if path_of is not None and head is not None else None
    return (_MISSING if head is None or WIDGET_INPUT not in head else head[WIDGET_INPUT]), path


def placement_moved(store, manifest: dict, stream: str) -> str | None:
    """Why a stored widget-reading stream read the widget through another
    placement than the one stored now, or None.

    A stream that recorded its placement (`record_placement`) moved when the
    recorded `placement_digest` differs from the stored one's; the stamp
    alone moves no pixel. One written before it was recorded is compared
    by time: it moved when its file was written before the stored placement
    last changed what a reader reads (`widget_frame.placement_changed_at`,
    over `minimap_widget_history`). 4f207c0c4e39's refit moved the turn from
    1192766.67 ms to 1148000 ms, and 37 ally_icon frame rows read through the
    old one went unnamed, since no stamp moved. A file rewritten by hand
    after the change reads as current: the time is the file's, not the read's."""
    import datetime as dt
    from .input_stamps import normalize
    from .widget_frame import NO_PLACEMENT, placement_changed_at, placement_identity
    rec, path = _placement_stored(store, manifest, stream)
    if rec is not _MISSING:
        now = placement_identity(manifest)
        digest = lambda v: (normalize(v) or NO_PLACEMENT).rsplit("#", 1)[-1]
        if digest(rec) != digest(now):
            return f"read through {rec}, stored {now}"
        return None
    changed = placement_changed_at(manifest)
    if changed is None or path is None or not path.is_file():
        return None
    written = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
    try:
        at = dt.datetime.fromisoformat(changed)
    except ValueError:
        return f"written before the placement changed at an unparsed time {changed}"
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.timezone.utc)
    if written < at:
        return f"written before the placement changed at {changed}"
    return None


def widget_work(store, manifest: dict) -> dict | None:
    """What the session's minimap widget needs before its pixels are read
    (`widget_frame`), or None:

    * `placement`: a side-based or drawn-collapse session with no stored
      placement (`widget_frame.placement_status`), and the fit command;
    * `cache`: a stored placement the minimap crop cache cannot serve
      (`stale_rects` after a wider capture box, `crop_clips_widget`), and the
      re-decode command (`roi_cache.rewrite_command`), which only the player
      starts;
    * `reread`: a stored placement and a usable cache, but a stored minimap
      table whose `widget_drawn` rate still collapses at a round boundary
      (`widget_frame.stored_collapse`): its readers read before the placement.
    """
    from . import widget_frame as wf
    from .profiles import get_profile
    from .roi_cache import RoiCache, rewrite_command, stored_record
    sid = manifest["session_id"]
    status = wf.placement_status(store, manifest)
    if status is not None:
        if stored_record(store.root, sid, "minimap") is None:
            status = {**status, "detail": status["detail"] + "; no minimap crop cache is "
                      "stored, so the fit waits for one"}
        return {"placement": status}
    if wf.entry(manifest) is None:
        return None
    rec = stored_record(store.root, sid, "minimap")
    if rec is not None:
        cache, why = RoiCache.load(store.root, manifest, get_profile(manifest["source_profile"]),
                                   "minimap")
        if cache is None:
            return {"cache": {"reason": why, "held": rec.get("rects", [None])[0],
                              "command": rewrite_command(sid, "minimap", rec)}}
    c = wf.stored_collapse(store, manifest)
    if c is not None:
        return {"reread": {"reason": "drawn_collapse_after_placement",
                           "detail": (f"widget_drawn {c['before']:.3f} before round "
                                      f"{c['round_no']} and {c['after']:.3f} from it")}}
    return None


def _widget_derived(store, sid: str, derived: list[dict], moving: set[str],
                    only: set[str] | None = None) -> None:
    """Name every stored cache-reading stream that read the widget's pixels
    (`WIDGET_PIXEL_DERIVED` and the ability pass's streams), or those of
    them in `only`, as moved by the placement; `_follow` then carries it
    downstream."""
    hand = {s: (k, c, cmd, _CACHE_READERS.get(s, "storage"))
            for s, (k, c, cmd) in _hand_specs().items()}
    specs = {**hand, **{s["stream"]: (s["key"], s["current"], s["command"], s["how"])
                        for s in derived_streams()}}
    names = [s for s in widget_streams()
             if s not in WIDGET_PIXEL_READERS and (only is None or s in only)]
    by = {d["stream"]: d for d in derived}
    for stream in names:
        if stream not in specs:
            continue
        head = _head(store, stream, sid)
        if head is None:
            continue
        if stream in by:
            if WIDGET_INPUT not in by[stream]["inputs_moved"]:
                by[stream]["inputs_moved"].append(WIDGET_INPUT)
            continue
        key, current, command, how = specs[stream]
        entry = {"stream": stream, "stored": head.get(key), "current": current,
                 "inputs_moved": [WIDGET_INPUT], "how": how,
                 "command": command.format(sid=sid)}
        derived.append(entry)
        by[stream] = entry
        moving.add(stream)


def _lane_streams() -> set[str]:
    from .entity_events import ENTITY_LANES, lane_streams
    return {s for spec in ENTITY_LANES for s in lane_streams(spec["lane"])}


def render(plan: dict) -> str:
    """The stale work grouped by what refreshes it, with the commands."""
    by_channel: dict[str, list[str]] = defaultdict(list)
    trials: dict[str, list[str]] = defaultdict(list)
    derived = []
    for sid, p in plan.items():
        for s in p["decode"]:
            if sid not in by_channel[s["channel"]]:
                by_channel[s["channel"]].append(sid)
            if s["trial"] and sid not in trials[(s["channel"], s["trial"])]:
                trials[(s["channel"], s["trial"])].append(sid)
        derived += [(sid, d) for d in p["derived"]]
    lines = []
    # Accepted by waiver: neither stale nor current, and always named.
    waived: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for w in p.get("waived", []):
            waived[(w["stream"], w["stored"], w["current"])].append(sid)
    from .version import STAMP_WAIVERS
    when = lambda stored, current: (
        f", where {w['when']} holds" if isinstance(w := STAMP_WAIVERS.get((current, stored)), dict)
        else "")
    waived_lines = [f"waived   {stream}: {stored} accepted as {current} by waiver "
                    f"(version.STAMP_WAIVERS{when(stored, current)}) on {len(sids)} sessions: "
                    f"{' '.join(sids)}"
                    for (stream, stored, current), sids in sorted(waived.items())]
    # A conditional waiver that did not hold on a session leaves it stale, by name.
    declined: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for w in p.get("declined", []):
            declined[(w["stream"], w["stored"], w["current"], w["why"])].append(sid)
    waived_lines += [f"not waived {stream}: {stored} stays stale under {current}, the waiver's "
                     f"condition fails ({why}) on {len(sids)} sessions: {' '.join(sids)}"
                     for (stream, stored, current, why), sids in sorted(declined.items())]
    unchecked: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for u in p.get("unchecked", []):
            unchecked[(u["stream"], u["why"])].append(sid)
    waived_lines += [f"unchecked {stream}: {why} on {len(sids)} sessions"
                     for (stream, why), sids in sorted(unchecked.items())]
    # A declared input the stored head never recorded cannot be compared: the
    # stream was written before it was recorded. Not stale, and not current.
    unrec: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for u in p.get("unrecorded", []):
            unrec[(u["stream"], ", ".join(u["inputs"]))].append(sid)
    waived_lines += [f"unrecorded {stream}: inputs {inputs} not recorded, so not compared, on "
                     f"{len(sids)} sessions; its next rerun records them"
                     for (stream, inputs), sids in sorted(unrec.items())]
    # A stream its owning rule says does not apply, or cannot yet tell, is
    # not work: neither stale, current nor never run.
    nap: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for n in p.get("not_applicable", []):
            nap[(n["stream"], n["status"], n["why"] or "")].append(sid)
    waived_lines += [f"{status.replace('_', ' ')} {stream}: {why} on {len(sids)} sessions: "
                     f"{' '.join(sids)}"
                     for (stream, status, why), sids in sorted(nap.items())]
    # A lane current as projected over inputs that are themselves stale: its
    # rows wait in the ledger as `stale`, and rebuilding it now changes nothing.
    held: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for h in p.get("held", []):
            held[(h["stream"], ", ".join(h["waits_for"]))].append(sid)
    waived_lines += [f"held     {stream}: rows held stale until {inputs} are refreshed, then "
                     f"`reticle project <sid>` for {' '.join(sids)}"
                     for (stream, inputs), sids in sorted(held.items())]
    # The widget comes first: a placement fit (crop cache, no decode), then
    # the crop cache's re-decode, which only the player starts; every stream
    # below that names `widget_placement` waits for both.
    for sid, p in plan.items():
        w = p.get("widget") or {}
        if "placement" in w:
            s = w["placement"]
            lines.append(f"placement {s['command']}   ({s['reason']}: {s['detail']}; reads "
                         f"the minimap crop cache and rounds, no decode) for {sid}")
        if "cache" in w:
            c = w["cache"]
            lines.append(f"decode   {c['command']}   (minimap crop cache {c['reason']}; holds "
                         f"{c['held']}; the player starts this decode) for {sid}")
        if "reread" in w:
            lines.append(f"reread   minimap streams of {sid}   ({w['reread']['reason']}: "
                         f"{w['reread']['detail']})")
        # Streams read through another placement than the stored one.
        why_of: dict[str, list[str]] = defaultdict(list)
        for stream, why in sorted((p.get("placement") or {}).items()):
            why_of[why].append(stream)
        for why, streams in why_of.items():
            lines.append(f"reread   {', '.join(streams)} of {sid}   (placement_moved: {why}; "
                         f"each is listed below with input {WIDGET_INPUT})")
    # Crop cache sets a session lacks (`cache_work`): a decode the player starts.
    caches: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for c in p.get("caches") or ():
            command = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "<sid>", c["command"])
            caches[(c["set"], c["reason"], f"{command}   ({c['set']} crop cache {c['reason']}; "
                    f"gated on stored {c['witness']} rows; the player starts this decode)")].append(sid)
    lines += [f"decode   {text} for {' '.join(sids)}"
              for (_s, _r, text), sids in sorted(caches.items())]
    # Crop cache sets a session with its video must rebuild before the
    # cache-fed work below (`cache_rebuild`): a decode the player starts.
    rebuild: dict[tuple[str, str], list[str]] = defaultdict(list)
    feeds: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sid, p in plan.items():
        for b in p.get("rebuild") or ():
            command = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "<sid>", b["command"])
            rebuild[(command, b["reason"])].append(sid)
            feeds[(command, b["reason"])] |= set(b["feeds"])
    lines += [f"decode   {command}   (rebuild first: the crop cache is absent, {reason}; "
              f"{', '.join(sorted(feeds[(command, reason)]))} read it; the player starts "
              f"this decode) for {' '.join(sids)}"
              for (command, reason), sids in sorted(rebuild.items())]
    # Steps that need a video the player retired (`source_retired`): named,
    # never proposed.
    gone: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for r in p.get("source_retired") or ():
            command = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "<sid>", r["command"])
            gone[(command, r["stream"], r.get("why", ""))].append(sid)
    dark: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for (command, stream, why), sids in gone.items():
        if why.startswith("no pixels"):
            dark[(command, why, " ".join(sids))].append(stream)
    waived_lines += [f"retired  {command}   ({stream}: source_retired, the video was retired "
                     f"and its audio kept; {why}; not proposed) for {' '.join(sids)}"
                     for (command, stream, why), sids in sorted(gone.items())
                     if not why.startswith("no pixels")]
    # Retired crop caches no stale step reads now (`retired_caches`): named
    # with their rebuild, a decode, for when cache-fed work returns.
    absent: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sid, p in plan.items():
        for c in p.get("retired_caches") or ():
            command = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "<sid>", c["command"])
            absent[(command, c["at"])].append(sid)
    waived_lines += [f"absent   {command}   (crop cache retired {at}; no stale step reads it "
                     f"now; rebuild it before cache-fed work, a decode the player starts) "
                     f"for {' '.join(sids)}"
                     for (command, at), sids in sorted(absent.items())]
    # No pixels (`roi_cache.pixel_source`): neither the video nor a crop
    # cache is stored, so no reread of these streams can ever run.
    waived_lines += [f"retired  {command}   ({', '.join(sorted(streams))}: {why}; never "
                     f"proposed) for {sids}"
                     for (command, why, sids), streams in sorted(dark.items())]
    if not by_channel and not derived:
        return "\n".join(lines + [f"nothing stale over {len(plan)} sessions"] + waived_lines)
    for ch, sids in sorted(by_channel.items()):
        streams = sorted({s["stream"] for p in plan.values() for s in p["decode"]
                          if s["channel"] == ch})
        cached = [t for (tch, t) in trials if tch == ch]
        # Never run (`NEVER_RUN_READERS`) and cache-fed (`CACHE_FED_READERS`).
        never = [sid for sid in sids if any(s.get("inputs_moved") == [NEVER_RUN]
                                            for s in plan[sid]["decode"] if s["channel"] == ch)]
        fed = {sid: s["cache_fed"] for sid in sids for s in plan[sid]["decode"]
               if s["channel"] == ch and s.get("cache_fed") and not s.get("from_cache")}
        how = ("stale" if not never else f"{NEVER_RUN}" if len(never) == len(sids)
               else f"stale or {NEVER_RUN} ({NEVER_RUN} on {' '.join(never)})")
        lines.append(f"{'reread' if cached or (fed and len(fed) == len(sids)) else 'decode'}   "
                     f"{ch}: {', '.join(streams)} {how} on {len(sids)} sessions")
        waits = [sid for sid in sids if any(s.get("rebuild") for s in plan[sid]["decode"]
                                            if s["channel"] == ch)]
        for (tch, t), tsids in sorted(trials.items()):
            if tch == ch:
                lines.append(f"  check  reticle trial {tsids[0]} --reader {t} --from cache"
                             f"   (one session, stored windows, no decode"
                             + ("; after its crop cache rebuild above)" if tsids[0] in waits
                                else ")"))
        # A retired session's reread reads the crop cache only (`source_retired`).
        only = [sid for sid in sids if any(s.get("from_cache") for s in plan[sid]["decode"]
                                           if s["channel"] == ch)]
        by_set: dict[str, list[str]] = defaultdict(list)
        for sid, name in fed.items():
            if sid not in only:
                by_set[name].append(sid)
        for name, fsids in sorted(by_set.items()):
            lines.append(f"  accept reticle scan <sid> --only {ch} --from cache   (reads the "
                         f"stored {name} crop cache, no decode) for {' '.join(fsids)}")
        rest = [sid for sid in sids if sid not in only and sid not in fed]
        accept = ACCEPT.get(ch, f"reticle scan <sid> --only {ch}")
        if rest:
            lines.append(f"  accept {accept}   for {' '.join(rest)}"
                         + (("   (from the rebuilt crop cache)" if all(x in waits for x in rest)
                             else "   (from the ROI crop cache where one exists)")
                            if cached else ""))
        if only:
            lines.append(f"  accept reticle scan <sid> --only {ch} --from cache   (video "
                         f"retired: the crop cache feeds it, no decode) for {' '.join(only)}")
    # Grouped by command and reason, each stream after every stream it is
    # built from (`build_order`), so a driver can run the lines top to bottom;
    # an identity stream follows the stream whose command writes it. `how`
    # says what the command reads: stored rows only, the ROI crop cache, or
    # the capture itself.
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    stream_of: dict[tuple[str, str, str], str] = {}
    for sid, d in derived:
        why = ("; ".join(filter(None, (
            f"{d['stored']} -> {d['current']}" if d["stored"] != d["current"] else None,
            "inputs " + ", ".join(d["inputs_moved"]) if d["inputs_moved"] else None)))
            if d["inputs_moved"] != [NEVER_RUN] else f"{NEVER_RUN}, current {d['current']}")
        command = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "<sid>", d["command"])
        key = (d.get("how", "storage"), command, f"{d['stream']}: {why}")
        grouped[key].append(sid)
        stream_of[key] = d["stream"]
    graph, fold = order_graph()
    node = {k: fold.get(s, s) for k, s in stream_of.items()}
    rank = {n: i for i, n in enumerate(build_order(list(node.values()), graph))}
    first = {k: i for i, k in enumerate(grouped)}
    for key in sorted(grouped, key=lambda k: (rank[node[k]], stream_of[k] != node[k], first[k])):
        how, command, why = key
        lines.append(f"{how:<8} {command}   ({why}) for {' '.join(grouped[key])}")
    return "\n".join(lines + waived_lines)
