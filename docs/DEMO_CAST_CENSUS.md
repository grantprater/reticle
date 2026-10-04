# Demo cast census: what each cast draws on the minimap

Measured 2026-09-26 by `prototypes/demo_cast_census.py`. The outputs live in
`<store>/analysis/demo-cast-census/`. The census asks the player to confirm
it. It is not a detector.
The four demos re-recorded to the Omen protocol have their own section,
[the re-recorded protocol demos](#the-re-recorded-protocol-demos-2026-09-26).

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
settings-menu drops. The menu witness now names all of them `menu_open`
([MENU_WITNESS.md](MENU_WITNESS.md)).

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
quit, and the label directory stayed absent. The player labelled the keyed
montages later on 2026-09-26, and his rows now fill that directory.

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

## The player's answers (2026-09-26)

Shown the montages named above, the player answered the same day:

- **keyed_034, Ruse.** The two discs are Ruse clouds, perfectly bounded, and
  Ruse is the only Clove ability that draws anything. The earlier answer that
  Ruse never draws is retracted, and [domain:abilities/clove-rouse] now says
  so; the census's prior was wrong and its blind read right. Why the
  tray-object pass found nothing on nine match casts stays open.
- **The Skye demo `6ab7a9e99235` at 28 s.** The ultimate was equipped, not
  cast, and the session ended: the same-instant C and X drops at 28.0 s are
  the menu dimming the tray [domain:hud/menu-dims-tray], one more of the
  settings-menu drops. At 22 s the cast was Guiding Light, the hawk.
- **The Sova demo `02cf738b1c8f` 14.5-15.5 s.** One Shock Bolt, another near
  19 s; no Recon Bolt. Both bolts are charged before release and have a
  toggleable bounce count shown in a HUD element just below screen centre
  [domain:abilities/sova-bolt-charge-and-bounce]. The tray read an E drop and
  two Q drops for that one cast; whether charging moves a bar is unmeasured.
- **Recordings.** The player will re-record Sova, Phoenix, Skye and Clove to
  the Omen protocol and then run the labelling pass.

## The re-recorded protocol demos (2026-09-26)

The player re-recorded four demos to the Omen protocol: standing still, casts
spaced, equip-hold-cast, three of each ability, Pick-me-up and Not Dead Yet
included. The census ran on them with `--run rerecorded`. The outputs live in
`<store>/analysis/demo-cast-census-rerecorded/`, and every count below is
recorded under a part named `rerecorded-*`.

| session | agent | capture file | length | cached frames |
|---|---|---|---|---|
| `aab12e41dcfc` | Sova | `C:\Users\grant\Videos\2026-09-26 19-39-06.mp4` | 65.7 s | [metric:demo_cast_census/rerecorded-cache@aab12e41dcfc#frames=904] |
| `6afc32cb46b4` | Phoenix | `C:\Users\grant\Videos\2026-09-26 19-41-03.mp4` | 59.0 s | [metric:demo_cast_census/rerecorded-cache@6afc32cb46b4#frames=812] |
| `fc02a2c1ac01` | Skye | `C:\Users\grant\Videos\2026-09-26 19-42-54.mp4` | 46.8 s | [metric:demo_cast_census/rerecorded-cache@fc02a2c1ac01#frames=638] |
| `0c6c52a65b9e` | Clove | `C:\Users\grant\Videos\2026-09-26 19-44-34.mp4` | 46.8 s | [metric:demo_cast_census/rerecorded-cache@0c6c52a65b9e#frames=637] |

The steps were the first census's, one process at a time: the whole-capture
crop cache at 15 Hz with NVDEC, `reticle.tray` drops judged by eye, the
residual, the montages, the blind read and the table. Six sampled crops per
demo matched the decoded frame (on Sova,
[metric:demo_cast_census/rerecorded-cache@aab12e41dcfc#rects_identical=6] of
[metric:demo_cast_census/rerecorded-cache@aab12e41dcfc#rects_checked=6]). The
first steps ran at Idle priority and the later ones at Below Normal with four
threads, as the player allowed for this session. Three steps are new: `holds`
times each Sova bolt from the bow's glow over the tray, `sweep` asks
`reticle.ability_shapes` for its shapes on every cached frame, and `discs`
reads each smoke disc's life at its centre.

### In brief

- **Fifteen casts, not 48.** Each charge falls once and never refills, so no
  ability shows three casts on the tray.
- **The classes repeat.** On the eleven abilities both censuses saw, the blind
  majority here equals the first census's on ten, and on fourteen of fifteen
  casts. The one change is Recon Bolt, whose first-census drop was no Recon
  Bolt.
- **Ruse draws one disc per cloud**
  [domain:abilities/clove-ruse-minimap-duration].
- **Regrowth spends no charge,** so the tray never sees it
  [domain:abilities/skye-regrowth-no-tray-drop]; the shape sweep finds its
  ring round Skye.
- **Four abilities were never cast:** Pick-me-up, Not Dead Yet, Run it Back
  and Seekers.

### Predictions and outcomes

I logged nine predictions (task `demo-cast-census`, run `rerecorded`) before
the cache was built and appended the outcomes after the key opened.

| | prediction (confidence) | outcome |
|---|---|---|
| R1 | three casts per ability, 12 per demo, 48 in all, and one menu drop at each session's end (0.5) | **wrong**: [metric:demo_cast_census/rerecorded-casts@rerecorded#census=15] casts, and a menu drop on [metric:demo_cast_census/rerecorded-casts@rerecorded#menu_demos=2] demos |
| R2 | on the first census's eleven abilities, the blind class equals its class on at least 80% (0.7) | **right**: [metric:demo_cast_census/rerecorded-table@rerecorded#agree_prior=15] of [metric:demo_cast_census/rerecorded-table@rerecorded#prior_rows=15] |
| R3 | every Ruse reads `dark_disc`, one disc per cloud, the count equal to the charges spent (0.8) | **right**: [metric:demo_cast_census/rerecorded-table@rerecorded#ruse_count_eq_spent=2] of [metric:demo_cast_census/rerecorded-table@rerecorded#ruse_casts=2] |
| R4 | Pick-me-up and Not Dead Yet read nothing on 6 of 6 (0.8) | **untested**: neither was cast |
| R5 | Blaze reads `wall_segments` on 3 of 3 (0.7) | **right** on the one cast |
| R6 | a teal ring round the bolt within 4 s on 3 of 3 Recon Bolts (0.75) | **right** on the one cast |
| R7 | each bolt's hold shows as the bow's glow, 0.5-4 s on all six, with a false glow drop (0.5) | **wrong**: three bolts, two holds outside the range; the false drop came |
| R8 | Regrowth reads `teal_ring` on 3 of 3; Seekers `compact_icon` on 3 of 3 (0.6) | **untested** by the blind read: no drop for either |
| R9 | blind nothing on 18-24 of 48; residual nothing on at most 12 (0.7) | **wrong** as worded; right in rate |

**R1.** `reticle.tray` found
[metric:demo_cast_census/rerecorded-casts@rerecorded#drops=20] drops. No
stored cast cache exists for these sessions, so I judged every drop by eye
from its tray strip
([metric:demo_cast_census/rerecorded-casts@rerecorded#eyed=20]):
[metric:demo_cast_census/rerecorded-casts@rerecorded#eyed_false=2] were false
and [metric:demo_cast_census/rerecorded-casts@rerecorded#eyed_menu=3] were the
settings menu, which leaves 15 casts. They cover
[metric:demo_cast_census/rerecorded-casts@rerecorded#abilities_cast=11] of the
[metric:demo_cast_census/rerecorded-casts@rerecorded#kit_abilities=16] kit
abilities, and
[metric:demo_cast_census/rerecorded-casts@rerecorded#abilities_cast_3=0] reach
three. Every charge fell once and none refilled: Ruse, Curveball, Guiding
Light and Shock Bolt spent both charges; Meddle, Blaze, Hot Hands, Owl Drone,
Recon Bolt, Trailblazer and Hunter's Fury spent one. Over the spent signature
slots the tray prints a cooldown count ("40" over Ruse, "50" over Recon Bolt
and Guiding Light), which fits the catalogue's restocks (Ruse 40 s, Recon Bolt
60 s). The manifests carry the tag `infinite-abilities`; the tray contradicts
it. The minimap agrees with the tray: a 1 Hz contact sheet of each demo shows
one Owl Drone, one Recon ring, one Hunter's Fury line, one Blaze wall, two
Ruse discs and one Regrowth ring, and no second copy of any.

The menu dimmed the tray [domain:hud/menu-dims-tray] and raised a drop on two
demos. On Clove at 44.05 s a CLOSE SETTINGS button covers the tray, and C and
X fall together; on Phoenix every bar and icon dims at 55.68 s and stays dim
to the end. Sova opens the menu at about 61 s, but every bar was already
empty, so nothing fell. Skye's capture ends on black with no menu. Of the two
false drops, the bow's glow lifted Sova's Q at 18.07 s, and a white flash and
flames over the screen (53.25-54.5 s) washed Phoenix's X at 54.05 s; the X
pips stay full through it.

**R7.** Sova's bow glows cyan over the tray while a bolt is up. `holds` finds
the glow run that holds each bolt's drop
([metric:demo_cast_census/rerecorded-holds@rerecorded#held=3] of
[metric:demo_cast_census/rerecorded-holds@rerecorded#bolts=3] bolts). The
first Shock Bolt's glow runs
[metric:demo_cast_census/rerecorded-holds@rerecorded#shock1_hold_s=12.9] s
before its drop, the second's
[metric:demo_cast_census/rerecorded-holds@rerecorded#shock2_hold_s=5.67] s,
and the Recon Bolt's
[metric:demo_cast_census/rerecorded-holds@rerecorded#recon1_hold_s=2.18] s.
Two of three lie outside 0.5-4 s, and three bolts are not six. The glow
raised the one false Q drop, as predicted. The glow marks the bow raised; it
cannot split the equip from the charge
[domain:abilities/sova-bolt-charge-and-bounce], so a 12.9 s glow may hold
several equips or a long aim.

**R2 and the comparison with the first census.** Against the first census's
blind majority per ability, the blind read here agrees on
[metric:demo_cast_census/rerecorded-table@rerecorded#compare_majority_agree=10]
of [metric:demo_cast_census/rerecorded-table@rerecorded#compare_judged=11]
abilities and on
[metric:demo_cast_census/rerecorded-table@rerecorded#compare_casts_agree=14]
of [metric:demo_cast_census/rerecorded-table@rerecorded#compare_casts=15]
casts. The cast numbers are this run's montages.

| ability (slot) | first census: class (n) | here: class (n) | agreement | casts here |
|---|---|---|---|---|
| Clove: Meddle (Q) | nothing (1) | nothing (1) | 1 of 1 | 012 |
| Clove: Ruse (E) | dark_disc (1) | dark_disc (2) | 2 of 2 | 001, 004 |
| Clove: Pick-me-up (C) | not cast | not cast | | |
| Clove: Not Dead Yet (X) | not cast | not cast | | |
| Phoenix: Blaze (C) | wall_segments (1) | wall_segments (1) | 1 of 1 | 013 |
| Phoenix: Hot Hands (Q) | nothing (1) | nothing (1) | 1 of 1 | 007 |
| Phoenix: Curveball (E) | nothing (2) | nothing (2) | 2 of 2 | 002, 009 |
| Phoenix: Run it Back (X) | nothing (1) | not cast | | |
| Sova: Owl Drone (C) | compact_icon (1) | compact_icon (1) | 1 of 1 | 006 |
| Sova: Shock Bolt (Q) | nothing (2) | nothing (2) | 2 of 2 | 005, 008 |
| Sova: Recon Bolt (E) | unsure (1) | teal_ring (1) | 0 of 1 | 011 |
| Sova: Hunter's Fury (X) | teal_line (1) | teal_line (1) | 1 of 1 | 003 |
| Skye: Regrowth (C) | unsure (1, menu) | no drop; the sweep finds a ring | | |
| Skye: Trailblazer (Q) | compact_icon (1) | compact_icon (1) | 1 of 1 | 010 |
| Skye: Guiding Light (E) | compact_icon (2) | compact_icon (2) | 2 of 2 | 014, 015 |
| Skye: Seekers (X) | unsure (1, menu) | not cast | | |

The Recon Bolt row does not dispute Recon Bolt's class: the player answered
that the first census's Recon Bolt drop (`02cf738b1c8f` 23.067 s) was no
Recon Bolt at all.

**R3.** Both Ruse drops spent one charge each
([metric:demo_cast_census/rerecorded-table@rerecorded#ruse_spent=2] in all)
and drew one bounded dark disc each
([metric:demo_cast_census/rerecorded-table@rerecorded#ruse_discs=2])
[domain:abilities/clove-rouse]. The first census saw two discs at once, a
batch launch [domain:abilities/clove-ruse-batch-launch]; here the player
placed one cloud per drop. `discs` finds each disc dark at its centre from the
drop to
[metric:demo_cast_census/rerecorded-discs@rerecorded#ruse1_life_s=14.9] and
[metric:demo_cast_census/rerecorded-discs@rerecorded#ruse2_life_s=14.9] s
after it, uncensored: the residual's windows end at the next drop, `discs`
does not.

**R5 and R6.** Blaze (013) draws a dark icon that leaves Phoenix trailing an
orange curve; the icon goes by +1 s and the curve stays. The residual's orange
component starts at
[metric:demo_cast_census/rerecorded-timing@rerecorded#blaze_013_onset_s=0.417]
s and lasts
[metric:demo_cast_census/rerecorded-timing@rerecorded#blaze_013_life_s=9.233]
s, uncensored, against the 8 s of [domain:abilities/phoenix-blaze-duration].
The wall builds as it travels, so the 8 s may count from its end. The Recon
Bolt (011) draws a teal ring with the bolt's crosshair icon at its centre
[domain:abilities/sova-recon-bolt-minimap-ring]; the residual's teal
component starts at
[metric:demo_cast_census/rerecorded-timing@rerecorded#recon_bolt_011_onset_s=0.817]
s and lasts
[metric:demo_cast_census/rerecorded-timing@rerecorded#recon_bolt_011_life_s=3.467]
s. Hunter's Fury (003) draws its teal line from
[metric:demo_cast_census/rerecorded-timing@rerecorded#hunters_fury_003_onset_s=-0.067]
s for
[metric:demo_cast_census/rerecorded-timing@rerecorded#hunters_fury_003_life_s=8.25]
s, turning between frames [domain:abilities/sova-hunters-fury-minimap-beam].

**R8.** Regrowth never moved the tray, so it has no montage. `sweep` asked
`reticle.ability_shapes` for Regrowth's ring on all
[metric:demo_cast_census/rerecorded-cache@fc02a2c1ac01#frames=638] cached
Skye frames. It finds
[metric:demo_cast_census/rerecorded-sweep@rerecorded#regrowth_runs=1] run,
from [metric:demo_cast_census/rerecorded-sweep@rerecorded#regrowth1_start_s=5.17]
to [metric:demo_cast_census/rerecorded-sweep@rerecorded#regrowth1_end_s=16.53]
s on [metric:demo_cast_census/rerecorded-sweep@rerecorded#regrowth1_frames=164]
frames, and
[metric:demo_cast_census/rerecorded-sweep@rerecorded#regrowth_runs_tray_unseen=1]
run that no tray cast explains. A crop sheet at 0.2 s steps shows the ring at
16.4 s and gone at 16.6 s. One run of 11 s may be one channel or three with
gaps under 0.5 s [domain:abilities/skye-regrowth-minimap-ring]; the player
later answered one [domain:abilities/skye-regrowth-channelled]. The fit took
about 4 s a frame, 43 minutes for this demo, mostly on the whole-widget
search that frames without the ring fall back to, so I swept no other demo.

**R4 and the casts that never came.** The tray fell on Pick-me-up and Not
Dead Yet only under the menu. The catalogue says Pick-me-up absorbs "a fallen
enemy that Clove damaged or killed" and Not Dead Yet acts "after dying"; a
solo range demo offers neither, which would explain it. Run it Back's and
Seekers' pips stay full to the end.

**R9.** The blind read calls nothing on
[metric:demo_cast_census/rerecorded-table@rerecorded#blind_nothing=6] of
[metric:demo_cast_census/rerecorded-table@rerecorded#read=15] casts: 40%,
inside the predicted 37.5-50%, but not 18-24, because 15 casts are not 48.
The residual calls nothing on
[metric:demo_cast_census/rerecorded-table@rerecorded#residual_nothing=1],
within the bar of 12. Its class agrees with the blind class on
[metric:demo_cast_census/rerecorded-table@rerecorded#agree_residual=3] of
[metric:demo_cast_census/rerecorded-table@rerecorded#residual_rows=15], and on
drawn against nothing on
[metric:demo_cast_census/rerecorded-table@rerecorded#agree_residual_drawn=10];
as in the first census, it says drawn almost everywhere and calls compact
icons `dark_disc`. The next drop cut
[metric:demo_cast_census/rerecorded-residual@rerecorded#end_next_cast=9] of
the fifteen residual windows. Every drawn cast showed its object by +1 s
([metric:demo_cast_census/rerecorded-table@rerecorded#drawn_by_1s=9] of
[metric:demo_cast_census/rerecorded-table@rerecorded#drawn_timed=9]).

### The blind read

The montages and the key work as in the first census, and I read all fifteen
before the key opened. The read is blind to the key, not to the tray, whose
glyphs name the slot. A flash hid the widget on two montages (002 and 009,
both Curveball). On two, the +8 s frame lies after the next drop and shows
that cast's object (008 shows the Recon ring, 011 the Fury line); I read those
frames as the next cast's.

### Questions for the player

Open these keyed montages first
(`<store>/analysis/demo-cast-census-rerecorded/montage/keyed_NNN.png`):

1. **keyed_004, Clove's second Ruse** (`0c6c52a65b9e`,
   `C:\Users\grant\Videos\2026-09-26 19-44-34.mp4`, 24.57 s). One new disc
   beside the first; by +8 s the first has gone. Is one disc per cloud what a
   match shows too?
2. **keyed_011, Sova's Recon Bolt** (`aab12e41dcfc`,
   `C:\Users\grant\Videos\2026-09-26 19-39-06.mp4`, 43.3 s). The ring shows
   at +1 and +2 s and is gone by +4 s. Is that the bolt's whole reveal?
3. **keyed_013, Phoenix's Blaze** (`6afc32cb46b4`,
   `C:\Users\grant\Videos\2026-09-26 19-41-03.mp4`, 7.08 s). The orange curve
   lasts 9.2 s. Does the 8 s count from the cast or from the wall's end?
4. **The protocol.** The tray shows each charge spent once and a cooldown
   count after it, against the manifests' `infinite-abilities` tag. Were
   infinite abilities on, and did you try three casts of each?
5. **Phoenix 53.25-54.5 s** (`6afc32cb46b4`). A white flash, then flames over
   the screen; the X pips stay full. Was that Run it Back?
6. **Pick-me-up and Not Dead Yet.** Can either be cast in the range without
   an enemy to absorb or a death?
7. **Skye 5.2-16.5 s** (`fc02a2c1ac01`,
   `C:\Users\grant\Videos\2026-09-26 19-42-54.mp4`). One Regrowth ring for 11
   s: one channel, or three?
8. **Sova's first Shock Bolt** (`aab12e41dcfc`, glow 16.67-29.57 s). Did you
   equip once and hold for 12.9 s, or equip more than once?

Then keyed_003 (Hunter's Fury's line turning), keyed_006 (Owl Drone: self's
portrait turns teal while the drone flies) and keyed_010 (Trailblazer, whose
marker stays within ~15 px of Skye).

### The player's answers (2026-09-26, later)

Asked the questions above the same evening, the player answered:

- **Question 3, Blaze.** The player guesses the 8 s may count from the wall
  completing, and had not thought about it. The census times the orange curve, the wall
  itself, not the cast icon that runs ahead of it; 9.2 s from the drop fits
  8 s from a wall that takes about a second to draw, and nothing confirms it
  [domain:abilities/phoenix-blaze-duration].
- **Question 4, the protocol.** Infinite abilities were not on. Three casts of each ability in one round is not possible, except over several
  rounds or by refreshing the abilities with cheats
  [domain:abilities/range-one-cast-per-round]; the manifests' tags had been
  corrected from the cooldown counters before the answer.
- **Question 5, the Phoenix flash.** The ult expired there. Decoded
  frames show no bar at 42.8 s, the cast's flaming hands with a full RUN IT
  BACK timer bar under the crosshair at 43.6 s, the bar nearly empty at 53.0
  s and the effigy at 53.4 s: the ult was cast at about 43.2 s and expired
  at 53.3 s, and the X pips never fell
  [domain:abilities/phoenix-run-it-back-expiry-flash]. So "never cast" above
  is wrong: the tray saw no drop. The player proposes reading that timer bar
  for cast times and ability names [domain:hud/ability-timer-bar]. The first
  census's Run it Back row (481336df9adb, montage 147, 34.5 s) sits where
  the pips fell, 4.7 s after a flame; which event that flame was is unknown.
- **Question 6.** Pick-me-up and Not Dead Yet cannot be cast in the range
  [domain:abilities/clove-c-and-x-need-a-target].
- **Question 7.** The 11 s Regrowth ring was one channel, held to give
  plenty of audio [domain:abilities/skye-regrowth-channelled]
  [domain:abilities/skye-regrowth-no-tray-drop].
- **Question 8.** One equip: the player toggled between the options for a
  while before the first Shock Bolt
  [domain:abilities/sova-bolt-charge-and-bounce]. The bolts landed right in
  front of Sova, and a Shock Bolt has no minimap indicator
  [domain:abilities/sova-shock-bolt-minimap-none].
- **Questions 1 and 2** (one Ruse disc per cloud in a match; whether the
  Recon Bolt ring is the whole reveal) are still open.

### The Trailblazer view tints the minimap (2026-09-26)

Labelling montage keyed_010, the player found the minimap rimmed in orange
with cyan patches spreading from +0.5 to +4 s: the view while Skye controls
Trailblazer is green, and the semi-transparent widget shows it through the
void and along the floor's edges [domain:hud/controlled-entity-view-tint].
On the minimap crop the green fraction rises from
[metric:demo_cast_census/drone-tint@fc02a2c1ac01#green_before=0.015] to
[metric:demo_cast_census/drone-tint@fc02a2c1ac01#green_during=0.643], and
the mean weight of `ability_shapes.teal`, the production detector behind the
ring and line fits, from
[metric:demo_cast_census/drone-tint@fc02a2c1ac01#teal_mean_before=0.0007] to
[metric:demo_cast_census/drone-tint@fc02a2c1ac01#teal_mean_during=0.0887],
so a fit during the drone would find teal everywhere. Sova's Owl Drone
([metric:demo_cast_census/drone-tint@aab12e41dcfc#green_during=0.004]) and
Tejo's Stealth Drone, whose view is brown
([metric:demo_cast_census/drone-tint@c0b63335e635#green_during=0.002]),
leave the teal weight under 0.005. The residual's "other hue" class and the
widget-drawn check read the same void. Frames were cut from the captures
with ffmpeg at the cached minimap rectangle, 1 s before the cast and 1 to 6
s after it; the tint is gated on nothing yet, and the montages the player
labels still carry it.

### The player's answers on the two open questions (2026-09-26, evening)

- **Ruse leaves one disc per cloud in matches too.** The disc is the
  indicator of the smoke's placement [domain:abilities/clove-rouse]. Why the
  nine match casts of the tray-object pass showed nothing stays open.
- **The Recon Bolt ring is the reveal range**, drawn round the bolt's icon
  [domain:abilities/sova-recon-bolt-minimap-ring]. The scan does not pass
  through walls; the enemies it sees on a pulse are shown through walls to
  everyone on Sova's team. Recon Bolt, Fade's Haunt and Tejo's Stealth Drone
  are the same pulse scan with different ranges
  [domain:abilities/pulse-scan-abilities], so one scan model with a range
  parameter serves all three, and the ring's radius names the device.

### A held-out icon pass from these casts (2026-10-04)

`prototypes/label_minimap_glyph_heldout.py` queues minimap frames at +1 s and
+3 s after each census cast whose ability the player did not answer as
drawing nothing or only a shape, plus one control frame per demo, and asks
the player to mark and name every ability icon. Its labels are held-out for
`prototypes/minimap_glyph_eval.py` and never tuned on; the module docstring
fixes the split and lists the controls.
