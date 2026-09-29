# Minimap objects: a classifier that names every object

The player approved this classifier on 2026-09-29. It names every object
drawn on the minimap: agent icons, the glyphs the match's kits can draw,
pings, X death marks, enemy "?" marks, the spike, smokes and other ability
areas, and `unknown`, an explicit refusal. It is adjudication over stored
observations: each class has witness channels that already exist, a prior
that narrows its gallery, and a stored form for disagreement. The first
stage, `prototypes/minimap_objects.py`, cross-references the portrait
gate's kept fits with the ping stream and with X marks at stored deaths;
its results are below, and it failed its falsifier.

## Where it starts

The teardrop reads ally and enemy facings to about two degrees. The portrait
gate, rule Bs of `prototypes/icon_portrait_gate.py` (icon-portrait-gate-0.3.0,
docs/STATISTICAL_ADJUDICATOR.md E6), keeps every labelled agent icon and
rejects half the non-icons. It still keeps red ping triangles, X marks and
Gekko's Wingman glyph, whose portraits fit as well as real icons do. A
portrait fit alone cannot reject them. The rule that follows is AGENTS.md's
"Cross-reference before tuning": ask the channels that already observe these
objects.

## What the existing channels are

**Pings.** `reticle/ping.py` owns `ping-event` and rides the shared decode
pass (`reticle scan`, channel `ping`). It stores `events/ping/<session>.jsonl`,
one row per confirmed ping: `kind` (standard, need_help, on_my_way,
watching_here, danger), widget position `x, y`, first frame `t_ms`, observed
`lifetime_s` against the class's (7 s, danger 10 s), and hue. It stores no
side: a minimap shows only the player's team's pings. It stores only pings
whose lifetime matched their class; unconfirmed and rejected groups are
dropped. The store holds it for twenty sessions at ping-0.1.0. **No production module reads
the stored stream.** Its ownership entry names `track` as consumer, but
`track` imports only the `LIFETIME_S` constant; `minimap_lifecycle` declares
`ping`, `death_mark` and `last_known` roles, but `team_vision` feeds it only
`ally` and `self`. The one reader of `events/ping` is the prototype
`prototypes/audio_gate.py`. The owner's own docstring measured the stream on
match footage: 8 of 31 confirmed pings real on one Lotus match, most false
ones ally icons held still for seven seconds.

**X death marks.** Two domain facts give the rule: an ally death always
leaves a cyan X at the death place [domain:minimap/ally-death-mark]; an
enemy death leaves a red X unless no teammate saw the victim, as with ally
utility or a fall [domain:minimap/enemy-death-mark]
[domain:minimap/environmental-death]. `adjudication.death` owns the question
"where" (`death-victim`) and has an X colour extractor,
`extract_minimap_death_marks`, and an `xmark_location` argument, but
`adjudicate_session_deaths` passes no X marks and no tracks: `location` is
null on every stored death verdict (death-adjudication-0.19.0). No stored
enemy track exists to take a victim's last place from. So a death's place can
come from stored data only as an X seen born at the death's killfeed time in
the minimap crop cache; stage 1 builds that.

**Enemy "?" marks.** No owner reads them and no domain fact records them.
`domain/minimap.toml`'s vision-trailing-persistence says an enemy stays drawn
briefly after leaving vision and lists the terminal marker ("a question mark,
a different marker, or nothing") as unmeasured
[domain:minimap/vision-trailing-persistence]. The player now says the "?"
shows an enemy's last known place; `prototypes/label_minimap.py` labels it so.
`identity.claim_from_minimap_icon` abstains on an observation marked
`question`. The player's labels hold "?" positions: `labels/minimap` (both
sessions) and `labels/minimap_agent` (Ascent).

**Other witnesses.** The spike reader (`spike`, spike-0.2.0, a 1 s grid over
the crop cache) places the glyph, on the ground or carried, and its carrier
[domain:minimap/spike-carrier-overlay]; `adjudication.spike_carrier` checks it
against the roster marker. `adjudication.smokes` and `adjudication.smoke_owner`
track ally smokes and their casters; enemy smokes are never drawn
[domain:abilities/enemy-smokes-not-on-minimap]. `minimap.ally_icons`
(`ally-candidates`) and `adjudication.minimap_candidates` propose and dispose
of teammate fits; `self_icon` reads the player's own portrait. The lineup
(`lineup`, decided by `adjudication.identity`) fixes each side's five agents,
and with them the kits whose glyphs can appear. The menu witness (`menu`)
marks frames the settings menu covers. The chat box prints callout pings
[domain:hud/chat-broadcasts-callouts], and nothing reads it yet.

## The classes

Every class answers one question about one drawn object at one time. The
prior names the gallery the match allows; the full set is the surprise path.

| class | witnesses that exist | prior that narrows it | disagreement stored as |
|---|---|---|---|
| agent icon, self | `self_icon`, `teardrop` (self), `minimap.pick_self` | the player's agent (`player-agent`) | portrait against the self agent's art; a refusal keeps its reason |
| agent icon, ally | `minimap.ally_icons`, `icon_teardrop` (ally), portrait gate | the ally five (`side_candidates`) | gate rejects a detector fit: both kept, `unknown` with the gate's fit |
| agent icon, enemy | `minimap_ring_fit`, `icon_teardrop` (enemy), portrait gate | the enemy five | as ally; red portraits refuse [domain:minimap/red-portrait-states] |
| ability glyph | `minimap.detect_ability_discs`, `adjudication.gallery`, `ability_timeline` tray drops (self only) | the ten agents' kits, and only glyph facts recorded per ability | glyph against the kit's recorded glyphs; an unrecorded glyph is `unknown`, never a guess |
| ping (five kinds) | `ping` stream; owner's rule on the crop cache; chat callouts (unread) | the player's team only; five kinds | stream and gate disagree: `disputed` with both |
| X death mark, ally | `extract_minimap_death_marks` (blue); stored deaths | ally deaths of the round, before the frame | X without a death, or a death without an X: both kept with reasons |
| X death mark, enemy | `extract_minimap_death_marks` (red); stored deaths; killfeed weapon (gun or not) | enemy deaths of the round; gunfire kills leave one | as ally; an absent X on an ability or fall kill is expected, not a miss |
| "?" last known | none | enemies of the round last seen and not dead | not a witness until a fact is recorded |
| spike | `spike` (glyph, state, carrier); `spike_carrier` | one spike per round | carried glyph flags its carrier, never rejects it |
| smoke | `minimap_dark`, `adjudication.smokes`, `smoke_owner` | the ally kits' smokes only | lifetime and owner alternatives, as stored today |
| other ability area | `ability_shapes`, `detect_ability_walls`, `adjudication.ability` | the ten kits | per ability [domain:abilities/ability-rules-are-unique] |
| unknown | the refusal | none | carries the reason and every rejected alternative |

Glyphs the labels and facts already hold: Gekko's Wingman
[domain:abilities/gekko-wingman-plant-minimap], Astra's placed star
[domain:abilities/astra-star-ally-minimap-glyph], Skye's Trailblazer on the
enemy's side [domain:abilities/skye-trailblazer-enemy-minimap-glyph], Skye's
Guiding Light [domain:minimap/skye-bird-like-ally], and the thrown-ability
icons [domain:abilities/minimap-thrown-ability-icon]. The lineup admits a
glyph class only where its agent is on the side that draws it. Each other
ability's minimap drawing is asked per ability, never by analogy.

## How a verdict is formed

Each object keeps every witness's observation, with its version and time.
The verdict names one class with its alternatives, or `disputed` with
several, or `unknown` with its reason. A witness overrules the portrait gate
only where it observes the same object independently: its own rule on its
own evidence, not the red the gate also saw. The lineup is counted once,
through the gate; nothing here names an agent, which stays
`adjudication.identity`'s. A glyph binds to its caster only by a claim to
the arbiter.

Time orders the witnesses. An enemy killed by gunfire has an icon and then an
X at the same place [domain:minimap/enemy-death-mark]; a fit there within a
second of the death is `disputed` between the victim's icon and its X until
the order is observed. Pings are static for their lifetime, so an icon that
moves inside a ping's life is an icon.

## Stage 1: the prototype and its results

`prototypes/minimap_objects.py` (minimap-objects-0.1.0) recomputes the
gate's rows on the labelled items and on the gate's own 40-frame sample of
Lotus 5822b6646448 (C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) and
Ascent a06f04a0059f (C:\Users\grant\Videos\2026-08-26 09-56-37.mp4), and
adds two witnesses (predictions M1-M7, task `minimap-objects-20260929` of
the store's `notes/predictions.jsonl`):

- **W1, the ping stream:** a stored ping live at the fit's time within the
  ping owner's grouping distance. Danger pairs with the enemy key, standard
  with the ally key. W1b reruns the owner's rule over 24 s of crop cache
  round each enemy fit, as a diagnostic.
- **W2, an X born at a stored death:** the owner's colour extractor over the
  crop cache from 3 s before to 3 s after each death, a cluster first seen
  within 2 s before to 1 s after the killfeed time, present after and absent
  before; a fit of the victim's side in the same round on that place, whose
  own frame still holds an X, becomes `death_mark`.

**The ping stream names nothing.** No gate-kept fit on the labels, the
sample or the `labels/minimap` frames coincides with a stored ping
([metric:minimap_objects/labels@5822b6646448+a06f04a0059f#enemy_not_icon_ping_danger=0]
labelled enemy not-icons). The red triangle at Lotus 750-762 s is not in the
stream: the owner's rule over the cache splits it into eight danger groups
of 0.5 to 3.9 s, drawn inside a red ring, and rejects each by the 10 s
lifetime gate. The same rule sights real enemy icons as danger groups of
0.4 to 4.2 s and rejects them. The ping stream therefore cannot speak for
the kept triangles; M1 passed.

**X places, by side.** Ally deaths have an X born at their time on
[metric:minimap_objects/deaths@5822b6646448#ally_placed_frac=0.713] of
Lotus's and [metric:minimap_objects/deaths@a06f04a0059f#ally_placed_frac=0.759]
of Ascent's; enemy deaths on
[metric:minimap_objects/deaths@5822b6646448#enemy_placed_frac=0.367] and
[metric:minimap_objects/deaths@a06f04a0059f#enemy_placed_frac=0.516], with
[metric:minimap_objects/deaths@5822b6646448#enemy_ambiguous_frac=0.165] and
[metric:minimap_objects/deaths@a06f04a0059f#enemy_ambiguous_frac=0.108]
ambiguous. The death sheets (`death_x_<session>.png` in the store's
`analysis/minimap-objects-20260929/`) show most blue places on blue X marks.
About one place in five is not an X: red "?" marks, a red blob under the
spike glyph, enemy icons, and pale blue smoke discs. The extractor is a
colour and area test; it cannot tell an X from a "?", a ring or a disc.

**On the labels.** W2 names the Ascent X at 793.6 s a death mark, bound to
Skye's death at 791.0 s; the Lotus X at 2014.9 s it misses, since Chamber's
death at 2010.5 s has no X born (a portrait icon covers half of it). It also
names [metric:minimap_objects/labels@5822b6646448+a06f04a0059f#enemy_true_icon_death_mark=2]
of [metric:minimap_objects/labels@5822b6646448+a06f04a0059f#enemy_true_icon_n=17]
labelled enemy icons death marks: at Lotus 1334.1 s the X is first seen
0.4 s after the fit's frame, and the fit's own red ring passed the presence
test; at 1559.5 s the fit is the victim's icon at its death. On the sample it
leaves all [metric:minimap_objects/sample@5822b6646448#ally_agent_icon_ally=55]
Lotus and [metric:minimap_objects/sample@a06f04a0059f#ally_agent_icon_ally=55]
Ascent ally fits agent icons, and calls one kept
Lotus enemy fit a death mark
([metric:minimap_objects/sample@5822b6646448#enemy_death_mark=1]); the sheet
shows a live enemy icon. The Wingman glyph stays an agent icon: no witness
reads glyphs.

**On `labels/minimap`.** On up to 60 frames per session that hold a "?" or
other-red mark, the enemy detector finds
[metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#enemy_detected=39]
of [metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#enemy_n=58]
enemy marks, only
[metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#question_detected=2]
of [metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#question_n=40]
"?" marks and
[metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#other_red_detected=13]
of [metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#other_red_n=166]
other-red marks. Bs keeps every detected enemy and both detected "?"; W2
calls [metric:minimap_objects/minimap-labels@5822b6646448+a06f04a0059f#enemy_kept_death_mark=5]
labelled enemies death marks, and neither witness explains the kept red X
marks. The "?" is rarely a confuser of the enemy ring detector, and the gate
does not reject the two it finds.

**Against the predictions.** M1 and M5 passed. M2, M3, M4, M6 and M7 failed,
and the falsifier was met: W2 relabelled true icons. The ping stream holds
only lifetime-confirmed pings, so it cannot name a ping its owner fragments.
The death extractor is colour alone, and the victim's icon stands where its X
is born, so a place bound only by colour and time relabels real icons. The
next stage needs an X shape test and the observed order of icon and X, not a
tighter threshold. The prototype carries `"wire": "no"`.

## Next stages

1. Ask the player the questions below; record each answer as a domain fact.
2. An X shape reader, as a detector beside the death owner's extractor,
   scored on the labelled X marks; W2 then binds shape-confirmed X marks
   only, and a fit at a death place within the death transition is
   `disputed`.
3. A ping witness from the owner's sightings that keeps unconfirmed groups
   as `possible` pings with their fragment lifetimes, rather than the
   confirmed stream alone; and the chat callout reader as an independent
   witness.
4. The "?" reader, once its fact is recorded: a red ring around a "?" glyph,
   born where an enemy track ends, never counted as a visible enemy.
5. Glyph classes per kit, from recorded glyph facts, gated by the lineup.

## The label plan

The labelling-pass skill governs every pass below: blank start, `U` for
unsure, `A` back, `Q` quit, append-only JSONL under `labels/<kind>/`, the
last row for a key wins, and the candidate ringed in every panel.

**What exists.**

| labels | holds | serves |
|---|---|---|
| `labels/icon_facing_20260928.jsonl` (60 items) and `icon_facing_20260928/ability_candidates_verdicts.jsonl` | teardrop items, facing or not an icon; five verdicts (three Omen icons, Wingman, Trailblazer) | agent icon against not-icon, per side |
| `labels/minimap/` (Lotus, Ascent) | every enemy, "?" and other-red mark per frame | enemy recall; "?" and other-red confusers; other-red is not subdivided |
| `labels/minimap_agent/` (Ascent) | enemy marks with agent names; "?" marks | enemy identity; "?" positions |
| `labels/minimap_dynamic/` (3 sessions) | colour-free detections: nothing, ability, player, area, ping, x_mark, barrier, spike | glyph and area classes |
| `labels/unnamed_piece/` (19 sessions) | ally pieces the arbiter could not name: bare map, between icons, agent, spike, ability object, x_mark | ally-side confusers |
| `labels/death_icon/` (19 sessions) | death-bound portraits, agent or not a portrait | the portrait channel at deaths |

**What a pass must collect, per class.** Each pass draws candidates from the
detectors' output, stratified by what the stage-1 witnesses said, plus a
uniform stratum as the control.

- Other-red subclasses: the `labels/minimap` other-red marks split into
  X, danger ping, red ring with a white glyph, Reyna's blind, spawn barrier,
  red floor, other. One digit key per subclass, `7` other.
- X marks: at each stored death's time plus 1 s, the candidate places the
  extractor reports, asked "is the ringed thing an X, and which colour";
  a sample of `no_x_born` deaths asked "is there an X anywhere near".
- The death transition: for gunfire kills, frames from 1 s before to 1 s
  after the killfeed time at the victim's place, asked "icon, X, both or
  neither", to observe the order.
- Pings: owner groups the stream rejected, asked "ping (which kind) or not".
- "?" marks: after the fact is recorded, tracks that end without a death,
  asked where the "?" appears and when it goes.
- Glyphs: per agent in the lineup, detector fits the gate rejects or keeps
  near that agent's tray drops, asked "which ability, or not a glyph".

## Questions for the player

1. **The "?" mark.** When does it appear: the instant an enemy leaves vision,
   or after the brief trailing time? Where: the enemy's last drawn place?
   How long does it stay, and what ends it (vision again, death, round end)?
   Does an enemy that dies unseen leave a "?" rather than an X? (The Ascent
   death sheet shows a red "?" born at the killfeed time of two enemy deaths
   at 35.9 s.)
2. **X persistence.** Does an X stay until the round ends, or fade? Can two
   X marks at one place merge?
3. **The death transition.** For a gunfire kill, does the victim's enemy icon
   vanish in the same frame the X appears, or overlap it?
4. **The red triangle in a red ring** (Lotus 750-762 s at the centre-right):
   is it a danger ping, or another mark? Does a danger ping draw a ring round
   its triangle?
5. **The red disc with a white bar glyph** (Lotus 277.8 s and 1773.2 s): what
   is it?
6. **Enemy pings.** Does pinging an enemy draw an enemy-spotted marker on the
   minimap, and how does it differ from a danger ping?
7. **Wingman's other states.** Besides the plant, how does Wingman draw while
   it runs, and does it keep the teal ring and lobe of an ally icon?

## What this plan does not settle

- Every number above rests on two 465 px sessions; no 331 px or turned
  widget was scored.
- The death sheets were judged by eye on 72 places; no X label exists yet.
- The ally side of W1 (a standard ping on an ally icon) never fired in the
  sample, so its `disputed` rule is untested.
