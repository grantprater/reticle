# Demo cast census: what each cast draws on the minimap

Measured 2026-09-26 by `prototypes/demo_cast_census.py`. The outputs live in
`<store>/analysis/demo-cast-census/`. The census asks the player to confirm
it. It is not a detector.

## Question

For every ability the solo demos exercise, what does the player's own cast
draw on the player's minimap, when does it appear relative to the tray's
charge drop, and how long does it last? The answer is a class per ability
(or `nothing`), an onset, a lifetime, and a colour and size, laid out so the
player can confirm or correct each row in one sitting.

## The answer in brief

I read [metric:demo_cast_census/table@demos#read=147] montages blind, one per
tray drop. [metric:demo_cast_census/table@demos#settings_cover=19] of them are
no cast at all: the settings menu's dim overlay covers the drop frame and the
tray bars read as a fall, often on every slot at one instant. `reticle.tray`
flags all of them `suspect`
([metric:demo_cast_census/table@demos#settings_cover_suspect=19]), and all of
them sit in the stored cast caches too
([metric:demo_cast_census/table@demos#settings_cover_stored=19]). My eye check
judged only the drops on which the two readers disagreed, so it never saw
them. Agreement was consistency, not accuracy. `reticle.tray` flags
[metric:demo_cast_census/table@demos#suspect=44] census drops `suspect` in
all, so the flag alone does not separate them. They include all twelve Cypher
drops, so the census holds no real Cypher cast.
[metric:demo_cast_census/table@demos#same_instant_drops=18] census drops share
their instant with another slot's drop, and
[metric:demo_cast_census/table@demos#same_instant_settings=16] of those are
settings-menu drops.

Of the [metric:demo_cast_census/table@demos#kept=128] real casts, the blind
read calls [metric:demo_cast_census/table@demos#kept_nothing=55] nothing and
[metric:demo_cast_census/table@demos#kept_drawn=70] drawn; three are unsure.
The drawn casts show four kinds of thing:

- **Travelling icons.** A thrown or sent ability travels from the caster as a
  round dark icon with its white glyph, and vanishes where it lands
  [domain:abilities/minimap-thrown-ability-icon]. Most of the
  [metric:demo_cast_census/table@demos#blind_compact_icon=38] `compact_icon`
  reads are these.
- **Dark discs.** Dark Cover, Cloudburst, Nebula, Waveform, Cove, Poison Cloud
  and, against the player's answer, Ruse land as dark grey discs
  ([metric:demo_cast_census/table@demos#blind_dark_disc=13] casts).
- **Lines and walls** run from the caster along the aim
  ([metric:demo_cast_census/table@demos#blind_wall_segments=9]
  `wall_segments`, [metric:demo_cast_census/table@demos#blind_teal_line=1]
  `teal_line`).
- **Aim previews.** A teal or red shape runs from the caster before the drop and
  vanishes at it or within a second [domain:abilities/minimap-aim-preview]. It
  belongs to the equipped ability, and a held preview can surface seconds after
  an unrelated drop.

The residual cannot say nothing. It calls nothing on
[metric:demo_cast_census/table@demos#residual_nothing=4] of the
[metric:demo_cast_census/table@demos#residual_rows=145] casts it measured and
agrees with the blind class on
[metric:demo_cast_census/table@demos#agree_residual=21]. It records what
changed on the widget, not what the cast drew.

## Predictions and outcomes

I logged seven predictions in the store's `notes/predictions.jsonl` (task
`demo-cast-census`) before the blind read and appended the outcomes after the
key opened.

| | prediction (confidence) | outcome |
|---|---|---|
| C1 | at least 40% of the census casts read `nothing` (0.6) | **right**: [metric:demo_cast_census/table@demos#blind_nothing=72] of [metric:demo_cast_census/table@demos#read=147]; without the settings-menu drops, [metric:demo_cast_census/table@demos#kept_nothing=55] of [metric:demo_cast_census/table@demos#kept=128] |
| C2 | at least 60% of drawn casts show their object by +1 s (0.6) | **right**: [metric:demo_cast_census/table@demos#drawn_by_1s=54] of [metric:demo_cast_census/table@demos#drawn_timed=68] |
| C3 | self-buffs and dashes read `nothing`: blind on 85%, residual on 70% (0.8) | **wrong**: the blind half holds, [metric:demo_cast_census/table@demos#self_blind_nothing=15] of [metric:demo_cast_census/table@demos#self_casts=16]; the residual calls nothing on [metric:demo_cast_census/table@demos#self_residual_nothing=1] |
| C4 | the residual class matches the blind class on 60% (0.6) | **wrong**: [metric:demo_cast_census/table@demos#agree_residual=21] of [metric:demo_cast_census/table@demos#residual_rows=145]; on drawn against nothing alone, [metric:demo_cast_census/table@demos#agree_residual_drawn=70] of [metric:demo_cast_census/table@demos#residual_drawn_rows=140] |
| C5 | the blind class matches my stated class per ability on 55% (0.5) | **right**: [metric:demo_cast_census/table@demos#agree_prior=93] of [metric:demo_cast_census/table@demos#prior_rows=147]; [metric:demo_cast_census/table@demos#kept_agree_prior=86] of the real casts |
| C6 | Dark Cover, Cloudburst, Recon Bolt, Hunter's Fury, Regrowth, Ruse, Hot Hands, Curveball, Run It Back as stated (0.85) | **wrong**: Ruse reads `dark_disc`, Recon Bolt `unsure`, and the settings menu hides Regrowth; the other six hold |
| C7 | Poison Cloud: no disc within 2 s of the throw, a disc 2-6 s after (0.6) | **right** by its falsifier, but a faint outline shows from +1 or +2 s |

**C3.** On the self casts the residual's components are mostly lit or red-hue
changes that start within 0.3 s of the drop. That fits a screen tint seen
through the translucent widget; the blind read notes blue, purple and flashing
screens on these casts.

**C4.** On drawn against nothing, the residual agrees wherever the blind read
saw something, because it says drawn almost everywhere. Its dark channel
follows compact icons, which are dark with a white glyph, and calls them
`dark_disc`.

**C6.** Dark Cover reads `dark_disc` on all four casts, with the residual's dark
component starting at
[metric:demo_cast_census/timing@demos#dark_cover_036_onset_s=0.167],
[metric:demo_cast_census/timing@demos#dark_cover_051_onset_s=0.083],
[metric:demo_cast_census/timing@demos#dark_cover_112_onset_s=0.067] and
[metric:demo_cast_census/timing@demos#dark_cover_127_onset_s=0.083] s; every
lifetime is censored by the next drop or the file's end, so none tests
[domain:abilities/omen-dark-cover]'s 15 s. Cloudburst reads `dark_disc` twice,
and the residual's dark component lasts
[metric:demo_cast_census/timing@demos#cloudburst_056_life_s=2.867] and
[metric:demo_cast_census/timing@demos#cloudburst_111_life_s=2.933] s, both
censored by the next drop, which fits [domain:abilities/jett-cloudburst-duration].
Hunter's Fury reads `teal_line` [domain:abilities/sova-hunters-fury-minimap-beam].
Hot Hands, both Curveballs and Run It Back read nothing
[domain:abilities/phoenix-minimap-objects].

Ruse (cast 034, `28f53bfddbbe` 14.5 s) shows two dark discs, about 24 px and
90 px apart, from 0 s to at least +4 s. The residual's dark component starts at
[metric:demo_cast_census/timing@demos#ruse_034_onset_s=0.0] s and lasts
[metric:demo_cast_census/timing@demos#ruse_034_life_s=5.85] s, censored by the
end of the file. The player answered that Ruse is never drawn
[domain:abilities/clove-rouse]; two discs at once fit a batch launch
[domain:abilities/clove-ruse-batch-launch]. This is the first question below.
Recon Bolt (086) draws nothing to +2 s and a teal ring with a crosshair at
+4 s; the residual's teal component starts at
[metric:demo_cast_census/timing@demos#recon_bolt_086_onset_s=1.833] s. I read it
unsure because the ring might be the next cast's preview.

**C7.** On `6bb88dba5d2c` 9.5 s the residual's dark disc starts at
[metric:demo_cast_census/timing@demos#poison_cloud_022_onset_s=2.933] s and
lasts [metric:demo_cast_census/timing@demos#poison_cloud_022_life_s=4.8] s; the
outline returns at +8 s. On `afa5bc60b935` 18.567 s it starts at
[metric:demo_cast_census/timing@demos#poison_cloud_074_onset_s=4.833] s. Both
fit [domain:abilities/viper-poison-cloud-toggle]. Before the disc, a faint
circle outline marks the emitter [domain:abilities/viper-poison-cloud-emitter-outline].

## The appearance table

Casts are montage numbers: open
`<store>/analysis/demo-cast-census/montage/keyed_NNN.png`. Onset and "gone by"
are the first montage frame (s from the drop) that shows the object and the
first that no longer does. Sizes and distances are my estimates from the
montage, in widget pixels. `table.json` holds every cast's full description.

**Drawn.**

| ability (slot) | casts | class | onset | gone by | what it looks like |
|---|---|---|---|---|---|
| Astra: Gravity Well (C) | 084 | other | 0 | persists | no new object: a yellow star icon turns into a dark ringed icon, and another vanishes |
| Astra: Nebula (E) | 063, 142 | dark_disc | 0 | persists | [domain:abilities/astra-nebula-minimap-disc] |
| Breach: Rolling Thunder (X) | 133 | wall_segments | +2 | +4 | a thin red bar ~10x55 px, ~60 px from self |
| Chamber: Trademark (C) | 073 | compact_icon | +4 | persists | a dark icon in a pale ring below self; its glyph looks like slot E's |
| Clove: Ruse (E) | 034 | dark_disc | 0 | persists | two dark discs ~24 px, ~90 px apart, at once |
| Deadlock: Barrier Mesh (C) | 057 | compact_icon | +0.5 | persists | a dark icon ~20 px with a white boxed-X glyph beside self; faint thin blue lines from +2 s |
| Deadlock: GravNet (E) | 109 | brief_flash | +0.5 | +1 | a filled yellow disc ~40 px, one frame [domain:abilities/deadlock-gravnet-detonation-flash] |
| Deadlock: Sonic Sensor (Q) | 090, 143 | compact_icon, nothing | +4 | persists | a third dark icon beside self on 090; nothing new on 143 |
| Fade: Nightfall (X) | 135 | wall_segments | +0.5 | +4 | a red bar ~60x10 px across the aim, ~55 px ahead by +2 s |
| Fade: Prowler (C) | 126, 129 | compact_icon | +0.5 | +4 | [domain:abilities/fade-prowler-minimap-icon] |
| Gekko: Dizzy (E) | 014 | compact_icon | +4 | +8 | a faint translucent blue disc ~20 px, one frame; weak |
| Gekko: Mosh Pit (C) | 028 | compact_icon | +4 | persists | a light green disc ~22 px beside self |
| Gekko: Thrash (X) | 094 | compact_icon | +1 | +8 | a dark teal-rimmed icon ~20 px, ~40 px from self |
| Gekko: Wingman (Q) | 009 | compact_icon | +0.5 | +8 | a dark teal-rimmed icon ~16 px with a creature glyph walks ~70 px |
| Harbor: Cove (E) | 107 | dark_disc | +0.5 | persists | a dark icon with a white swirl, then a dark grey disc ~26 px from +2 s: Dark Cover's two phases |
| Harbor: High Tide (Q) | 019 | wall_segments | 0 | persists | a dark icon leaves self trailing a lavender-blue curve ~200 px, which stays after the icon goes |
| Harbor: Reckoning (X) | 140 | wall_segments | +2 | persists | a lavender-blue bar ~70 px wide moves away along the aim, ~40 to ~110 px |
| Harbor: Storm Surge (C) | 068 | brief_flash | +1 | +2 | a faint teal-tinted circle ~30 px along the aim, one frame |
| Iso: Undercut (Q) | 116 | compact_icon | +0.5 | +2 | a dark icon ~18 px flies 40-70 px |
| Jett: Cloudburst (C) | 056, 111 | dark_disc | +1, +2 | +4, +8 | a dark grey disc ~20-24 px, 50-85 px from self |
| KAY/O: FLASH/drive (Q) | 080, 081 | compact_icon | +0.5 | +2 | [domain:abilities/kayo-flashdrive-minimap-icon] |
| KAY/O: ZERO/point (E) | 139 | teal_ring | +1 | +4 | a teal-rimmed, tinted disc r~45 px with a dark icon at its centre |
| Killjoy: ALARMBOT (Q) | 088 | compact_icon | +4 | persists | a second, smaller dark icon beside an older one |
| Killjoy: Lockdown (X) | 137 | compact_icon | +1 | persists | a dark icon ~20 px under self; the teal ring r~100 px predates the drop |
| Killjoy: Nanoswarm (C) | 020, 047 | compact_icon | +1 | persists | [domain:abilities/killjoy-nanoswarm-minimap-icon] |
| Miks: M-pulse (C) | 001, 138 | compact_icon | +2, +1 | +8 | inconsistent: a white target icon ~16 px ~90 px away (001); a dark teal-rimmed icon ~24 px beside self (138) |
| Miks: Waveform (E) | 012 | dark_disc | 0 | persists | two dark discs ~22 px, 70 px apart, at once |
| Neon: Fast Lane (C) | 017 | wall_segments | 0 | +8 | one thin blue line from self, ~80 px by +4 s; [domain:abilities/neon-fast-lane] says two |
| Neon: Relay Bolt (Q) | 095 | compact_icon | +1 | +4 | a yellow ring outline ~30 px, ~120 px along the aim |
| Omen: Dark Cover (E) | 036, 051, 112, 127 | dark_disc | +0.5 | persists | [domain:abilities/omen-dark-cover-minimap-phases] |
| Omen: From the Shadows (X) | 045, 066 | other | +2 | +4 | no object: the widget turns to a black full-map view, then self has moved |
| Omen: Paranoia (Q) | 003, 130 | compact_icon | +0.5 | +2 | [domain:abilities/omen-paranoia-minimap-icon] |
| Phoenix: Blaze (C) | 070 | wall_segments | 0 | persists | a dark icon leaves self trailing an orange line ~100 px; the icon goes at +1 s, the line stays |
| Raze: Boom Bot (C) | 035 | compact_icon | 0 | +8 | a dark teal-rimmed icon with a teal arrow drifts ~30 px |
| Reyna: Leer (C) | 093, 103 | compact_icon | +0.5 | +4 | [domain:abilities/reyna-leer-minimap-icon] |
| Skye: Guiding Light (E) | 039, 117 | compact_icon | +0.5 | +4 | [domain:abilities/skye-guiding-light-minimap-icon] |
| Skye: Trailblazer (Q) | 087 | compact_icon | +0.5 | persists | a dark teal-rimmed icon ~20 px moves off, ~60 px by +4 s |
| Sova: Hunter's Fury (X) | 059 | teal_line | 0 | +8 | a teal line ~10 px wide, ~200 px long, from self along the aim, turning with it |
| Sova: Owl Drone (C) | 048 | compact_icon | +1 | +8 | self's ring turns teal while a dark teal-rimmed icon moves ~30 px off |
| Tejo: Armageddon (X) | 096 | pale_region | 0 | +8 | a pale yellow hatched band ~40x120 px from self along the aim, turning with it |
| Tejo: Guided Salvo (E) | 037, 100 | compact_icon | 0 | +2, +4 | [domain:abilities/tejo-guided-salvo-minimap-rings] |
| Tejo: Stealth Drone (C) | 125 | compact_icon | +0.5 | +8 | a dark teal-rimmed icon ~22 px travels ~100 px |
| Veto: Chokehold (Q) | 055 | compact_icon | +2 | persists | a dark icon ~20 px in a pale ring ~40 px, ~40 px from self |
| Veto: Crosscut (C) | 025, 097 | nothing, compact_icon | 0 | +8 | a dark icon ~20 px inside a pale ring r~95 px (097); on 025 the icon predates the drop |
| Viper: Poison Cloud (Q) | 022, 074 | dark_disc | +1, +2 | persists | a faint outline ~28-30 px, then a dark disc (C7 above) |
| Viper: Toxic Screen (E) | 089, 106 | wall_segments | +0.5 | persists | [domain:abilities/viper-toxic-screen-minimap-growth] |
| Vyse: Arc Rose (E) | 006 | teal_ring | +8 | persists | only a teal ring r~90 px round self at +8 s, likely Steel Garden's preview; the widget is hidden from +0.5 to +2 s |
| Vyse: Razorvine (C) | 023, 043 | compact_icon | +0.5 | +4, +8 | [domain:abilities/vyse-razorvine-minimap-icon] |
| Vyse: Shear (Q) | 044 | other | 0 | persists | a short magenta bar ~20 px beside self that moves with self |
| Waylay: Convergent Paths (X) | 030 | wall_segments | +2 | +4 | two thin red parallel lines ~100 px from self |
| Yoru: FAKEOUT (C) | 091 | compact_icon | 0 | persists | a dark teal-rimmed icon ~20 px drifts off, ~110 px by +8 s |
| Yoru: GATECRASH (E) | 120, 128 | compact_icon | +0.5 | +8 | [domain:abilities/yoru-gatecrash-minimap-icon] |

**Nothing drawn.** A `nothing` cannot tell "draws nothing" from "equipped and
not used": a drop also comes from an ability equipped and put away. The cast
numbers follow each name; an asterisk marks a settings-menu drop, which is no
cast.

- Astra: Nova Pulse (040; a star icon vanishes at 0 s), Astral Form / Cosmic Divide (110)
- Breach: Aftershock (141), Fault Line (004), Flashpoint (136, 145\*)
- Chamber: Headhunter (104), Rendezvous (108), Tour De Force (071)
- Clove: Meddle (085)
- Cypher: Cyber Cage (016\*, 041\*, 058\*), Neural Theft (050\*, 101\*, 121\*),
  Spycam (026\*, 075\*, 118\*), Trapwire (010\*, 124\*, 131\*)
- Deadlock: Annihilation (032)
- Fade: Haunt (015), Seize (002)
- Iso: Contingency (134), Kill Contract (099)
- Jett: Blade Storm (102), Tailwind (011), Updraft (007)
- KAY/O: FRAG/ment (132), NULL/cmd (062)
- Killjoy: TURRET (076)
- Miks: Bassquake (122), Harmonize (053)
- Neon: High Gear (005, 083\*), Overdrive (077)
- Omen: Shrouded Step (042, 079, 146; 123 unsure)
- Phoenix: Curveball (114, 119), Hot Hands (115), Run it Back (147)
- Raze: Blast Pack (038, 113), Paint Shells (046), Showstopper (061)
- Reyna: Devour (031), Dismiss (072); both drops may be a magenta wash over full bars
- Sage: Barrier Orb (065), Healing Orb (008\*), Resurrection (078\*), Slow Orb (029, 033)
- Sova: Shock Bolt (060, 069)
- Tejo: Special Delivery (054)
- Veto: Interceptor (144)
- Viper: Snake Bite (027, 049), Viper's Pit (052\*, 082)
- Vyse: Steel Garden (092; its ring predates the drop)
- Waylay: Lightspeed (013), Refract (024), Saturate (021)
- Yoru: BLINDSIDE (067), DIMENSIONAL DRIFT (105)

**Not observed.** Skye's Regrowth (098) and Seekers (064): the settings menu
covers every frame from the drop to the end of the file. Iso's Double Tap
(018) and one Shrouded Step (123): a teal band after +2 s that looks like a
held aim preview. Sova's Recon Bolt (086): C6 above.

**Against the player's match answers.** The player's tray-object answers from
match sessions agree with the census on every ability both observed (Hot
Hands, Curveball, Meddle, Guiding Light, Trailblazer, Owl Drone, Shock Bolt,
Hunter's Fury, Blaze) except Ruse.

## Disagreements

`table.json` keeps every disagreement: `disagree_residual` (blind against the
residual) and `disagree_prior` (blind against my stated class).

Against my stated class, the blind read saw an object where I predicted none on
Rolling Thunder, Ruse, Nightfall, Mosh Pit, Reckoning, Storm Surge, Undercut,
FLASH/drive, M-pulse, Relay Bolt, Paranoia, Guided Salvo and Convergent Paths.
It saw nothing where I predicted an object on Astral Form, Rendezvous, Sonic
Sensor (one of two), Haunt, Contingency, TURRET, Bassquake, Barrier Orb,
Crosscut (one of two), Interceptor, Viper's Pit and Steel Garden, and on the
Cypher kit, which the settings menu hid. Where both saw an object the class
differed on Gravity Well, Barrier Mesh, ZERO/point, ALARMBOT, Lockdown, From
the Shadows, Armageddon, Arc Rose and Shear. ALARMBOT is the sharpest:
[domain:abilities/killjoy-alarmbot] calls it a dark disc, and cast 088 shows a
small dark icon with white line art, which the fact also describes.

Against the residual, most disagreements share three causes. The dark channel
calls a compact icon `dark_disc`. Screen tints and flashes pass through the
translucent widget and read as lit or hue changes, so the residual rarely says
nothing. A held aim preview, or the next cast's object, lands inside the +12 s
window. The residual's timings are still useful where the blind read agrees
the object is there, as C6 and C7 use them.

## How the casts were found

**Crops.** Each of the [metric:demo_cast_census/cache@demos#demos=33] solo
demos (the `ability-demo` tag plus `2ba870ccbd50`) got the production
whole-capture crop cache (`reticle scan <sid> --only roi_cache --cache-roi
minimap --cache-hz 15`, NVDEC, one scan at a time at Idle priority):
[metric:demo_cast_census/cache@demos#frames=20163] frames,
[metric:demo_cast_census/cache@demos#gb=2.08] GB, at a mean
[metric:demo_cast_census/cache@demos#mean_hz=13.57] Hz rather than the 15 Hz
asked for. Three samples per demo matched the decoded frame exactly
([metric:demo_cast_census/cache@demos#rects_identical=198] of
[metric:demo_cast_census/cache@demos#rects_checked=198] crops). The cache
holds the minimap and the ability tray (`hud_abilities`); everything after
this step reads only those crops and decodes no video.

**Drops.** `reticle.tray` (`tray-0.1.0`) read the tray at 2 Hz from the
cached crops (`slot_counts`, then `drops`), bridging refused samples as
`reticle tray` does. It found [metric:demo_cast_census/casts@demos#drops=161]
drops. Matched within 0.75 s against the stored cast caches
(`<store>/casts/`): [metric:demo_cast_census/casts@demos#stored=139] stored,
[metric:demo_cast_census/casts@demos#matched=135] matched,
[metric:demo_cast_census/casts@demos#added=17] added,
[metric:demo_cast_census/casts@demos#missing=4] missing. Two demos
(`29eff6920e8f` Deadlock, `afa5bc60b935` Viper) have no stored cast cache;
their [metric:demo_cast_census/casts@demos#no_stored_cache_real=9] drops,
all real, are counted apart from the added ones.

I judged by eye every drop that disagreed with the stored cache, that left a
slot above 1.05 charges, or that left 0.7 or more
([metric:demo_cast_census/casts@demos#eyed=30] drops), from strips of the
tray crops 1.5 s before to 0.8 s after (`tray_strips/`). Of these,
[metric:demo_cast_census/casts@demos#eyed_false=14] were false: teal light,
flame or a placement view washing over a full bar. Every drop that left its
slot at 0.8 charges or more was a wash
([metric:demo_cast_census/casts@demos#stays_full_false=8] of
[metric:demo_cast_census/casts@demos#stays_full=8]). All four missing stored
casts were false too ([metric:demo_cast_census/casts@demos#missing_false=4]);
their verdicts sit in `casts.json` beside each row. That leaves
[metric:demo_cast_census/casts@demos#census=147] census casts over 28 agents.
Brimstone (`2ba870ccbd50`) and one Cypher demo (`79a706a7ce4c`) contribute
none: Brimstone's two drops were washes, and the Cypher demo's tray never
drops.

Against the prototype reader it replaced (`prototypes/ability_hud.py`),
`reticle.tray` adds [metric:demo_cast_census/reader-diff@demos#only_tray=5]
drops and loses [metric:demo_cast_census/reader-diff@demos#only_prototype=0];
all five are bridged across a refused sample
([metric:demo_cast_census/reader-diff@demos#only_tray_across_gap=5]), and
[metric:demo_cast_census/reader-diff@demos#only_tray_real=4] are real casts.

**The `reticle tray` gap.** `reticle tray` cannot run on a demo. It reads the
session's HUD table for the player's deaths and its rounds table for the
round windows, and `ability_timeline.player_tray_casts` keeps only drops in a
live round phase before the player's first death. A solo demo has neither
table: `store.read_hud` exits with "no HUD reads", and with a HUD but no
rounds every drop would be refused as `no_round`. The census therefore calls
`tray.slot_counts` and `tray.drops` itself over `_cache_grid`, as
`cmd_tray` does, and writes no `tray_drop` events. A demo mode for
`reticle tray` (the whole capture as one live window, no deaths) would close
the gap.

## The residual

Per cast, over [-2, +12] s at the cache rate, the residual compares each
minimap crop with the frame at -1 s. Every static value comes from the baked
`(map, profile)` geometry: the lighting reference, the floor mask, the art
footprint and the widget disc. No session median exists anywhere in the
census. Frames where `minimap.widget_drawn` fails are skipped, and the self
icon is masked with the `minimap_dark` margin.

The components are `raw_dark` and `raw_lit` (`reticle.lighting`), teal
(`ability_shapes.teal`) on the footprint support and over the whole widget
disc, white, and twelve 30-degree hue bins. A component turns on when its new
pixels exceed the pre-cast maximum by 40 px on two consecutive drawn frames,
and ends after 1 s below that. The lifetime is censored at the next drop, the
end of the file, or a frame where the widget is not drawn, and the reason is
stored. Each cast writes `features/<sid>_<t_ms>_<slot>.npz` and a summary row
in `residual.json`.

The widget is translucent, and the world shows through it. On the footprint
support, white and the hue bins followed the world: Jett's Updraft at
`ff19748eea8c` 12.7 s read as a coloured icon while the minimap drew nothing.
White and hue are therefore read on the baked floor eroded by 2 px. The floor
itself still carries the world's tint, so the hue bins remain the weakest
channel (see the disagreements).

## Montages and the blind read

Each census cast has a blind montage (`montage/blind_NNN.png`): the minimap
at native scale at -1, 0, +0.5, +1, +2, +4 and +8 s from the drop, and the
tray at -1, 0 and +0.5 s, under a legend that shows only the cast number. The
numbers follow a salted hash of the cast key, so a number says nothing about
its demo. The keyed montage (`keyed_NNN.png`) adds the agent, slot, ability,
residual class and the residual masks as outlines. The key sits in
`key.json`.

I read every blind montage before `table` opened the key (`unblinded.json`
records the moment; `read --add` refuses after it). Each row in
`blind_read.jsonl` names one class of ten (`nothing`, `dark_disc`,
`teal_ring`, `teal_line`, `wall_segments`, `compact_icon`, `pale_region`,
`brief_flash`, `other`, `unsure`), the first frame the object shows, the
first frame it has gone by or `persists`, and one line of description.

Three things weaken the blindness. The montage shows the tray, and a reader who
knows the glyphs can name the slot's ability from it; the read is blind to the
key, not to the tray. I had opened cast 112 (`b9558488a607` 47.05 s, a Dark
Cover) while building the residual and did not mark it `seen_before`; the row
stands as written. I redid cast 036's row before the key opened, from
`compact_icon` to `dark_disc`, to match cast 051's two phases; the redo is the
second row for 036 in `blind_read.jsonl`, and the last row wins.

## Questions for the player

Open these keyed montages first, in this order
(`<store>/analysis/demo-cast-census/montage/keyed_NNN.png`):

1. **keyed_034, Clove's Ruse** (`28f53bfddbbe`, `clove.mp4`, 14.5 s). Two dark
   discs appear at 0 s. You answered that Ruse is never drawn
   [domain:abilities/clove-rouse]. Are these Ruse clouds, drawn in a demo but
   not in a match, or something else?
2. **keyed_016 and keyed_010, a settings-menu drop** (`d95cfad5693a`,
   `2026-09-02 16-08-43.mp4`, 47.517 s; `eb10db50b1fb`,
   `2026-09-02 16-06-56.mp4`, 40.017 s). Is this the settings menu over the
   tray, with no cast? If so, every Cypher drop is one, and the tray reader
   needs a guard against it.
3. **keyed_086, Sova's Recon Bolt** (`02cf738b1c8f`,
   `2026-09-03 19-29-26.mp4`, 23.067 s). Is the teal ring with a crosshair at
   +4 s this bolt's ring [domain:abilities/sova-recon-bolt-minimap-ring], or
   the next cast's preview?
4. **keyed_137, keyed_076** (`dae6f33f3f48`, `2026-09-03 19-10-11.mp4`, 41.05
   and 33.55 s) **and keyed_092, keyed_006** (`64d0fb783be2`,
   `2026-09-03 19-33-47.mp4`, 51.0 and 39.0 s). A teal ring r~90-100 px with a
   tinted interior shows before a Lockdown or Steel Garden drop. Is it the
   ultimate's placement preview?
5. **keyed_045 and keyed_066, Omen's From the Shadows** (`e78e75b2d191`,
   `2026-09-03 19-16-07.mp4`, 29.567 s; `b9558488a607`,
   `2026-09-06 17-00-35.mp4`, 75.0 s). The widget turns into a black full-map
   view and Omen reappears elsewhere. Is that all it draws?
6. **Any montage, e.g. keyed_005** (`f1cf160b213d`, `2026-09-03 19-14-22.mp4`,
   18.067 s). A pale ring round self shows on
   [metric:demo_cast_census/table@demos#self_ring=119] of
   [metric:demo_cast_census/table@demos#montages=147] montages. What is it?
7. **keyed_001 and keyed_138, Miks's M-pulse** (`ad6b67cdf91d`,
   `2026-09-03 19-12-37.mp4`, 14.5 and 7.0 s). The two casts draw different
   icons. Which is M-pulse's?
8. **keyed_017, Neon's Fast Lane** (`f1cf160b213d`, 3.0 s). One blue line,
   where [domain:abilities/neon-fast-lane] says two.

`label` walks the keyed montages one cast at a time: a digit picks a class, U
marks unsure, A goes back one cast, Q quits.

    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py label

Answers append to `<store>/labels/demo_cast_class/<sid>.jsonl`, keyed
`sid:t_ms:slot`; the last row for a key wins, and answered casts are skipped,
so a pass resumes. I ran it once with `--dry-run --keys 5,a,u,q`: it showed
cast 001, printed a `compact_icon` row, went back, printed an `unsure` row and
quit, and the label directory stayed absent. No label row exists.

## What the census could not do

- **No Brimstone and no real Cypher.** Brimstone's two drops (`2ba870ccbd50`)
  were washes over full bars; the Cypher demo `79a706a7ce4c` never drops; the
  other Cypher demos' drops are all settings-menu drops.
- **Seven sampled instants.** The montage shows -1, 0, +0.5, +1, +2, +4 and
  +8 s, so an onset or end is known only to the interval between frames, and a
  sub-0.5 s flash can fall between them. The next drop often lands before +8 s.
- **Lifetimes are mostly censored.** The demos cast one ability after another,
  so the residual's lifetimes end at the next drop or the file's end; none
  tests a duration longer than a few seconds.
- **Two Cypher demos use the other profile.** They do not change the answer,
  since every Cypher drop is a settings-menu drop.
- **The residual's hue bins follow the world.** The widget is translucent, so
  a screen tint passes through it; a hue-only class is weak evidence.
