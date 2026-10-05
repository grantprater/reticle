# The minimap ability-glyph channel

This plan wires the game's minimap ability textures into production as a
channel that names the ability a minimap disc draws, and through the kit
that holds it, the agent who cast it. It answers BACKLOG item 2(a). The
evaluation it builds on is `prototypes/minimap_glyph_eval.py`
(`minimap-glyph-eval-0.2.0` on master, `0.3.0` on `killjoy-refs-20261004`;
wire: no); the measurements it rests on are `prototypes/glyph_channel_cost.py`
(`glyph-channel-cost-0.2.1`, wire: no), logged in the store's
`notes/predictions.jsonl` as `glyph-wiring-design-20261004` W1-W13 (0.1.0)
and G1-G4 (0.2.0), with the corrections and the stage 1 predictions of
`glyph-wiring-design-fix-20261004`. The rules it obeys live in `AGENTS.md`;
this document cites them and never restates them. Revised 2026-10-04 with
the clean held-out score, the player's rotation answers, the two-flag
rotation test and the cross-channel independence measurement
(`cross-channel-independence-20261004`).

## 1. What the measurements decide

**The clean held-out score clears the bar.** On labels nobody tuned on
(`minimap-heldout-score-20261004`, H1-H8), the prototype's follow named
[metric:glyph_channel_cost/heldout_020#headline_follow_right=102] of
[metric:glyph_channel_cost/heldout_020#headline_n=139] headline marks, the
single frame [metric:glyph_channel_cost/heldout_020#headline_base_right=100],
none refused. The Killjoy Alarmbot fix (eval 0.3.0, K5) left the headline at
[metric:glyph_channel_cost/heldout_030#headline_follow_right=102] while the
dev session went from
[metric:glyph_channel_cost/heldout_020#dev_session_follow_right=15] to
[metric:glyph_channel_cost/heldout_030#dev_session_follow_right=21] of
[metric:glyph_channel_cost/heldout_030#dev_session_n=21]. With the player's
Chamber correction (the marks re-answered Chamber:E) the headline is
[metric:glyph_channel_cost/heldout_030#corrected_headline_follow_right=103];
the player was re-asked only where the matcher disagreed, so the corrected
score is biased upward and the uncorrected one stays the headline. The first
recording of the corrected score wrote 102 (store `notes/metrics.jsonl`,
the two `heldout_*` rows at 15:34:11); those rows stay, a correction row in
`predictions.jsonl` names them, and the later rows carry the right value.
The labels are now spent: no arm in this plan is chosen on them.

**The misses are ontology, not pixels.** The headline confusions are led by
Astra:E named Astra:Q
([metric:glyph_channel_cost/heldout_020#astra_e_to_q=12] marks) and Omen:E
named Omen:Q ([metric:glyph_channel_cost/heldout_020#omen_e_to_q=7]). The
outcome row's provisional visual reading (store `notes/predictions.jsonl`,
the `minimap-heldout-score-20261004` outcome) puts every Astra:E mark on a
smoke disc, and most Omen:E marks on a smoke disc or a ring: shapes a glyph
matcher cannot name and `minimap-dark` owns. So the Astra rule below fixes
none of the held-out Astra misses, and the held-out confusions say nothing
about how often the glyph will tie on Astra or Omen icons. The icons that do
reach the glyph need rules from each ability's facts, not a better pixel
pair [domain:abilities/ability-rules-are-unique]:

- A placed Astra star is a pending ability, not yet a smoke, concuss or well;
  which it becomes is read when it turns
  [domain:abilities/astra-star-placed-then-turned]
  [domain:abilities/astra-star-ally-minimap-glyph]. The star states on the
  minimap are being recorded on `astra-star-states-20261004`
  (`astra-star-minimap-states`, not yet in master).
- Omen's Paranoia travels: it leaves his icon 0.5 s after the tray drop, is
  40-70 px away by 1 s and gone by 2 s
  [domain:abilities/omen-paranoia-minimap-icon]. A Dark Cover stays where
  it lands: a target icon from 0.5 s, a grey disc from 2-4 s, seen to +8 s on
  every census cast [domain:abilities/omen-dark-cover-minimap-phases]. Motion
  and lifetime separate them; the glyph scores only break a tie the track
  leaves. The fact's pixel distances were read on demo captures whose widget
  scale it does not state, so the motion cut waits until that scale is
  recorded (section 2, the Omen rule).

This contradicts the first draft's P4, which expected ties on Skye and Sova.

**The proposer finds most icons; it costs; the glyphs do not.** A proposer
disc lay within 8 px x scale of
[metric:glyph_channel_cost/heldout_020#found_raw=106] of
[metric:glyph_channel_cost/heldout_020#icon_marks=143] headline icon marks.
On 100 cached minimap frames of c40d950031bb
(`C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`, 331 px crop),
`ability_icons.propose_icons` took
[metric:glyph_channel_cost/cost@c40d950031bb#propose_ms=44.8] ms per frame
(median), and scoring every proposed disc against the ally candidate set's
glyphs, every rotation searched, took
[metric:glyph_channel_cost/cost@c40d950031bb#bank_a_ms=3.4] ms. On
a06f04a0059f (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`, 465 px) the
proposer took [metric:glyph_channel_cost/cost@a06f04a0059f#propose_ms=148.2]
ms and the glyphs [metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_ms=5.6]
ms. The same bank on the GPU took
[metric:glyph_channel_cost/cost@c40d950031bb#bank_a_gpu_ms=0.86] and
[metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_gpu_ms=0.75] ms.
`ability_icons.verify_icons`, which rescores the previous frame's discs
locally, took [metric:glyph_channel_cost/cost@c40d950031bb#verify_ms=1.06]
and [metric:glyph_channel_cost/cost@a06f04a0059f#verify_ms=1.08] ms. The
prototype's `follow` reruns the proposer on every cached frame for 3 s
after each label; production must never do that.

**A random-access crop read costs more than the glyphs.** Reading one
cached minimap crop alone took
[metric:glyph_channel_cost/births@c40d950031bb#read_ms=62.2] ms (median).
The reader must ride a pass that already reads the crop cache in order,
never fetch frames one at a time.

**A shared threshold sits under the null.** All
[metric:glyph_channel_cost/births@c40d950031bb#new_at_or_above=50] of the
[metric:glyph_channel_cost/births@c40d950031bb#new=50] new discs at 2 Hz
on c40d950031bb scored at least 0.4 against the ally set (median
[metric:glyph_channel_cost/births@c40d950031bb#best_q50=0.626]). Against
the labelled caster's kit, every rotation searched, a share
[metric:glyph_channel_cost/null#not_at_or_above_04=0.9917] of the player's
labelled non-ability discs scored at least 0.4 (median
[metric:glyph_channel_cost/null#not_p50=0.543], 90th percentile
[metric:glyph_channel_cost/null#not_p90=0.664]); labelled icons score a
median [metric:glyph_channel_cost/null#pos_p50=0.875]. The follow's
`ICON_SCORE` gate therefore admits every disc. A maximum over thousands of
templates is high on noise. The null is the channel's open-set path: a disc
whose best key does not clear that key's null, measured per bank and per
key, refuses as `below_null` (no ability, or one outside the bank) and goes
to the surprise path; nothing is named by elimination.

**Rotation is per key; a game-data rule fits most answers, unproven.** The
player answered the rotation questions on 2026-10-04
(`labels/minimap_glyph_questions/answers.jsonl`, `rotation:*` rows):
Cypher:E, Omen:E and Killjoy:Q turn; of Deadlock:Q the player said "I think
it could be any angle but it is always normal to the wall"; Deadlock:C,
Reyna:C, Skye:E, Skye:Q and Sova:C stay upright; Cypher:C and Skye:X are
unsure. The Killjoy:Q answer was logged 8 s after prediction G1, about three
minutes before the run. `bRotates` alone contradicts the answers (Reyna:C
and Deadlock:C set it and stay upright). A hypothesis, not a domain fact,
fits them better:

> An icon turns iff its minimap component's `bRotates` XOR
> `RotationSpace == AMRS_ConstantMinimap`; `RotationSource == AMRSRC_Upright`
> forces upright; a component that sets none of the three (Skye's and
> Sova's `Comp_Actor_AresFastMinimapPill`) stays upright.

`glyph_channel_cost.py rotrule` read every minimap component of the raw
ability-states export, merged down its class chain (the derived table
`ability-states-gamedata-0.2.0` drops `RotationSource` and some targeting
components), and joined
[metric:glyph_channel_cost/rotation_rule#keys_with_component=45] catalogue
keys by texture. Of [metric:glyph_channel_cost/rotation_rule#answers_sure=9]
sure answers the rule agrees with
[metric:glyph_channel_cost/rotation_rule#answers_agree=7]. The two it misses,
Deadlock:Q and Omen:E, are mixed keys: their targeting or projectile
component reads turns, and their placed object
(`GameObject_StealthingTrap_SoundSensor`, `FXC_Wraith_4_ChargeMarker_Parent`)
sets no flag and reads upright. Prediction G1 said 8 of 8, falsified at 6 or
fewer; on those 8 answers the rule agrees with 6 (7 of 9 minus Killjoy:Q;
correction row glyph-wiring-design-fix-20261004, ts
2026-10-04T22:19:35.822601Z), so G1 failed on its own falsifier. The count
with any one component deciding
([metric:glyph_channel_cost/rotation_rule#answers_agree_some_component=9])
is no evidence: a mixed key agrees with any answer. The rule was framed after
8 of the 9 answers were seen; only Killjoy:Q tests it out of sample, and it
agrees (1 of 1, the same correction row). The visible behaviour of both
placed icons is answered: the sensor is normal to the wall (L349) and the
Dark Cover marker turns (L350); the rotated sonic square seen on `sonic-square-20261004` agrees for the
sensor. Which game component draws each placed icon is game-data work, not
a question for the player.

The dev fits agree where they can: on the right dev items of eval 0.3.0,
[metric:glyph_channel_cost/rotation_rule#dev_rotates_near_zero=18] of
[metric:glyph_channel_cost/rotation_rule#dev_rotates_items=55] items of
rule-rotating keys fit within 15 deg of upright; Cypher's Trapwire and
Killjoy's Alarmbot (Q_InActive: no `bRotates`, ConstantMinimap) fit far from
upright (`rotrule.json`, `dev_angles`). Every near-upright fit is Cypher:E,
which the player says turns: the dev cameras faced near north, or the glyph
is near symmetric at that scale, so a dev fit near 0 proves nothing. No dev
item falls on a rule-upright key, so G3's upright side is untested.

Searched as a per-key policy (the rule's
[metric:glyph_channel_cost/rotation_rule#rotating_keys=18] rotating keys,
[metric:glyph_channel_cost/rotation_rule#mixed_keys=9] of them mixed,
rotated; the rest upright), the single-frame matcher named
[metric:glyph_channel_cost/rotation_rule#heldout_policy=174] of
[metric:glyph_channel_cost/rotation#heldout_n=192] stored windows and
[metric:glyph_channel_cost/rotation_rule#dev_policy=53] of
[metric:glyph_channel_cost/rotation#dev_n=59] dev, against
[metric:glyph_channel_cost/rotation#heldout_rotate_all=164] for rotating
every key, [metric:glyph_channel_cost/rotation#heldout_gamedata_policy=155]
for `bRotates` alone and
[metric:glyph_channel_cost/rotation_rule#heldout_upright=157] upright (the
control, reproduced exactly). Prediction G4 put the policy between the
`bRotates`-only policy and rotate-all; it overshot that range and beat
rotate-all, so G4 held only on its falsifier clause (no better than
upright). The overshoot is a surprise, logged in the correction row; its
cause is unmeasured (one candidate: upright keys searched at one rotation
win less often on noise).
These windows are contaminated: the matcher and the follow were chosen on
them, and the player saw their crops before answering. They are also the
eval 0.2.0 windows, not stage 1's. They size the design; they gate nothing.

**Naming the caster is easier than naming the slot.** Widening the
candidate set from the labelled caster's kit to the ally candidate set
(named slots plus each refused slot's best guess and rival) took the slot
right from
[metric:glyph_channel_cost/rotation#ally_rotate_all_caster_kit_right=152]
to [metric:glyph_channel_cost/rotation#ally_rotate_all_ally_set_right=144]
of [metric:glyph_channel_cost/rotation#ally_rotate_all_items=178] items,
and the caster agent was right on
[metric:glyph_channel_cost/rotation#ally_rotate_all_ally_set_agent_right=155].
The identity claim needs only the caster; a slot refusal must not withhold
it.

**The prior carries most discs.** At the cache's hold spacing
([metric:glyph_channel_cost/cost@c40d950031bb#hold_gap_ms=66.7] ms), a share
[metric:glyph_channel_cost/cost@c40d950031bb#prior_share=0.954] of discs lie
within 2 px x scale of a disc of the frame before; at the ability pass's
2 Hz the stored streams give
[metric:glyph_channel_cost/prior2hz@c62c2b06bcfb#prior_share=0.52] (c62c2b06bcfb,
`C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`) to
[metric:glyph_channel_cost/prior2hz@c40d950031bb#prior_share=0.78]
(c40d950031bb).

**A follow seeded at the self icon is no channel.** The cross-channel
independence measurement (`cross-channel-independence-20261004`, store
`analysis/cross-channel-independence-20261004`) ran the glyph follow on the
player's own casts on the matches, seeded at the self icon at the tray drop.
On the casts of abilities that draw a glyph it named a slot right
[metric:glyph_channel_cost/cross_channel@matches#glyph_self_seed_right=69]
times and wrong
[metric:glyph_channel_cost/cross_channel@matches#glyph_self_seed_wrong=50]
(named precision
[metric:glyph_channel_cost/cross_channel@matches#glyph_self_seed_precision=0.5798]),
and on [metric:cross_channel_independence/glyph_control@matches#not_drawn_casts=118]
casts of abilities that draw nothing it still named a slot
[metric:cross_channel_independence/glyph_control@matches#named_a_slot=35]
times. Section 1 first named the seed as the cause: the thrown glyph is
already beyond the follow's starting reach at the drop frame, 4 px times
the widget scale (`REACH[0]` in `prototypes/minimap_glyph_eval.py`). An
instance is Undercut
on 4f207c0c4e39 (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`), the Iso:Q
cast at `t_ms` 232500 in the store's
`analysis/cross-channel-independence-20261004/casts.jsonl`, where audio named
Q and the follow kept the self icon and named Iso:E. Stage 1's S5
falsified that belief (section 6): seeded at the thrown icon instead, the
follow's precision did not rise, and on the
[metric:glyph_tables/thrown@matches#paired_both_named=43] casts both seeds
named, both were wrong on
[metric:glyph_tables/thrown@matches#paired_both_wrong=15], the self seed
alone was right on [metric:glyph_tables/thrown@matches#paired_self_only_right=6]
and the thrown seed alone on
[metric:glyph_tables/thrown@matches#paired_thrown_only_right=3]. The seed
is not the main cause of the self seed's errors; the cause is open.

**Audio can label the player's own glyphs.** On the same casts the audio
witness (`ability-audio` [owns:ability-audio], ability-audio-0.4.0, params
0.2.6) named the slot with precision
[metric:glyph_channel_cost/cross_channel@matches#audio_precision=0.9814]
([metric:glyph_channel_cost/cross_channel@matches#audio_right=211] right,
[metric:glyph_channel_cost/cross_channel@matches#audio_wrong=4] wrong,
[metric:glyph_channel_cost/cross_channel@matches#audio_refused=11]
refused), and
[metric:glyph_channel_cost/cross_channel@matches#audio_sova_skye_precision=0.9856]
on Sova:C and Skye:Q, E and X, which hold almost all of them. The label
path rests on that precision, not on independence. Audio and minimap
failures are not shown independent: the correction row of
cross-channel-independence-20261004 (store `notes/predictions.jsonl`, ts
2026-10-04T22:17:25Z) calls the pooled odds ratio a Simpson's-paradox
artefact, because glyph casts pair rare audio failure with common minimap
failure and shape casts the reverse. Stratified by minimap source, the
Mantel-Haenszel odds ratio is
[metric:cross_channel_independence/stratified_source@matches#or_mh=2.694]
(CI [metric:cross_channel_independence/stratified_source@matches#ci_low=1.105]
to [metric:cross_channel_independence/stratified_source@matches#ci_high=6.57]):
inconclusive under the registered rule, and leaning against independence.
Part of the coupling is built in: every channel anchors on the tray drop
(audio's cast frame and window, the glyph window's start, the shape owner's
drop time), so a wrong tray cast fails them together and their agreement
cannot catch it. On glyph casts the follow seeded at the self icon fails on
its own, not jointly: it fails on
[metric:cross_channel_independence/glyph@matches#p_b_fail=0.673] of them,
audio on [metric:cross_channel_independence/glyph@matches#p_a_fail=0.0711],
and both on [metric:cross_channel_independence/glyph@matches#p_both=0.0521];
that stratum's odds ratio
[metric:cross_channel_independence/glyph@matches#or_cmle=1.363] (CI
[metric:cross_channel_independence/glyph@matches#or_ci_low=0.385] to
[metric:cross_channel_independence/glyph@matches#or_ci_high=6.096]) cannot
tell coupling from independence.

So a disc born where the player's thrown glyph flies can be a borrowed glyph
label. It declares `rests_on` both the audio witness, with its version and
params, and the tray drop it was anchored on (`tray_drop:<sid>:<t_ms>`, the
`player_cast` whose slot `ability-cast` decides; audio corroborates). Such
labels cover only the player's own casts of Sova:C and Skye:Q, E and X,
where audio's precision is measured; Iso:Q and Iso:C hold
[metric:cross_channel_independence/corrections@matches#iso_q_casts=3] and
[metric:cross_channel_independence/corrections@matches#iso_c_casts=3] casts,
too few to call safe. They enter only the dev side of stage 1, and a fit
made from them (the null table's cut, the follow comparison) is scored only
on the player's own labels, never on borrowed ones. They are never an
identity claim: `ability-audio` is not pooled into `agent-identity`.
Shape-owner casts couple with audio more strongly (odds ratio
[metric:cross_channel_independence/shape@matches#or_cmle=7.208]), and the
shape owner is told the truth slot, so the label path stays on glyph
abilities.

## 2. The parts

The channel has four parts, each with its own owner, stamp and stream.
The proposer exists; the other three are proposed.

| Part | Owner | Stream | Reads | Decides |
|---|---|---|---|---|
| Proposer (exists) | `ability_icons` [owns:ability-icon] | `ability_icon` | crop cache | where dark discs are |
| Glyph reader | `minimap_glyph` (new) | `ability_glyph` | crop cache, `ability_icon` rows, lineup, policy and null tables | each disc's score per candidate texture |
| Disc tracks | `adjudication.ability` (new function) | `ability_disc_track` | `ability_icon`, `ability_glyph` | which observations are one object |
| Glyph verdict | `adjudication.ability_glyph` (new) | `ability_glyph_name`, `ability_glyph_identity` | the tracks, `team_vision`, `tray_kit`, the lineup, the null table | each track's ability and the claim on its caster |

The aggregator, `adjudication.identity` [owns:agent-identity], decides the
caster's name, as for every name.

### The glyph reader

**Where it runs.** It joins the ability pass (`reticle scan <sid> --only
ability`), which rereads the minimap crop cache at 2 Hz on live spans, as a
`passes.Reader`. Sharing the pass is an execution optimisation: the reader
keeps its own stamp (`ability-glyph-0.2.0`), and a change to the proposer
restamps it only through its declared input. It reads the proposer's
candidates for the same frame, never reruns the proposer, and never
decodes video.

**The follow.** A disc the frame before does not carry (a birth) opens a
follow window of up to 3 s (a design choice). Inside it the reader takes the
cache's held frames, every one, and tracks the disc by `verify_icons` from
its last fix, searching wider each frame it misses, as the prototype's reach
does. Each fix declares `rests_on` the fix before it. The window ends after
eight scored frames or at 3 s (design choices). Dense sampling here is gated
on opportunity (a birth), not outcome. Whether the follow at the cache's
cadence beats the same follow over the 2 Hz frames alone is stage 1's
question; the 2 Hz arm costs no extra reads.

**The candidate set.** Per frame, the reader scores the textures the
match's context allows: the ally side's kits, each texture whose game-data
row (`ability-states-gamedata-0.2.0`) does not mark the frame's view
`false`, and the enemy side's kits, only textures an enemy sees. The
sides come from the lineup's verdicts, each refused slot admitting its best
guess and rival, as the arbiter admits rivals. Each frame row declares
`rests_on` the lineup file and version. The full set, every agent's kit,
runs on two paths, stored apart:

- the audit: every tenth birth (a cadence fixed here, a design choice),
  scored against every kit, every key rotated, through its window; these
  rows carry `audit: true` and measure what the lineup prior and the
  rotation policy hide;
- the surprise: a disc whose best candidate stays under its key's null
  through its window is rescored against every kit, `surprise: true`,
  never an audit sample.

The full set costs [metric:glyph_channel_cost/cost@c40d950031bb#bank_c_ms_per_disc=2.75]
ms per disc against [metric:glyph_channel_cost/cost@c40d950031bb#bank_a_ms_per_disc=1.29]
for the ally set on c40d950031bb.

**The rotation policy, per key.** A stored table
(`glyph-rotation-policy-0.1.1`), one row per catalogue key, each row citing
what decided it, in this order:

1. A sure player answer decides. `upright`: 0 deg only. `rotates`: 0-345 deg
   by 15. Deadlock:Q, normal to the wall: the two normals of the sensor's
   wall, plus or minus 15 deg, when a sonic-square fit at that place gives the
   wall (`sonic-square-20261004`, not yet in master); all rotations when none
   does. Each answer becomes one domain fact per ability before the table
   cites it.
2. Without an answer, the two-flag rule over every component that draws
   the key's textures: all upright gives 0 deg; any component turning, a
   mixed key, or a `RotationSource` the rule does not read (Custom,
   Rotation, None) gives all rotations. The row stores each component's
   flags and verdict, so a later answer that contradicts the rule is a
   stored surprise against the hypothesis, not a silent override. This
   step carries a risk: an unanswered key the rule calls upright is
   searched only upright on a hypothesis fitted to other abilities'
   answers, not on its own fact. The audit path, which rotates every key,
   measures what that hides; a key whose audit fits turn is a surprise
   that reopens its row. A key no minimap component draws has no flags to
   read: it is upright by default, unverified (`no_component_default`),
   never a rule decision.
3. Every rotated key's null is measured at its own search size (the
   per-key null), because a key searched over 24 times more templates wins
   on noise; the audit path rescores with every key rotated.

The stored fit angle of a turning key is an observation; it becomes a
placement fact only where an ability's fact says what the angle means (the
Alarmbot's facing, the sensor's wall).

**The textures.** Each ability's DisplayIcon and its exported minimap
textures, assigned by the player's texture answers
([domain:abilities/minimap-textures-deadlock] and its siblings, one fact
per agent) or by DisplayIcon correlation where no answer exists, with the
export build and inventory versions in the stamp. Game files, never mined
captures. Of the [metric:glyph_channel_cost/gamedata_minimap#minimap_abilities=71]
abilities with a minimap component in the game data,
[metric:glyph_channel_cost/gamedata_minimap#abilities_with_png=49] have an
exported texture.

**Pixels.** Luma inside an r = 8.5 px x scale disc, masked Pearson, never
binarised; templates shrink with `INTER_AREA` and turn with linear
interpolation [domain:capture/capture-resolution]. All discs of a frame
score in one matrix product, on the GPU when one is present; no per-disc
Python loop.

**Stored row (`ability_glyph`).** A coverage row: the stamp; inputs
(`ability_icon_version`, `roi_cache_version`, the lineup's file and
version, the glyph bank's digest: build, inventory, export, answers file
hash, states table, rotation policy table); the matcher's parameters; the
candidate set per side with why each agent is in it; the audit cadence;
counts by reason. One row per scored frame and disc:
`{t_ms, frame_idx, disc: "ability_icon:<sid>:<t_ms>:<i>" or a follow fix
{cx, cy, r, rests_on}, set: "context"|"audit"|"surprise", scores:
{"<agent>:<slot>": [score, texture, canvas, rot, dx, dy]}, best, second,
margin}`. An unread frame keeps its reason: `not_live`,
`widget_not_drawn`, `no_ability_icon_row`, `off_crop`,
`geometry_size_mismatch`, `no_lineup`. The reader names nothing.

### Disc tracks

`ability-icon`'s entry routes tracks to `adjudication.ability`
(`not_for`: "tracks and lifecycles"), so the track joins there as
`disc_tracks`, pure over stored rows: a 2 Hz birth, its follow fixes, and
the later 2 Hz candidates its verify keeps. A track ends when the verify
loses it (`score` None, stored) or the round ends. Track ids are
`<sid>:adisc:<birth_t_ms>:<i>`. Each track stores its path length, its
speed over its first second and its lifetime, the inputs the per-ability
rules below read. A track switching objects, which the prototype saw twice,
is a stored surprise when its fixes jump past the reach.

### The glyph verdict

`adjudication.ability_glyph` reads the tracks and decides per track,
pure over stored rows:

1. **Gates, from other owners' stored answers.** A frame counts when the
   widget is drawn [owns:widget-drawn], no stored `team_vision` portrait
   covers the disc (the prototype's `portrait_cover`) and the disc is not
   the baked map's [domain:capture/session-pixels-are-not-the-map]. The
   frame's view is `self` while the tray shows the player's kit and
   `spectator` while it shows a teammate's [owns:tray-kit]
   [domain:hud/tray-after-player-death]; textures whose view is false for
   that view leave the set. A null view stays in with `view_unknown`, and
   a verdict resting on one is a stored surprise until the player answers
   [domain:minimap/spectator-view-matches-self].
2. **Pooling.** The mean score per key over the clean frames.
3. **The cut, once.** A key names the track when its pooled score clears
   its own null and its margin over the runner-up clears the tie margin;
   both come from the null table (gate 3), never a shared constant.
   Otherwise the track refuses with one reason: `below_null`,
   `pairwise_tie`, `no_clean_frame`, `occluded`, `outside_candidate_set`
   (the audit or surprise path named a kit outside the set),
   `view_excluded`, `pending` (below).
4. **Per-ability rules, from facts.** Each rule is the named ability's own,
   cites its fact, and runs only on tracks whose candidates include it:
   - Astra: a disc that scores best as a placed star names the track
     `Astra:star`, state `pending`, never E, Q or C
     [domain:abilities/astra-star-placed-then-turned]. Which slot it
     becomes is a later event read at the turn: a smoke disc at the same
     place is `minimap-dark`'s, the others need their own drawing facts,
     which the mechanics sheet asks. The glyph never names the turn.
   - Omen: between Paranoia and Dark Cover, a track that moves 40 px or
     more within its first second and ends by 2 s is Paranoia
     [domain:abilities/omen-paranoia-minimap-icon]; a track that stays
     within the follow's reach and outlives 2 s is Dark Cover
     [domain:abilities/omen-dark-cover-minimap-phases]. A track that fits
     neither refuses `pairwise_tie` with both pooled scores stored. The
     40 px and 2 s cuts come from the facts; their tolerances are design
     choices, measured on dev before use. The 40 px is a pixel distance on
     demo captures at a widget scale the fact does not state; the rule
     applies it as base value x widget scale x map zoom, and runs only
     after the fact records the scale it was read at (or a dev
     measurement replaces it).
   No rule carries to another ability by analogy
   [domain:abilities/ability-rules-are-unique].
5. **State.** The winning texture's game-data state (inactive, active,
   ally, enemy and the rest) is an observation of that ability's drawing.
   A lifecycle phase comes only from the ability's lifecycle fact
   [domain:minimap/device-dim-on-deactivation]; the entity contract
   enforces it.

Output `ability_glyph_name`: per track, the ability (agent, game slot,
display name) or `pending`, the texture and its state, the pooled scores of
every candidate (the alternatives), margin, the rule that decided it, clean
and skipped frames with reasons, and `rests_on` the lineup, `team_vision`,
`tray_kit` and policy-table stamps.

**The claim.** Per track whose winning kit is clear, one
`identity.identity_claim` on channel `minimap_glyph`: the entity is the
track, the agent is the kit's owner. The caster's kit may be clear when the
slot is not (a `pairwise_tie` inside one kit, an Astra `pending` star); the
claim then names the agent and the track stays refused on its slot. When
the lineup chose the candidates, the claim `depends_on` the ally slot
entities, as `smoke_owner`'s claims do, so it never counts as an
independent witness of the roster. An audit-path claim, scored against
every kit, rests on no lineup and may witness which agents a side fields;
it enters the aggregator only after the null holds on the audit rows.
Until channel arbiters exist (`docs/ARBITER_ARCHITECTURE.md`, section 1),
the owner publishes its claims as `smoke_owner` does
(`ability_glyph_identity`); afterwards, through the minimap channel's
arbiter.

### The event and its consumers

A new lane `ability_icon` in `docs/ENTITY_EVENTS.md`: an `ability_object`
entity per track, its `identity` the aggregator's verdict cited by `ref`,
events `drawn` (first fix) and `gone` (the verify's loss) with observed
times and baked positions, one event per texture state change, and for an
Astra star a `turned` event when its slot is read. A refused track goes to
the ledger with its reason and `returns_to: ["ability-glyph-name"]`.
Consumers read only this lane [owns:entity-event]:

- `reticle view`, which draws named ability icons on the annotated match;
- `ability-owner`, unowned today and blocked on "an ability entity to
  attribute": the track is that entity, and the aggregator's verdict over
  the glyph claim, the birth at a bound ally fragment
  [domain:abilities/minimap-thrown-ability-icon] and the player's tray drop
  answers it;
- `adjudication.ability_state`'s later steps (allies' kits) and
  `adjudication.phases`, which read texture states as transitions;
- `adjudication.reliability` [owns:identity-channel-reliability], which
  scores the channel per agent.

## 3. Ownership entries

Proposed text; each lands in `ownership.toml` with the code that owns it.

- **`ability-glyph`**, owner `minimap_glyph`, role detect, "Which game
  minimap texture of the candidate kits does each proposed ability disc
  draw, and how well does each candidate score?" Produces the reader and
  its scoring. `not_for`: finding discs (`ability-icon`); joining discs
  across frames (`ability-disc-track`); naming the ability or its caster
  (`ability-glyph-name`, `agent-identity`); smokes (`minimap-dark`) and
  shapes (`ability-shape`); choosing the candidate set beyond the
  lineup's verdicts, which it takes as a candidate set only.
- **`ability-disc-track`**, owner `adjudication.ability`, role group,
  "Which stored ability-disc observations are one object, from birth to
  loss?" `not_for`: reading pixels (the follow's fixes are the reader's);
  naming; lifecycle phases (`ability-phase`).
- **`ability-glyph-name`**, owner `adjudication.ability_glyph`, roles
  adjudicate and attribute, `names_agents = true`, `defers_to =
  ["agent-identity", "player-agent", "tray-kit", "team-vision",
  "ability-disc-track"]`, "Which ability does a tracked minimap disc
  draw, in which texture state, and whose kit holds it?" `not_for`:
  deciding the caster's name, which the aggregator decides from the claim;
  binding the ability to a player track (`ability-owner`); a phase without
  a lifecycle fact; the slot an Astra star turns into; a threshold the null
  table does not give.
- **`ability-owner`** stays the aggregator's question; this plan supplies
  its entity and its first witness, and its `blocked_by` changes to the
  stage 5 lane.

## 4. Plan inputs

In `reticle/plan.py`, beside the ability pass's streams:

- `ability_glyph`: command `reticle scan {sid} --only ability`, how
  `cache`; fields `ability_glyph_version`, the glyph bank digest (the
  rotation policy table's version inside it), `ability_icon_version`;
  upstream `ability_icon`; inputs the geometry and `_lineup_inputs()`.
- `ability_disc_track`: command `reticle ability-glyphs {sid}`, how
  `storage`; upstream `ability_icon`, `ability_glyph`, `rounds`.
- `ability_glyph_name`: same command, storage; fields the null table's
  version and the states table's version; upstream `ability_disc_track`,
  `team_vision`, `tray_kit`; inputs `_lineup_inputs()`.
- `ability_glyph_identity`: an identity stream, `producer_version` the
  aggregator's, parent `ability_glyph_name`.

The lineup appears twice on purpose: a lineup change restamps the reader,
whose candidate set it chose, and the verdict, whose claims depend on it.

## 5. Evaluation gates

Each gate states its command, its labels and its threshold before it runs.
Every threshold below is a design choice made here, not a measured
optimum; a gate that fails reopens its threshold only with a logged reason.

1. **Instrument.** `prototypes\glyph_channel_cost.py rotation` reproduced
   the prototype's [metric:glyph_channel_cost/rotation#heldout_rotate_all=164]
   of [metric:glyph_channel_cost/rotation#heldout_n=192] and
   [metric:glyph_channel_cost/rotation#dev_rotate_all=51] of
   [metric:glyph_channel_cost/rotation#dev_n=59]; `rotrule`'s upright
   control reproduced [metric:glyph_channel_cost/rotation_rule#dev_upright=35]
   of them. On stage 1's own windows (eval 0.3.0 dev), `baseline030` read
   rotate-all at [metric:glyph_channel_cost/dev_030#dev_rotate_all=55] and
   upright at [metric:glyph_channel_cost/dev_030#dev_upright=35] of
   [metric:glyph_channel_cost/dev_030#dev_n=59]. Done.
2. **The clean held-out pass.** Done:
   [metric:glyph_channel_cost/heldout_020#headline_follow_right=102] of
   [metric:glyph_channel_cost/heldout_020#headline_n=139] (section 1)
   against a stop line of 35% (a design choice); stage 1 may start.
3. **The null table.** Per bank (context set and full set, at each widget
   scale) and per key at its policy's search size, the pooled-score and
   margin distributions of discs the player labelled as no ability, and of
   proposer discs no label names, from dev sessions only. The cut sits
   where the false naming rate on those discs is at most 5% (a design
   choice). Stored as its own version; the verdict records it.
4. **Accuracy at the cut, on a fresh held-out set.** A new labelling pass
   (`prototypes/label_minimap_glyph_heldout.py`, a new queue version) on
   sessions no stage used, glyph marks and shape marks asked apart. Named
   tracks must be right on the caster agent on at least 90% (Wilson lower
   bound at least 80%), naming at least half the sure kit-named glyph
   marks (design choices). Refusals are kept with reasons.
5. **Riot.** Riot records each player's casts per slot per match (`stats.
   abilityCasts`; per-round effects are null). For each ally player and
   slot whose ability draws a disc, named births may not exceed Riot's
   count times that ability's births per cast; an ability with no births
   fact gets no bound and asks the player through the mechanics sheet.
   Excess lists the tracks with their reasons. Run with
   `prototypes\riot_ground_truth.py --all --offline --record` once a
   block reads the lane.
6. **Cross-reference.** The glyph claim against the birth's origin at an
   ally fragment and against the player's tray drop; disagreements are
   stored, never averaged, and the agreement rate joins the reliability
   table. Agreement is consistency, not accuracy.

   **Per-ability origin rules (for gate 6's next revision).** The nearest
   ally at a birth is no origin rule: each ability has its own
   [domain:abilities/ability-rules-are-unique]. Stage 3's first gate 6 run
   disagreed most on Chamber and Cypher devices and Astra stars born near a
   different ally, and the player answered on 2026-10-05 with these rules,
   which the next revision applies per ability and no other:

   - Astra's stars carry no origin at Astra
     [domain:abilities/astra-stars-origin-global]; gate 6 skips the
     proximity check for them.
   - Chamber's Trademark and Rendezvous
     [domain:abilities/chamber-trademark-origin-placed-away],
     [domain:abilities/chamber-rendezvous-origin-placed-away] and Cypher's
     Trapwire and Spycam [domain:abilities/cypher-trapwire-origin-placed-away],
     [domain:abilities/cypher-spycam-origin-placed-away] may be born up to
     their game-file targeting range from the caster. Cyber Cage
     [domain:abilities/cypher-cyber-cage-origin-placed-away] has no range in
     the files; its birth stays unbounded until one is measured.
   - Reyna's Leer [domain:abilities/reyna-leer-origin-set-distance] is born
     at most its game-file trigger distance from Reyna, nearer when cast
     steeply.
   - Sova's Owl Drone [domain:abilities/sova-owl-drone-origin-at-caster] and
     Tejo's Stealth Drone [domain:abilities/tejo-stealth-drone-origin-at-caster]
     are born at the caster's icon.
   - Every other ability has no origin rule yet; gate 6 stores its
     disagreement as unexplained, never as an error. Skye's drone is
     unnamed. Trailblazer is piloted like the Owl Drone
     [domain:abilities/skye-trailblazer-piloted] and Guiding Light is
     steered [domain:abilities/skye-guiding-light-steered]; whether the
     player meant one, both or neither is asked.

   Each distance is a game-data fact in metres. It becomes widget pixels as
   base value x widget scale x map zoom (`geometry.MapScale.px`), where the
   base value is the metres in base pixels at `geometry.SCALE_REF_KEY` for
   that map; world drawings follow the zoom
   [domain:minimap/world-drawings-follow-map-zoom]. The base pixels per
   metre are not yet a recorded fact: the next revision measures them per
   map from a drawing whose game-file size is known, before it applies any
   bound. Gate 6's code is unchanged until stage 3 merges.
7. **Cost.** `reticle usage <sid>` on the fast handful: the reader adds at
   most 10% to the ability pass's wall time, and the verdict runs under
   one minute per match from storage (design choices).

## 6. Staged order

0. **Done:** cost, prior share, rotation and null measurements (W1-W13);
   the clean held-out score (H1-H8, K5); the rotation answers; the
   two-flag test (G1-G4, with its correction row); the cross-channel
   independence measurement; S1's baseline on the eval 0.3.0 windows.
1. **Rotation policy and null table on dev. Done except gate 3's
   unlabelled discs** (2026-10-05, `prototypes/glyph_tables.py`,
   `glyph-tables-0.1.1`, wire: no; store `analysis/glyph-tables-20261005b`,
   which reproduces the 0.1.0 run in `analysis/glyph-tables-20261005`).
   `build` writes both tables from storage alone: the policy table
   (`glyph-rotation-policy-0.1.1`), one row per catalogue key,
   [metric:glyph_tables/policy#keys=116] keys,
   [metric:glyph_tables/policy#rotates=19] rotated, of which
   [metric:glyph_tables/policy#by_answer=9] rows a player answer decides
   (each citing its `answers.jsonl` line and a new domain fact, such as
   [domain:abilities/cypher-spycam-minimap-glyph-turns]) and
   [metric:glyph_tables/policy#unsure=2] are unsure keys (Cypher:C, Skye:X)
   rotated with the reason `unsure_pending_player`. The two-flag rule
   decides [metric:glyph_tables/policy#by_rule=35] rows; no answer
   contradicts it. No minimap component draws the other
   [metric:glyph_tables/policy#no_component_default=70] keys: they are
   upright by default, unverified (`no_component_default`). Deadlock:Q is
   searched at every rotation, since no wall fit is in master. The null
   table (`glyph-null-table-0.1.1`) scores the
   [metric:glyph_tables/build#negatives_n=63] dev discs the player labelled
   no ability against every key at its policy's search size, single frame,
   and stores two cuts: each key's, which lets at most 5% of the discs
   exceed it, and each bank's (gate 3), which lets at most 5% of the discs'
   best keys in the bank exceed it, overall and at each widget scale. Both
   tables carry the build, the answers file's hash and lines, the dev
   sessions (d95cfad5693a, dae6f33f3f48), the held-out sessions they did
   not use (the held-out pass's 31 and the eval's own held-out split's 19),
   and the 15 match sessions S5 used; the builder refuses any item outside
   the dev split or the eval's label sources. The dev sessions are Cypher
   and Killjoy demos, so no borrowed audio label exists there and none
   entered. On the eval 0.3.0 dev windows:
   - S1 held: single frame with the policy table named
     [metric:glyph_tables/build#s1_single_policy=58] of
     [metric:glyph_tables/build#dev_n=59] (rotate-all control
     [metric:glyph_tables/build#control_rotate_all=55], upright
     [metric:glyph_tables/build#control_upright=35], both reproducing the
     stored run), the follow [metric:glyph_tables/follow#policy_cache_right=58]
     (rotate-all control [metric:glyph_tables/follow#rotate_all_cache_right=58]).
   - S2 held: [metric:glyph_tables/build#s2_clear=55] of
     [metric:glyph_tables/build#s2_right=58] right items clear their key's
     cut ([metric:glyph_tables/build#s2_share=0.9483]); pooled over the
     follow, [metric:glyph_tables/follow#pooled_policy_cache_s2_share=0.9828].
   - S3 held: the rotated keys' median cut is
     [metric:glyph_tables/build#s3_median_cut_rotated=0.6678], the upright
     keys' [metric:glyph_tables/build#s3_median_cut_upright=0.5242], and
     [metric:glyph_tables/build#s3_median_cut_upright_with_component=0.5333]
     over the [metric:glyph_tables/build#s3_upright_keys_with_component=27]
     upright keys a component draws; a per-bank null alone would not do.
   - S4 held: the 2 Hz follow named
     [metric:glyph_tables/follow#policy_2hz_right=58], the cache-cadence
     follow 58, [metric:glyph_tables/follow#s4_points=0.0] points apart. The
     placed dev icons do not move; a thrown icon at 2 Hz is untested.
   - S5 failed. Seeded at the thrown icon's birth (a disc absent 0.5 s
     before the drop, 17-34 px x scale from the caster, within 1.5 s), the
     rotate-all follow named [metric:glyph_tables/thrown@matches#rotate_all_right=36]
     right and [metric:glyph_tables/thrown@matches#rotate_all_wrong=29] wrong,
     precision [metric:glyph_tables/thrown@matches#rotate_all_precision=0.5538],
     not above the self seed's
     [metric:glyph_tables/thrown@matches#self_seed_stored_precision=0.5798],
     and refused [metric:glyph_tables/thrown@matches#rotate_all_refused=161]
     of the 226 casts, most for finding no birth. The policy arm reads
     [metric:glyph_tables/thrown@matches#policy_precision=0.5968]. On the
     [metric:glyph_tables/thrown@matches#paired_thrown_named=65] casts the
     thrown seed named, the self seed was right
     [metric:glyph_tables/thrown@matches#paired_self_right=25] times and
     wrong [metric:glyph_tables/thrown@matches#paired_self_wrong=18]; where
     both named, both were wrong on
     [metric:glyph_tables/thrown@matches#paired_both_wrong=15]. Revised
     belief: section 1 named the seed as the cause of the self seed's
     errors; S5 falsified it. The birth rule is an untuned design guess. One
     sample run (`thrown --only 043bafca271a`, 10 casts) came before the S5
     run, with the same birth parameters (BIRTH_MS 1.5 s, BIRTH_R 34,
     REF_MS 500), which both runs stamp. Stage 3 must find the thrown icon's
     track before it can name it, and the label path stays closed until a
     seed beats 0.58. S5 used the 15 match sessions of the cross-channel
     casts (`s5_match_sessions` in both tables' provenance: 043bafca271a,
     223d636bf8d2, 3694746e4e54, 4f207c0c4e39, 59c70f1ef720, 75a55a296d3b,
     96aa1ae9b96f, 9acf02f98283, b3b9defb6fd7, b7d24102a6f6, bdfdcf009dba,
     bfad2778a372, c40d950031bb, c62c2b06bcfb, e37fdeca944f); gate 4's
     fresh set excludes them.
   Gate 3 is met only in its bank form and only on labelled discs. The
   per-key cuts alone do not hold a bank at 5%: they falsely name
   [metric:glyph_tables/build#false_naming_context_cut=0.0794] of the dev
   no-ability discs in the caster's kit and
   [metric:glyph_tables/build#false_naming_full_cut=0.3016] in the full set.
   The dev tie margin brings these to
   [metric:glyph_tables/build#false_naming_context_verdict=0.0159] and
   [metric:glyph_tables/build#false_naming_full_verdict=0.0317], but that
   margin rests on one wrong dev item, so it meets no gate. The bank cuts
   hold by construction: the context cut
   [metric:glyph_tables/build#bank_cut_context_cut=0.652] names
   [metric:glyph_tables/build#bank_cut_context_rate=0.0476] of the discs
   and keeps [metric:glyph_tables/build#bank_cut_context_glyph_items_named_right_cut=55]
   right items above it; the full cut
   [metric:glyph_tables/build#bank_cut_full_cut=0.8043] names
   [metric:glyph_tables/build#bank_cut_full_rate=0.0476]. Pooled over the
   follow, the context bank cut keeps
   [metric:glyph_tables/follow#pooled_policy_cache_bank_cut_context_s2_share=0.8966]
   of the right items at cache cadence and
   [metric:glyph_tables/follow#pooled_policy_2hz_bank_cut_context_s2_share=1.0]
   at 2 Hz. Gate 3 is unmet in two parts. The null holds no unlabelled
   proposer disc. The per-scale cuts rest on 37 and 26 discs, so 5% allows
   one named disc per scale (rate
   [metric:glyph_tables/build#bank_cut_full_per_scale_rate=0.0317] in the
   full bank); they are stored but too coarse to choose between. Stage 2
   chooses which cut the verdict uses. `glyph_channel_cost.py rotrule`
   reproduces the 0.2.0 counts except one key: Miks:C joins (46 keys with a
   component, against 45) because a later extraction gave it a DisplayIcon;
   it reads upright and changes no policy. Outcome rows: store
   `notes/predictions.jsonl`, ts 2026-10-05T09:11:10Z, and the fix round's
   correction and outcome rows after it.
   - **Rebuilt for the 2026-10-05 rotation answers** (branch
     `glyph-answers-20261005`, `glyph-tables-0.2.1`; store
     `analysis/glyph-tables-20261005d`). The player answered that Seekers,
     Cyber Cage and Trapwire turn
     [domain:abilities/skye-seekers-minimap-glyph-turns-belief]
     [domain:abilities/cypher-cyber-cage-minimap-glyph-turns-belief]
     [domain:abilities/cypher-trapwire-minimap-glyph-turns-belief].
     `glyph-rotation-policy-0.1.2` rotates
     [metric:glyph_tables/policy_012#rotates=20] of
     [metric:glyph_tables/policy_012#keys=116] keys; a player answer
     decides [metric:glyph_tables/policy_012#by_answer=12] rows and
     [metric:glyph_tables/policy_012#unsure=0] stay unsure. Skye:X stores
     the table's one surprise
     ([metric:glyph_tables/policy_012#surprises=1]): the two-flag rule
     reads it upright. Only Cyber Cage's search changes: Skye:X and
     Trapwire were already rotated as unsure, and Cypher:Q was upright by
     default. In `glyph-null-table-0.2.1`
     [metric:glyph_tables/build_021#cut_move_keys_moved=1] per-key cut
     moved, Cypher:Q's, from
     [metric:glyph_tables/build_021#cypher_q_cut_before=0.4367] to
     [metric:glyph_tables/build_021#cypher_q_cut=0.5331]; no audit cut
     moved ([metric:glyph_tables/build_021#cut_move_audit_keys_moved=0]),
     and the bank cuts held: context
     [metric:glyph_tables/build_021#bank_cut_context_cut=0.6596], full
     [metric:glyph_tables/build_021#bank_cut_full_cut=0.8219] and audit
     [metric:glyph_tables/build_021#audit_bank_cut=0.8608]. The build
     counted each at its unrounded order statistic,
     [metric:glyph_tables/build_021#bank_cut_context_rate=0.0476] of the
     dev no-ability discs, but stored the cut rounded to nearest; as the
     reader applies the stored cuts, the full and audit banks named
     [metric:glyph_reader/rescore_022@dev#full_bank_named_before=4] and
     [metric:glyph_reader/rescore_022@dev#audit_bank_named_before=4] of
     [metric:glyph_reader/rescore_022@dev#negatives=63], over gate 3's 5%
     (the full bank's fourth-highest score, 0.821934 at d95cfad5693a
     39.90 s, clears its stored 0.8219). Master's 0.2.0 tables share the
     defect. `glyph-tables-0.2.2` fixes it below. The per-key
     cuts alone still name
     [metric:glyph_tables/build_021#false_naming_context_cut=0.0952] in the
     caster's kit. S1 fell from 58 to
     [metric:glyph_tables/build_021#s1_single_policy=57] of
     [metric:glyph_tables/build_021#dev_n=59]: one Trapwire item
     (d95cfad5693a 24.60 s) now reads best as Cypher:Q, under its cut, so
     no named decision changed. The controls reproduce
     [metric:glyph_tables/build_021#control_rotate_all=55] and
     [metric:glyph_tables/build_021#control_upright=35]. On the
     [metric:glyph_reader/answers_021@heldout#n=19] held-out marks whose
     caster's kit holds one of the three keys, the reader's matcher names
     [metric:glyph_reader/answers_021@heldout#s1_before=19] before and
     [metric:glyph_reader/answers_021@heldout#s1=19] after, no best key
     changed. Outcome rows: `glyph-answers-20261005` in
     `notes/predictions.jsonl`.
   - **Cuts stored as counted** (`glyph-tables-0.2.2`, same branch; store
     `analysis/glyph-tables-20261005e`, `analysis/glyph-bank-20261005e`).
     `cut_at` returns the cut rounded up to 4 decimals, and every count is
     taken at that stored value. Each cut equals 0.2.1's or rises by
     0.0001; the policy rows and glyphs do not change. The bank cuts are
     context [metric:glyph_tables/build_022#bank_cut_context_cut=0.6596],
     full [metric:glyph_tables/build_022#bank_cut_full_cut=0.822] and audit
     [metric:glyph_tables/build_022#audit_bank_cut=0.8609]; the reader's
     matcher, rescoring the dev discs against them, names
     [metric:glyph_reader/rescore_022@dev#context_bank_named=2],
     [metric:glyph_reader/rescore_022@dev#full_bank_named=3] and
     [metric:glyph_reader/rescore_022@dev#audit_bank_named=3] of 63, the
     stored counts (full rate
     [metric:glyph_tables/build_022#bank_cut_full_rate=0.0476]): gate 3's
     bank form holds as applied. The per-key cuts alone name
     [metric:glyph_tables/build_022#false_naming_context_cut=0.0794] in the
     caster's kit and
     [metric:glyph_tables/build_022#false_naming_full_cut=0.2063] in the
     full set. S1 stays [metric:glyph_reader/rescore_022@dev#s1=57] of 59
     and right items above their cut stay
     [metric:glyph_reader/rescore_022@dev#right_above_cut=55]. Cypher:Q's
     cut is [metric:glyph_tables/build_022#cypher_q_cut=0.5332]. In the
     audit sample (the earlier draw, 200 context rows per session, decided
     from the stored scores), [metric:glyph_reader/audit_022@all#context_cut_agree=600]
     of 600 cut decisions agree (Wilson 95% lower bound
     [metric:glyph_reader/audit_022@all#wilson95_lower=0.9936]; at most
     0.5% disagreement by the rule of three), and no row of the three
     trials' full context pools flips
     ([metric:glyph_reader/audit_022@all#pool_flips=0]).
2. **The reader** in the ability pass; `reticle trial --reader
   ability_glyph` on a06f04a0059f, 5822b6646448
   (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) and 4f207c0c4e39
   (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`); gate 7. **Built,
   `ability-glyph-0.2.0`, gate 7 met** (2026-10-05, `reticle/minimap_glyph.py`
   [owns:ability-glyph]). It reads three versioned store files, never
   `prototypes/`: the reference bank `glyph-bank-0.2.0` (store
   `analysis/glyph-bank-20261005b`, written by `glyph_tables.py bank` from
   the references the stage 1 tables were built on, paired to them by
   sha256, each source with its game file and sha256; the glyphs equal
   0.1.0's), the policy and the null table. It scores the lineup's kits
   (`lineup.glyph_candidates`) under the policy on every ungated disc, the
   first birth and every tenth after it against every kit at every rotation
   (`audit`), and a window whose best context key never clears its per-key
   cut against every kit when it closes (`surprise`). It runs the 2 Hz arm
   only (S4); the cache-cadence follow is not built. `plan` names
   `ability_glyph` stale where `ability_icon` is stored without it
   (`plan.PASS_ADDED`). Outcome rows: store `notes/predictions.jsonl`,
   `glyph-reader-20261005` (0.1.0) and `glyph-reader-fix-20261005` (0.2.0,
   with the correction row that withdraws 0.1.0's revised beliefs).
   - **Revisions after review (0.2.0).** The 0.1.0 reader scored every
     proposer disc without stage 1's gates; on 4f207c0c4e39 most rows sat
     on static map structure. Each disc row now stores `static_corr` against
     the baked static and its nearest stored `ally_icon` portrait, and a
     disc that is the map's (`static_like`, stage 1's MAP_CORR 0.7) or lies
     inside a portrait (`on_ally_icon`) is neither scored nor scheduled.
     Continuation is the proposer's verify
     (`ability_icons.verified_continuations`), not a reach of the reader's
     own. Context and frame rows rest on the lineup stamp. Audit rows store
     no cut (`no_null_at_full_rotation`). The per-view gate (enemy kits only
     their enemy-visible textures) is deferred: both sides' full kits are
     scored, which widens the surprise and audit comparisons (R3, R4) and the
     cost, all measured with it.
   - The matcher reproduces stage 1 exactly: against the origin/master
     prototype with its own normalisation, the largest per-key difference
     on the 122 dev windows is [metric:glyph_reader/r1_020#max_abs_diff_cpu=0.0]
     and S1 is [metric:glyph_reader/r1_020#s1_reader=58] of 59; on 200
     scored rows per trial session it matches `frame_scores` within
     [metric:glyph_reader/trial_020@4f207c0c4e39#r2_max_abs_diff=5.01e-05]
     (the stored rounding), the best key on every row.
   - The gates on 4f207c0c4e39: of the 0.1.0 trial's 12 most frequent
     positions, a share
     [metric:glyph_reader/trial_020@4f207c0c4e39#f1_gated_share=0.942] of
     the rows are now gated, and the above-cut share there fell from
     [metric:glyph_reader/trial_020@4f207c0c4e39#f1_old_above_share=0.6556]
     to [metric:glyph_reader/trial_020@4f207c0c4e39#f1_above_share=0.0521].
     Nearly all that remains sits at the widget's left edge, half over the
     void, where the static correlation reads 0.64; the stage 1 rule does
     not reach it, and a slab-only correlation did not either (probed, not
     adopted). On the other two sessions the frequent positions are the
     player's placed Deadlock:Q sensors, real glyphs the gate rightly keeps.
     Births fell from 2798 to
     [metric:glyph_reader/trial_020@4f207c0c4e39#births=933].
   - Gate 7, as worded: in `reticle usage c40d950031bb` after one `scan
     --only ability --from cache` (331 px; shape, icon and glyph readers
     fed live) the glyph reader took a share
     [metric:glyph_reader/scan_020@c40d950031bb#glyph_share_of_pass=0.0537]
     of the pass ([metric:glyph_reader/scan_020@c40d950031bb#glyph_share_without_templates=0.0301]
     without the one-time template build). In the trial on 4f207c0c4e39,
     against the icon reader and the cache read alone, the ratio is
     [metric:glyph_reader/trial_020@4f207c0c4e39#ratio=0.0635], from 0.1178
     at 0.1.0. A trial reading the stored proposer rows (`StoredIcons`)
     reproduced all [metric:glyph_reader/scan_020@c40d950031bb#stored_path_identical=3709]
     rows the scan wrote live.
   - The scale is a measured exception, held by parity, not insensitivity.
     Rescored at the full transform (widget x zoom), the best key agrees on
     only [metric:glyph_reader/trial_020@4f207c0c4e39#f4_best_agree_share=0.805]
     of 200 rows at zoom 0.892 and the cut decision on
     [metric:glyph_reader/trial_020@4f207c0c4e39#f4_cut_agree_share=0.885];
     at zoom 1.0 both agree on every row. The null cuts hold only at the
     basis they were measured on, the widget scale at dev zooms 0.887 and
     1.0, which the trial sessions match. A session at another zoom needs a
     null at its basis, or the tables rebuilt at the full transform.
   - The surprise path takes
     [metric:glyph_reader/trial_020@4f207c0c4e39#r3_share=0.3494],
     [metric:glyph_reader/trial_020@a06f04a0059f#r3_share=0.5382] and
     [metric:glyph_reader/trial_020@5822b6646448#r3_share=0.3197] of the
     windows: the per-key cut alone still clears most windows after the
     gates, as gate 3's bank rates warned. The audit's full rotated bank
     puts its best key inside the lineup's kits on
     [metric:glyph_reader/trial_020@4f207c0c4e39#r4_best_in_context=30] of
     [metric:glyph_reader/trial_020@4f207c0c4e39#r4_cleared_audit_windows=65]
     cleared windows there: a bank searched at every rotation wins on noise.
     Audit rows need their own null before stage 3 compares them with
     context verdicts (P5).
   - **Revisions after the second review (0.3.0).** The portrait gate is
     stage 1's `portrait_cover` itself, moved into `reticle/minimap_glyph.py`;
     the prototype's follow calls it and reproduces stage 1 exactly (dev
     58/59, every skip and score). The reader applies it to the stored
     `ally_icon` fits and self icon: the stored `team_vision` puts the self
     icon about 15 px off on the variant session. An ally fit within SAME_R
     no longer gates its disc; the ring to OCC_R does. That regained
     [metric:glyph_reader/trial_030@5822b6646448#regained=62] rows on
     5822b6646448, Gekko discs with a white glyph and a teal rim, but also
     [metric:glyph_reader/trial_030@4f207c0c4e39#regained=14] on
     4f207c0c4e39 that are ally portraits the proposer proposed; the ring
     gates [metric:glyph_reader/trial_030@4f207c0c4e39#newly_portrait_gated=171]
     rows there that 0.2.0 scored. Births on 4f207c0c4e39 went from
     [metric:glyph_reader/trial_030@4f207c0c4e39#births_before=933] to
     [metric:glyph_reader/trial_030@4f207c0c4e39#births=844]. R1 and R2
     hold: [metric:glyph_reader/r1_030#max_abs_diff_cpu=0.0] on the dev
     windows, [metric:glyph_reader/trial_030@4f207c0c4e39#r2_max_abs_diff=5.0e-05]
     on 200 trial rows. The glyph feed over the icon feed and the cache read
     is [metric:glyph_reader/trial_030@4f207c0c4e39#ratio=0.062] on
     4f207c0c4e39.
   - **The void-corner disc stays scored.** The disc at (21, 91) on
     4f207c0c4e39 is the void beside the radar ring at the variant
     widget's corner. The baked static is placed right there; the void half
     shows the world behind the widget, so no baked value predicts it, and
     the static correlation over the map-art footprint alone is still
     [metric:glyph_reader/trial_030@4f207c0c4e39#edge_onfootprint_corr_median=0.665].
     The disc lies [metric:glyph_reader/trial_030@4f207c0c4e39#edge_footprint_share=0.195]
     on the footprint, but real glyphs drawn over the void do too:
     [metric:glyph_reader/trial_030@4f207c0c4e39#heldout_marks_below_half_footprint=9]
     of [metric:glyph_reader/trial_030@4f207c0c4e39#heldout_marks=226]
     labelled held-out marks sit under half on it. A footprint gate, not
     built, would have removed
     [metric:glyph_reader/trial_030@4f207c0c4e39#fpgate_births=374] of 933
     births there and real glyph rows on 5822b6646448. Stage 3 answers it.
3. **Tracks, verdict, per-ability rules and claims** from storage; gates 4
   and 6. The ability pass first runs on the 21 matches in one batched
   corpus rerun; today `ability_icon` exists on five sessions only.
   Prerequisites, from stage 2's review (2026-10-05, branch
   `glyph-prereqs-20261005`: `glyph-tables-0.2.0`, `glyph-null-table-0.2.0`
   and `glyph-bank-0.3.0` in the store's `analysis/glyph-tables-20261005c`
   and `analysis/glyph-bank-20261005c`, `ability-glyph-0.5.0`; prediction,
   amendment, correction and outcome rows `glyph-prereqs-20261005` and
   `glyph-prereqs-fix-20261005` in `notes/predictions.jsonl`; the reader
   now reads `glyph-bank-0.3.2`, `glyph-rotation-policy-0.1.2` and
   `glyph-null-table-0.2.2` from `analysis/glyph-bank-20261005e` and
   `analysis/glyph-tables-20261005e`, stage 1's rebuild for the 2026-10-05
   rotation answers with cuts stored as counted, with the glyphs unchanged and `ability-glyph-0.5.0`
   unchanged, since its matcher, gates, windows and fields did not move;
   `plan` sees the new `GLYPH_BANK_STAMP`):
   - **The rebuilt tables in the trials.** 200 scored context rows per
     session (the stage 2 F4 draw, rng 20261005, rescored from the stored
     0.5.0 trials; master's tables reproduce every stored row) keep their
     best key and cut decision on all 200 on 4f207c0c4e39, a06f04a0059f
     and 5822b6646448 (Wilson 95% lower bound
     [metric:glyph_reader/audit_021@4f207c0c4e39#context_best_agree_lo95=0.9812];
     at most 1.5% disagreement by the rule of three): no lineup there
     holds Cypher. The surprise rows search every key, and there rotated
     Cyber Cage templates win on noise: of 200 surprise rows the best key
     agrees on [metric:glyph_reader/audit_021@4f207c0c4e39#surprise_best_agree=181]
     (95% interval [metric:glyph_reader/audit_021@4f207c0c4e39#surprise_best_agree_lo95=0.8564]
     to [metric:glyph_reader/audit_021@4f207c0c4e39#surprise_best_agree_hi95=0.9383]),
     [metric:glyph_reader/audit_021@a06f04a0059f#surprise_best_agree=186]
     and [metric:glyph_reader/audit_021@5822b6646448#surprise_best_agree=193],
     every change a new Cypher:Q best, and the per-key cut decision on
     [metric:glyph_reader/audit_021@4f207c0c4e39#surprise_cut_agree=188],
     [metric:glyph_reader/audit_021@a06f04a0059f#surprise_cut_agree=189]
     and [metric:glyph_reader/audit_021@5822b6646448#surprise_cut_agree=198].
     The full bank cut's decision agrees on every row
     ([metric:glyph_reader/audit_021@4f207c0c4e39#surprise_bank_agree=200]
     on each session). The prediction of 97% agreement failed; a surprise
     verdict must read the bank cut, never the per-key cut alone.
   - **A null at the full transform. Met.** The null table scores every
     dev disc at `geometry.MapScale.scale` (widget x map zoom; the table's
     `basis` map_scale) and the reader reads the same scale, so no session
     needs a null at its own zoom. S1 names
     [metric:glyph_tables/build_020#s1_single_policy=58] of
     [metric:glyph_tables/build_020#dev_n=59] at the full transform (the
     widget basis still reproduces stage 1's
     [metric:glyph_tables/build_020#s1_single_policy_widget=58]); the median
     key's cut moved [metric:glyph_tables/build_020#cut_move_median_abs=0.0152].
     R1: the reader's matcher (unchanged since 0.4.0) equals the
     prototype's at that scale
     ([metric:glyph_reader/r1_040#max_abs_diff_cpu=0.0] on the dev windows,
     S1 [metric:glyph_reader/r1_040#s1_reader=58]); R2: on 200 trial rows per
     session within
     [metric:glyph_reader/trial_050@4f207c0c4e39#r2_max_abs_diff=5.0e-05],
     the best key on every row. F4 again, the 0.5.0 rows against 0.3.0's on
     the same discs: at zoom 0.892 (4f207c0c4e39) the best key agrees on
     [metric:glyph_reader/trial_050@4f207c0c4e39#f4_best_agree_share=0.6915]
     and the cut decision on
     [metric:glyph_reader/trial_050@4f207c0c4e39#f4_cut_agree_share=0.883];
     at zoom 1.0 the best key on every row and the cut decision on
     [metric:glyph_reader/trial_050@a06f04a0059f#f4_cut_agree_share=0.995]
     (a06f04a0059f) and
     [metric:glyph_reader/trial_050@5822b6646448#f4_cut_agree_share=0.995]
     (5822b6646448). The prediction put 4f207c0c4e39's agreement at 75-90%
     from stage 2's F4; it failed low, and the cause is the sample: stage
     2's 200 rows held
     [metric:glyph_reader/f4_sample@4f207c0c4e39#corner_rows=48] corner rows
     that all agree, and its
     [metric:glyph_reader/f4_sample@4f207c0c4e39#off_corner_rows=152] other
     rows agree on
     [metric:glyph_reader/f4_sample@4f207c0c4e39#off_corner_best_agree_share=0.7434];
     the gated corner never enters the new sample.
   - **Gate 3's unlabelled discs. Not met.** The null takes a proposer disc
     no label names only from a frame the player painted exhaustively
     (`labels/ability_paint`: the latest row per time is `exhaustive` and
     sure), where no other icon is drawn, and only where the reader's own
     gate decision (`minimap_glyph.disc_gates`) keeps it.
     The [metric:glyph_tables/build_020#unlabelled_frames=12] such frames of
     d95cfad5693a hold
     [metric:glyph_tables/build_020#unlabelled_discs=46] proposer discs:
     [metric:glyph_tables/build_020#unlabelled_near_label=38] lie at a
     painted icon or labelled item and the other
     [metric:glyph_tables/build_020#unlabelled_static_like=8] are static
     structure the reader gates, so
     [metric:glyph_tables/build_020#unlabelled_negatives_n=0] enter.
     dae6f33f3f48 has no exhaustive frame, and nothing else vouches that an
     unlabelled disc there is no ability. More exhaustive dev frames are
     the way to meet it.
   - **An audit null. Met.** Every key at every rotation on the same dev
     discs: each key's `audit_cut` (median
     [metric:glyph_tables/build_020#audit_median_key_cut=0.6675] against
     [metric:glyph_tables/build_020#policy_median_key_cut=0.5553] at the
     policy) and the audit bank cut
     [metric:glyph_tables/build_020#audit_bank_cut=0.8608] (rate
     [metric:glyph_tables/build_020#audit_bank_rate=0.0476], counted at
     the unrounded cut; the reader named
     [metric:glyph_reader/rescore_022@dev#audit_bank_named_before=4] of 63
     at the stored 0.8608, fixed in `glyph-tables-0.2.2`). Audit rows now
     store both (`best_cut`, `bank_cut`). In the trials, every audit window
     whose best key clears the audit bank cut has that key inside the
     lineup's kits ([metric:glyph_reader/trial_050@4f207c0c4e39#c2_best_in_context=8]
     of [metric:glyph_reader/trial_050@4f207c0c4e39#c2_cleared=8],
     [metric:glyph_reader/trial_050@a06f04a0059f#c2_best_in_context=15] of
     [metric:glyph_reader/trial_050@a06f04a0059f#c2_cleared=15],
     [metric:glyph_reader/trial_050@5822b6646448#c2_best_in_context=22] of
     [metric:glyph_reader/trial_050@5822b6646448#c2_cleared=22]).
   - **The void-corner disc. Met, with a stated cost.** The `map_shown`
     gate (`reticle/minimap_glyph.py`, MAP_SHOWN): a drawn icon is an
     opaque dark disc that hides the map art under it, so over the disc's
     body on the footprint the crop's 10th-percentile luma over the baked
     static's reads far under 1 on an icon and near 1 on static structure.
     What was blind and what was not: the cut 0.73 and the percentile were
     chosen on dev only, at the midpoint of the
     [metric:glyph_tables/map_shown_dev#n_glyph=59] dev glyph items'
     maximum ([metric:glyph_tables/map_shown_dev#glyph_q10_min=0.1406] to
     [metric:glyph_tables/map_shown_dev#glyph_q10_max=0.4872]) and the
     [metric:glyph_tables/map_shown_dev#n_static=8] static dev discs'
     minimum ([metric:glyph_tables/map_shown_dev#static_q10_min=0.9744] to
     [metric:glyph_tables/map_shown_dev#static_q10_max=1.0598]). The rule
     family (judge the footprint part, never gate on footprint share) and
     the footprint floor MAP_SHOWN_MIN_FP 0.1 were chosen knowing the
     corner's footprint share (about 0.2) and that 9 of 226 held-out marks
     sit under half on the footprint; dev alone does not choose the floor
     (dev glyph items lie
     [metric:glyph_tables/map_shown_dev#glyph_fp_share_min=0.899] or more on
     the footprint, the static discs
     [metric:glyph_tables/map_shown_dev#static_fp_share_min=0.427] to
     [metric:glyph_tables/map_shown_dev#static_fp_share_max=0.483]).
     At 0.4.0 the score read the matcher disc alone, which excludes an
     icon's dark rim: where the footprint part fell on the white glyph it
     read bright, and the gate refused
     [metric:glyph_reader/strong_040@4f207c0c4e39#map_shown_gated=4] of
     [metric:glyph_reader/strong_040@4f207c0c4e39#strong_rows=226]
     off-corner rows 0.3.0 scored at 0.85 or more on 4f207c0c4e39, four
     opaque icons with a white ring glyph, and
     [metric:glyph_reader/strong_040@5822b6646448#map_shown_gated=4] of
     [metric:glyph_reader/strong_040@5822b6646448#strong_rows=2881] on
     5822b6646448 (a translucent grey disc). 0.5.0 reads the body, the
     matcher disc united with the proposer's disc of radius r, so the rim
     enters; on dev the cut stays at the midpoint (glyph items
     [metric:glyph_tables/map_shown_dev#glyph_body_max=0.4872] at most,
     static discs [metric:glyph_tables/map_shown_dev#static_body_min=0.9744]
     at least), frozen before any 0.5.0 trial row was read; the family
     itself was informed by the four 4f207c0c4e39 rows. On 4f207c0c4e39 it
     removes all
     [metric:glyph_reader/trial_050@4f207c0c4e39#corner_scored_before=574]
     scored corner rows (now
     [metric:glyph_reader/trial_050@4f207c0c4e39#corner_scored=0]) and their
     [metric:glyph_reader/trial_050@4f207c0c4e39#corner_births_before=237]
     births, and scores all
     [metric:glyph_reader/trial_050@4f207c0c4e39#four_scored=4] icons the
     0.4.0 score refused; births fell from
     [metric:glyph_reader/trial_050@4f207c0c4e39#births_before=844] to
     [metric:glyph_reader/trial_050@4f207c0c4e39#births=507]. One tile per
     gated position cluster, viewed: every one is map structure (wall
     notches, building corners, the void corner). Strong rows refused:
     [metric:glyph_reader/trial_050@4f207c0c4e39#strong_map_shown=0],
     [metric:glyph_reader/trial_050@5822b6646448#strong_map_shown=0] and
     [metric:glyph_reader/trial_050@a06f04a0059f#strong_map_shown=0]. The
     cost that remains: on 5822b6646448 it gates
     [metric:glyph_reader/trial_050@5822b6646448#map_shown_rows=1] row, a
     dark disc with a white glyph whose proposer disc sits on the glyph off
     the icon's centre, so the body misses most of the rim; a translucent
     icon still breaks the premise in principle. The margin under the cut
     on scored rows: on 4f207c0c4e39 the median
     [metric:glyph_reader/trial_050@4f207c0c4e39#scored_map_shown_q50=0.4872],
     the 99th percentile
     [metric:glyph_reader/trial_050@4f207c0c4e39#scored_map_shown_q99=0.547],
     the maximum
     [metric:glyph_reader/trial_050@4f207c0c4e39#scored_map_shown_max=0.6579],
     and [metric:glyph_reader/trial_050@4f207c0c4e39#scored_map_shown_060_cut=6]
     rows between 0.6 and the cut; the maximum on 5822b6646448
     [metric:glyph_reader/trial_050@5822b6646448#scored_map_shown_max=0.5812]
     and on a06f04a0059f
     [metric:glyph_reader/trial_050@a06f04a0059f#scored_map_shown_max=0.5556].
     The scored maximum sits closer to the cut than the dev glyph maximum.
     The held-out falsifier, read after the freeze: at the mark position
     [metric:glyph_reader/heldout_050@heldout#map_shown_gated=40] of
     [metric:glyph_reader/heldout_050@heldout#marks=226] marks read at or
     above the cut, none with a proposer disc within 8 px x scale (smokes,
     walls, other shapes the reader never scores); of the
     [metric:glyph_reader/heldout_050@heldout#snapped=161] marks a disc
     snaps to, [metric:glyph_reader/heldout_050@heldout#snapped_gated=0]
     are gated. Stage 3 reads `map_shown` beside the verdict and must keep
     a dimmed device's track from being dropped by it; the dimmed state
     needs its own fact first [domain:minimap/device-dim-on-deactivation].
   - Gate 7 holds within its bound of 0.10, and the ratio varies between
     runs: the glyph feed over the icon feed and the cache read on
     4f207c0c4e39 is
     [metric:glyph_reader/trial_050@4f207c0c4e39#ratio=0.0805] at 0.5.0,
     and two runs of 0.4.0 read
     [metric:glyph_reader/trial_040@4f207c0c4e39#ratio=0.0701] and
     [metric:glyph_reader/gate7_repeat_040@4f207c0c4e39#ratio=0.08]
     (0.3.0 [metric:glyph_reader/trial_040@4f207c0c4e39#ratio_before=0.0619]).
4. **The lane and `reticle view`**; gate 5.
5. **The scene model.** The glyph textures become an ability sprite in
   `docs/SCENE_MODEL.md`'s renderer, composited over the baked static at
   the fitted pose; the per-key null becomes the sprite's residual
   threshold, and the reader's scores the render-and-compare residual.

## 7. Real time

Live, nothing decodes: the reader is a function of one minimap crop and
the previous frame's fixes. Its glyph scoring fits a live budget on the GPU
([metric:glyph_channel_cost/cost@a06f04a0059f#bank_a_gpu_ms=0.75] ms per
frame median). The proposer does not
([metric:glyph_channel_cost/cost@a06f04a0059f#propose_ms=148.2] ms at
465 px). A live proposer would continue the prior: verify the tracked
discs every frame, propose births only near the ally icons where an
ability's fact places its birth, and run the full search on surprise and
at a fixed audit cadence. That change belongs to `ability-icon` and needs
a birth-place fact per ability; it is out of this plan's scope.

## 8. Predictions for the later stages

Logged in the store when each stage starts, with these as the first
draft:

- P3 (stage 2): the reader adds at most 10% to the ability pass's wall time.
- P4 (stage 3): at the cut, at most 20% of tracks refuse as `below_null`
  on matches, and the Omen motion-and-lifetime rule resolves at least 80%
  of Omen tracks the glyph alone ties. The held-out Astra and Omen
  confusions were smoke discs and rings, not glyphs, so they predict
  nothing about where `pairwise_tie` and `pending` fall; stage 3 measures
  that.
- P5 (stage 3): audit-path verdicts agree with context-path verdicts on at
  least 95% of audit births.
- P6 (stage 3): the caster agent is right on more tracks than the slot,
  as on the stored windows.

## 9. What this plan does not settle

- Whether a spectator sees what the spectated player sees
  [domain:minimap/spectator-view-matches-self]: the player is unsure, and
  the views gate rests on it.
- Births per cast per ability, for the Riot bound.
- The two-flag rule itself: one out-of-sample answer (Killjoy:Q) supports
  it. On 2026-10-05 the player answered three rotation questions in chat:
  Seekers turn [domain:abilities/skye-seekers-minimap-glyph-turns-belief]
  and Cyber Cage turns
  [domain:abilities/cypher-cyber-cage-minimap-glyph-turns-belief], both as
  beliefs, and later Trapwire turns with the direction it is placed
  [domain:abilities/cypher-trapwire-minimap-glyph-turns-belief]. They are
  appended to `answers.jsonl` (rows `rotation:Skye:X`, L472,
  `rotation:Cypher:Q`, L473, and `rotation:Cypher:C`, L474) and named in
  `glyph_tables.ANSWER_FACTS`; `glyph-rotation-policy-0.1.2` marks all
  three `player_answer`, and no rotation row stays unsure. Skye:X stores a
  surprise: the two-flag rule reads it upright.
- Which game component draws a placed icon where an ability's components
  disagree (Deadlock:Q, Omen:E): game-data work; the player has answered
  what the icons do.
- The widget scale behind the Omen fact's pixel distances.
- How an Astra star's turn into Nova Pulse or Gravity Well draws; only the
  smoke turn is observed.
- The cost of reading the cache in order inside the pass; only the
  random-access read is measured.
- Shape-class drawings (recon bolt, smokes, walls): `ability-shape` and
  `minimap-dark` own them.

## Reproduce

From the repository root, single-threaded, Below Normal, no decode:

```powershell
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py cost --out <new dir>      # cost.json: 100 frames each on c40d950031bb, a06f04a0059f
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py rotation --out <new dir>  # rotation.json: stored windows, no cache
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py births --out <new dir>    # births.json: c40d950031bb, stored 2 Hz rows
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py table                     # game-data minimap counts
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py record --out <that dir>   # the 0.1.0 metric series
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py rotrule --out <new dir>   # rotrule.json: raw export, answers, dev angles, policy arm
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py record2 --out <rotrule dir>  # rotation_rule, heldout_020, heldout_030
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py baseline030               # dev_030: S1's baseline on eval 0.3.0 dev
.\.venv\Scripts\python.exe prototypes\glyph_channel_cost.py crosscheck                # cross_channel@matches: audio and self-seed precision
.\.venv\Scripts\python.exe prototypes\glyph_tables.py build --out <new dir>           # stage 1: both tables and build.json (storage only)
.\.venv\Scripts\python.exe prototypes\glyph_tables.py follow --out <that dir>         # follow.json: S1 follow, S4, pooled null (dev crop cache)
.\.venv\Scripts\python.exe prototypes\glyph_tables.py thrown --out <that dir>         # thrown.json: S5 (match crop caches)
.\.venv\Scripts\python.exe prototypes\glyph_tables.py record --out <that dir>         # glyph_tables/* metric series, once
.\.venv\Scripts\python.exe prototypes\glyph_tables.py bank --out <new dir> --tables <that dir>  # stage 2's reference bank
.\.venv\Scripts\python.exe -m reticle trial <sid> --reader ability_glyph --from cache   # stage 2: proposer and reader, no decode
```

Each writing command refuses an existing output file, and `--out` has no
default, so a rerun never overwrites the stored 0.1.0 outputs (the store's
`analysis/glyph-wiring-20261004/`) or the two-flag run
(`analysis/glyph-wiring-rotrule-20261004/`). `record2`, `baseline030` and
`crosscheck` refuse an input already recorded, so a rerun appends no
duplicate metric rows; `record` has no such guard and records once per
directory by hand.
