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
sessions); `labels/minimap_agent` is the player's second pass over the
same Ascent marks (`label_icon_agent.py`), so it adds no new "?" places. Its
71 `claude-provisional` rows are enemy rows, which stage 2 leaves out of
scoring. The player's answers and the measurement below now
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

2b. **The trailing time.** The player places the delay he sees before a "?"
   in the icon drawn after the team's vision leaves its place
   [domain:minimap/vision-trailing-persistence]; measure it against the
   stored joined team vision.

## Stage 2: results

`prototypes/minimap_objects_s2.py` (minimap-objects-s2-0.1.0; task
`minimap-objects-c-20260929` of the store's `notes/predictions.jsonl`, one
prediction row per part, each logged before its run) scored each part once
on the player's labels and the gate's Lotus and Ascent sample. The sheets
are in the store's `analysis/minimap-objects-c-20260929/`.

**1. X by shape and order.** The shape test keeps a blob whose pixels lie on
two crossing diagonals with four arms. At the player's labelled points it
fires on both labelled X items, on
[metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#dynamic_x_mark_x=3]
of 3 `minimap_dynamic` X marks, on no labelled "?" (it rejects
[metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_question_not_x=83]
of 83), on
[metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_enemy_x=5]
of 286 enemy marks and
[metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#icon_facing_true_icon_x=1]
of 43 true icons, and on
[metric:minimap_objects_s2/x-labels@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_other_red_x=194]
other-red marks, which the sheet shows to be mostly red X marks. Binding a
death needs an X born at its time where a same-side icon ended: ally deaths
are placed at
[metric:minimap_objects_s2/x-deaths@5822b6646448#ally_placed_frac=0.553] and
[metric:minimap_objects_s2/x-deaths@a06f04a0059f#ally_placed_frac=0.563],
enemy deaths at
[metric:minimap_objects_s2/x-deaths@5822b6646448#enemy_placed_frac=0.266] and
[metric:minimap_objects_s2/x-deaths@a06f04a0059f#enemy_placed_frac=0.323],
lower than stage 1's colour rule but far cleaner: two of 36 tiles on each
death sheet show no X (a smoke over it, an icon covering it, the map
closed). The utility search placed one late X. X1, X2 and X4 passed; X3
failed on coverage.

**2. The "?" witness.** A red blob, not X-shaped, under no enemy icon, whose
red run walks back to an enemy icon at the place. It finds
[metric:minimap_objects_s2/question@5822b6646448+a06f04a0059f#question_witness=70]
of [metric:minimap_objects_s2/question@5822b6646448+a06f04a0059f#question_n=82]
of the player's "?" marks, and calls
[metric:minimap_objects_s2/question@5822b6646448+a06f04a0059f#enemy_witness=12]
of [metric:minimap_objects_s2/question@5822b6646448+a06f04a0059f#enemy_n=284]
enemy marks "?". Its timing came from the same instances, so this scores
its mechanics, not the timing. Away from any mark it is poor: of the 60
candidates on `question_candidates.png` about 8 are "?" marks; the rest are
enemy icons the ring detector misses, ally icons with red in their art, danger
triangles and frames with the map closed. It needs a "?" shape test as the X
has. Q1 passed, Q2 failed (under its falsifier), Q3 failed.

**2b. The trailing time.** On the 29 measured "?" instances, the icon was
tracked back from its last frame and read against the stored joined vision
(team_vision 0.3.0). On
[metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#lag_n=8]
instances the icon leaves the joined vision and is drawn on for a median
[metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#lag_median=0.5] s
(quartiles [metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#lag_p25=0.483]
to [metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#lag_p75=0.583] s),
then the "?" follows. On
[metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#status_in_vision_at_last_frame=12]
the stored vision still covers the place when the "?" appears, and on
[metric:minimap_objects_s2/trailing-lag@5822b6646448+a06f04a0059f#status_not_in_vision_in_track=9]
it never covers the tracked icon: the instrument disagrees with the game on
21 of 29, the cone's known error. The tinted sheets (`trailing_lag_1.png`,
`trailing_lag_2.png`) show the eight clean cases leaving the cone about half
a second before the swap. V2 passed; V1 and V3 failed. Half a second is a
candidate, not a fact: eight instances, one instrument.

**3. Ping kinds.** The ping owner's rule over every widget-drawn cached frame
confirms few pings at 15 Hz and refinds
[metric:minimap_objects_s2/ping@5822b6646448#stored_refound=19] of
[metric:minimap_objects_s2/ping@5822b6646448#stored_n=36] and
[metric:minimap_objects_s2/ping@a06f04a0059f#stored_refound=16] of
[metric:minimap_objects_s2/ping@a06f04a0059f#stored_n=46] stored pings.
Joining pulse-split danger groups gives
[metric:minimap_objects_s2/ping@5822b6646448#danger_joined=12] and
[metric:minimap_objects_s2/ping@a06f04a0059f#danger_joined=20] candidates; the
labelled triangle at 757.1 s is one, and no labelled true enemy icon lies on
one. On `ping_danger_joined.png` about two in five are pulsing triangles;
the rest are red X marks, "?" marks, Leer and enemy icons that also sit in
the danger hue for ten seconds. The X shape test already names the X marks,
so the next step is to cross-reference the two, not to tighten the join. P3
and P4 passed; P1 (761.1 s not covered) and P2 failed.

**4. Glyph templates.** Leer's template, mined at 277.8 s, matches the
held-out labelled Leer at 1773.2 s and ten other-red marks the sheet shows
are Leer. Trailblazer matches #23, its own source (not scored). No template
matches a labelled true icon, enemy or "?". The Wingman template failed: its
cited source frame (405.0 s) has Omen's icon over half the disc, and it
misses #15. Astra's star matches in
[metric:minimap_objects_s2/glyph@5822b6646448+a06f04a0059f+223d636bf8d2#astra_frames_matched=24]
of [metric:minimap_objects_s2/glyph@5822b6646448+a06f04a0059f+223d636bf8d2#astra_frames=29]
frames of 612-640 s, and across the 223d636bf8d2 sample it also matches
faint grey discs of the star's shape. G2 and G3 passed; G1 failed on
Wingman.

**Combined.** Applied to the gate's fits, the witnesses keep every labelled
true icon an agent icon
([metric:minimap_objects_s2/combined@5822b6646448+a06f04a0059f#labels_enemy_true_icon_agent_icon_enemy=17]
enemy, [metric:minimap_objects_s2/combined@5822b6646448+a06f04a0059f#labels_ally_true_icon_agent_icon_ally=24]
ally) and all 110 ally sample fits. They name both labelled X items death
marks, the Leer item a Leer glyph and #23 a Trailblazer. Three Bs-kept
not-icons stay agent icons: the two danger triangles (the joined candidate's
place, its first sighting, lies 12 px from the fit's centre) and the red floor dashes; the
Wingman glyph stays too. On the sample one kept Ascent enemy fit becomes a
death mark, and the sheet shows a live enemy icon. C1 and C3 passed, C2
failed. Every part stays `"wire": "no"`.

## Stage 2 on the current readers, and the enemy lane

`prototypes/enemy_lane_score.py` (enemy-lane-score-0.1.0; task
`enemy-lane-score-20260930` in the store's `notes/predictions.jsonl`, one
prediction row per part, each logged before its run) reruns stage 2 at
465 px on teardrop-0.4.0 and scores the enemy lane. It reads the crop cache
and stored streams only. Geometry comes through `reticle/geometry.py`; every
run read `built_by` 1ddd7c86… and `occ_built_by` 7135c737…, and no detector
here reads the occluder table. The Ascent npz was rewritten during the X run
with the same stamps; the loader reads each npz once, and the ring mode
reproduced stage 2 exactly. Mode `ring` keeps every ring-fit find at its
centre (stage 2's detector); mode `teardrop` keeps only finds the teardrop
reads, at the teardrop's centre.

**X.** The label counts do not move in either mode (the shape test reads no
enemy class): still
[metric:enemy_lane_score/x-labels-teardrop@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_enemy_x=5]
enemy marks and
[metric:enemy_lane_score/x-labels-teardrop@5822b6646448+a06f04a0059f+c62c2b06bcfb#minimap_other_red_x=194]
other-red marks called X. Ally deaths place as before. With the teardrop's
enemy list, enemy deaths on 5822b6646448 place at
[metric:enemy_lane_score/x-deaths-teardrop@5822b6646448#enemy_placed_frac=0.291]
against
[metric:enemy_lane_score/x-deaths-ring@5822b6646448#enemy_placed_frac=0.266];
a06f04a0059f stays at
[metric:enemy_lane_score/x-deaths-teardrop@a06f04a0059f#enemy_placed_frac=0.323].
XR1-XR3 held.

**"?".** The ring mode reproduces
[metric:enemy_lane_score/question-ring@5822b6646448+a06f04a0059f#question_witness=70]
of 82. The teardrop mode finds
[metric:enemy_lane_score/question-teardrop@5822b6646448+a06f04a0059f#question_witness=72],
calls
[metric:enemy_lane_score/question-teardrop@5822b6646448+a06f04a0059f#enemy_witness=17]
of 284 enemy marks "?" (up from 12: an icon the teardrop refuses leaves its
red to the "?" test), and cuts other-red calls from
[metric:enemy_lane_score/question-ring@5822b6646448+a06f04a0059f#other_red_witness=36]
to
[metric:enemy_lane_score/question-teardrop@5822b6646448+a06f04a0059f#other_red_witness=15]
and unmarked candidates from
[metric:enemy_lane_score/question-ring@5822b6646448+a06f04a0059f#candidates_labels_unmarked=46]
to
[metric:enemy_lane_score/question-teardrop@5822b6646448+a06f04a0059f#candidates_labels_unmarked=14].
QR1-QR3 held.

**The enemy proposal.** The ring fit proposes
[metric:enemy_lane_score/proposal@5822b6646448+a06f04a0059f#enemy_ring=225]
of 284 enemy marks, and the teardrop reads
[metric:enemy_lane_score/proposal@5822b6646448+a06f04a0059f#enemy_read=193]
of them; it refuses the rest mostly as `ambiguous_facing`
([metric:enemy_lane_score/proposal@5822b6646448+a06f04a0059f#enemy_refused_ambiguous_facing=21]),
a facing refusal the teardrop mode drops although the icon is real. On
other-red marks it reads
[metric:enemy_lane_score/proposal@5822b6646448+a06f04a0059f#other_red_read=5]
of 50 ring finds (refusals mostly `low_ncc`), and it reads none of the
[metric:enemy_lane_score/proposal@5822b6646448+a06f04a0059f#question_ring=4]
ring finds on "?" marks. EP1-EP4 held.

**Enemy identity.** The ally path, unchanged, names enemy icons:
`ally_portrait` features on the teal-and-self-excluding key,
`claims_from_ally_icons(side="enemy")` with the lineup's enemy five as the
gallery, and `adjudication.identity` deciding every name. The one change to
`reticle/` is that `side` argument; the ally default is unchanged. On
a06f04a0059f, whose lineup names all five enemies, the arbiter names
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_teal_self_named=70]
of the
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_proposed=70]
proposed player-labelled enemy marks, and
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_teal_self_right=70]
match the player's agent. No claim is refused; the eight unnamed marks
carry no ring-fit proposal. A red-only key refuses one on
`margin_below_gate`. The
[metric:enemy_lane_score/identity@a06f04a0059f#provisional_rows=71]
provisional rows are counted apart and none is an enemy mark. The perfect
score prompted controls, logged before they ran (IC1-IC3): the 29-agent
argmax is also right on
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_all29_right=70],
so on this match the five-agent prior adds nothing measurable (IC1 failed).
A decoy gallery (a Lotus enemy five) still names
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_decoy_named=20]
icons, wrongly on 13, so the margin gate does not guard against a wrong
gallery (IC2 failed low; IC3 held: the decoy's median fit is
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_decoy_fit_median=1.34365]
against
[metric:enemy_lane_score/identity@a06f04a0059f#player_enemy_fit_median=0.52555]).
Two "?" rows carry a proposal and are named; one names the player's agent
(ID4 failed). One match, one map: this is a consistency result, not an
accuracy figure for 331 px.

**Lineup coverage.** Every stored lineup, read through `load_lineup` with the
scoreboard constraint, names the enemy five with no blind slot:
[metric:enemy_lane_score/lineups@store#enemy_five_named=21] of
[metric:enemy_lane_score/lineups@store#lineups=21], the same as the ally
side. The lineup files alone name the enemy five on only
[metric:enemy_lane_score/lineups@store#enemy_five_named_in_file=2] and the
ally five on [metric:enemy_lane_score/lineups@store#ally_five_named_in_file=6];
the constraint resolves the rest. An enemy gallery therefore exists on every
session, but only through `load_lineup`. LC1 and LC2 held; LC3 failed after
the constraint.

**The 331 px queue.** `labels/enemy_lane_331_20260930/` holds a fixed-seed
sample (40 frames each on c40d950031bb, 223d636bf8d2 and bfad2778a372; 212
red opportunities), the prototypes' calls frozen in `calls.json` before any
answer, and a 60-item queue: 12 uniform over opportunities, then 12 each of
the enemy, X, "?" and other-red calls. Predictions QF1-QF5 are logged. The
player answers class and, for an enemy icon, the agent from the enemy five:

```powershell
.\.venv\Scripts\python.exe prototypes\label_enemy_lane_331.py
```

`enemy_lane_score.py --score331 --record` scores the answers by stratum.
Every part stays `"wire": "no"`.

## The label plan

The labelling-pass skill governs every pass below: blank start, `U` for
unsure, `A` back, `Q` quit, append-only JSONL under `labels/<kind>/`, the
last row for a key wins, and the candidate ringed in every panel.

**What exists.**

| labels | holds | serves |
|---|---|---|
| `labels/icon_facing_20260928.jsonl` (60 items) and `icon_facing_20260928/ability_candidates_verdicts.jsonl` | teardrop items, facing or not an icon; five verdicts (three Omen icons, Wingman, Trailblazer) | agent icon against not-icon, per side |
| `labels/minimap/` (Lotus, Ascent) | every enemy, "?" and other-red mark per frame | enemy recall; "?" and other-red confusers; other-red is not subdivided |
| `labels/minimap_agent/` (Ascent) | the player's agent names for the `labels/minimap` marks, and their "?" marks again; 71 enemy rows are `claude-provisional` | enemy identity from the player's rows only; the provisional rows are not ground truth |
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

1. Does an enemy stay drawn about half a second after leaving the team's
   vision, for every enemy? (Stage 2b measured it on eight instances.)
2. Can two X marks at one place merge into one?
3. Which ping kinds are static, and how long does each last on match
   footage?
4. What are the faint grey discs with the star's ring-and-notch mark on
   223d636bf8d2 (304 s, 498 s, 559 s, 1016 s): Astra stars in another
   state, or something else?
5. Wingman: a clean frame of its icon, not under another icon, for its
   template.

## What this plan does not settle

- Every number above rests on two 465 px sessions; no 331 px or turned
  widget was scored.
- The death sheets were judged by eye on 72 places; no X label exists yet.
- The ally side of W1 (a standard ping on an ally icon) never fired in the
  sample, so its `disputed` rule is untested.
