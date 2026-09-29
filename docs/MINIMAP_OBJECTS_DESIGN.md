# Minimap objects: a classifier that names every object

The player approved this classifier on 2026-09-29. It names every object
drawn on the minimap: agent icons, the glyphs the match's kits can draw,
pings, X death marks, enemy "?" marks, the spike, smokes and other ability
areas, and `unknown`, an explicit refusal. It is adjudication over stored
observations: each class has witness channels that already exist, a prior
that narrows its gallery, and a stored form for disagreement. The first
stage, `prototypes/minimap_objects.py`, cross-references the portrait
gate's kept fits with the ping stream and with X marks at stored deaths;
its results are below, and it failed its falsifier. The player answered its
questions the same day, and `prototypes/last_known_marks.py` measured the
enemy "?" mark; stage 2 below rests on both.

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
`question`. The player's labels hold "?" positions in `labels/minimap` (both
sessions); `labels/minimap_agent` holds more, mostly marked
`claude-provisional`. The player's answers and the measurement below now
record the mark [domain:minimap/last-known-mark]; no owner reads it yet.

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
| ping (five kinds) | `ping` stream; owner's rule on the crop cache | the player's team only; five kinds | stream and gate disagree: `disputed` with both |
| X death mark, ally | `extract_minimap_death_marks` (blue); stored deaths | ally deaths of the round, before the frame | X without a death, or a death without an X: both kept with reasons |
| X death mark, enemy | `extract_minimap_death_marks` (red); stored deaths; killfeed weapon (gun or not) | enemy deaths of the round; gunfire kills leave one | as ally; an absent X on an ability or fall kill is expected, not a miss |
| "?" last known | none yet; stage 2 builds one from the measured timing | the enemy icon that ended where the "?" begins | a "?" with no icon before it, or one outliving its timing: both kept with reasons |
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

## The "?" mark, measured

The player recalls that the "?" comes after a delay and stays a couple of
seconds, and asked for both to be measured [domain:minimap/last-known-mark].
`prototypes/last_known_marks.py` (last-known-marks-0.1.0; task
`minimap-objects-b-20260929` of the store's `notes/predictions.jsonl`)
follows each of the player's "?" marks in `labels/minimap` through the
crop cache. The death owner's red extractor finds the mark; the enemy ring
detector finds the icon before it; the mark's red contrast against a floor
annulus times its fade. Of
[metric:last_known_marks/timing@5822b6646448+a06f04a0059f#instances=36]
instances, [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#measured=29]
were measured.

- **The swap.** The "?" appears one cache frame after the icon's last frame
  on every measured instance: median
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#delay_median=0.083] s,
  at most [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#delay_max=0.083] s,
  at the icon's place. No blank frame falls between. The delay the player
  sees lies before the swap, while the enemy stays drawn after leaving
  vision [domain:minimap/vision-trailing-persistence]; the team's light was
  not read, so that interval is not measured.
- **The life.** Of the
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#ending_vanished=19]
  marks that vanish, the fade begins at a median
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#fade_start_median=1.95] s
  and the mark is gone at a median
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#gone_median=3.083] s,
  quartiles [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#gone_p25=3.033]
  to [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#gone_p75=3.183] s:
  a fixed timer. The other
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#ending_icon_returned=10]
  end when the enemy's icon returns at the place, after a median
  [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#returned_after_median=1.583] s.
- **The instrument.** The red extractor loses the fading mark early, at a
  median [metric:last_known_marks/timing@5822b6646448+a06f04a0059f#duration_median=2.733] s;
  a witness must read the fade, not the extractor's run. Three of the 19 on
  the sheets are odd: the widget closes (Ascent 539.9 s), a red X lies under
  the "?" (Ascent 1161.9 s), and two "?" overlap a blue X (Lotus 2008.7 s).
  The sheets are `question_marks_1.png` and `question_marks_2.png` in the
  store's `analysis/minimap-objects-b-20260929/`.

Predictions K1-K5 passed; the fade reading was added after a smoke test of
five instances and logged as a correction before the full run. The fact is
[domain:minimap/last-known-mark-timing].

## The player's answers

The player answered the stage-1 questions on 2026-09-29, and each answer is
a domain fact:

- X marks stay until the round ends; an ally's is always drawn, an enemy's
  only while its place is in vision [domain:minimap/death-mark-persistence].
- The victim's icon and its X are one thing for reading
  [domain:minimap/death-icon-becomes-mark].
- An enemy killed by utility while a "?" may leave no X until its place is
  seen [domain:minimap/unseen-utility-death-mark].
- The red triangle at Lotus 750-762 s is a danger ping, the kind with radial
  pulses [domain:minimap/danger-ping-pulses]. The pulses explain stage 1's
  finding that the ping owner splits it into short groups.
- The red disc with a white bar is an enemy Reyna's Leer
  [domain:abilities/reyna-leer-enemy-minimap-glyph].
- Wingman draws like Skye's Trailblazer in its side's colour, with an arrow
  [domain:abilities/gekko-wingman-minimap-icon], and, as he recalls, moves in
  straight lines that reflect off walls
  [domain:abilities/gekko-wingman-straight-bounce].
- The automatic "enemy spotted" voice line and chat message draw nothing on
  the minimap [domain:minimap/spotted-callouts-draw-nothing], so no
  enemy-spotted class exists. The chat message is a possible future witness:
  the game itself names an enemy agent and a place at a time. No chat reader
  exists yet.

## Stage 2

Each part cross-references a channel that already observes the object, and
each is scored on labels before any threshold moves.

1. **X by shape and order.** An X shape test beside the death owner's colour
   extractor, scored on labelled X marks. W2 binds a stored death only to a
   shape-confirmed X at a place where the victim's icon ended at the death's
   time [domain:minimap/death-icon-becomes-mark]; the X then holds its place
   to the round's end [domain:minimap/death-mark-persistence], so an enemy X
   leaving view is not an absence, and a missing enemy X after a "?" waits
   for the place to be seen [domain:minimap/unseen-utility-death-mark].
2. **A "?" witness from the measured timing.** A red "?" at the place where
   an enemy icon ended in the frame before, fading from about 2 s and gone
   by about 3.3 s, or replaced by the icon's return. A "?" with no icon
   before it, or one that outlives the timing, is kept with its reason.
3. **Ping kinds.** A ping witness from the owner's sightings that keeps the
   danger ping's pulse-split groups as one candidate over its 10 s life,
   and the other kinds as the owner confirms them; the kinds the player
   calls static and shorter are checked on the stream before any rule
   assumes it.
4. **Glyph templates from the recorded facts.** Leer, Wingman, Trailblazer
   and Astra's star [domain:abilities/astra-star-ally-minimap-glyph], each
   admitted only where its agent is on the side that draws it, scored on
   the labelled glyph items; Wingman's straight-line motion is checked on
   tracks before a reader relies on it.

## The label plan

The labelling-pass skill governs every pass below: blank start, `U` for
unsure, `A` back, `Q` quit, append-only JSONL under `labels/<kind>/`, the
last row for a key wins, and the candidate ringed in every panel.

**What exists.**

| labels | holds | serves |
|---|---|---|
| `labels/icon_facing_20260928.jsonl` (60 items) and `icon_facing_20260928/ability_candidates_verdicts.jsonl` | teardrop items, facing or not an icon; five verdicts (three Omen icons, Wingman, Trailblazer) | agent icon against not-icon, per side |
| `labels/minimap/` (Lotus, Ascent) | every enemy, "?" and other-red mark per frame | enemy recall; "?" and other-red confusers; other-red is not subdivided |
| `labels/minimap_agent/` (Ascent) | enemy marks with agent names; "?" marks, most by `claude-provisional` | not ground truth until the player confirms them |
| `labels/minimap_dynamic/` (3 sessions) | colour-free detections: nothing, ability, player, area, ping, x_mark, barrier, spike | glyph and area classes |
| `labels/unnamed_piece/` (19 sessions) | ally pieces the arbiter could not name: bare map, between icons, agent, spike, ability object, x_mark | ally-side confusers |
| `labels/death_icon/` (19 sessions) | death-bound portraits, agent or not a portrait | the portrait channel at deaths |

**What a pass must collect, per class.** Each pass draws candidates from the
detectors' output, stratified by what the stage-1 witnesses said, plus a
uniform stratum as the control.

- Other-red subclasses: the `labels/minimap` other-red marks split into
  X, danger ping, Reyna's Leer, spawn barrier, red floor, other. One digit key per subclass, `7` other.
- X marks: at each stored death's time plus 1 s, the candidate places the
  extractor reports, asked "is the ringed thing an X, and which colour";
  a sample of `no_x_born` deaths asked "is there an X anywhere near".
- The death transition: for gunfire kills, frames from 1 s before to 1 s
  after the killfeed time at the victim's place, asked "icon, X, both or
  neither", to observe the order.
- Pings: owner groups the stream rejected, asked "ping (which kind) or not".
- "?" marks: witness candidates on sessions other than the two measured,
  asked "is the ringed thing a '?'", to score the stage-2 witness away from
  the frames its timing came from.
- Glyphs: per agent in the lineup, detector fits the gate rejects or keeps
  near that agent's tray drops, asked "which ability, or not a glyph".

## Questions still open

1. How long does an enemy stay drawn after leaving the team's vision, before
   its "?" appears? (Measurable: read the team's drawn light at the icon.)
2. Can two X marks at one place merge into one?
3. Which ping kinds are static, and how long does each last on match
   footage? (Measurable on the stream once the danger ping's groups join.)

## What this plan does not settle

- Every number above rests on two 465 px sessions; no 331 px or turned
  widget was scored.
- The death sheets were judged by eye on 72 places; no X label exists yet.
- The ally side of W1 (a standard ping on an ally icon) never fired in the
  sample, so its `disputed` rule is untested.
