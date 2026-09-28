# The menu witness

`reticle menu SESSION|--all` asks the stored crop caches whether the game's
menu covers the HUD, per sample, and writes `events/menu_open` (`menu-0.1.0`).
It decodes no video. The owner is `reticle/menu.py` (`reticle ownership
menu-open`); the structures it fits are [domain:hud/menu-structure].

## What it fits

- **The tab strip**, in the `hud` cache at 2 Hz: one line of tab labels
  crossing `hud_roster`, `scoreline` and `hud_roster_enemy` at the same rows,
  with dark panel rows above and below. The line sits on y 26-36 in most
  captures and on y 53-63 in `4f207c0c4e39`, which draws the menu smaller and
  lower, so the fit searches for the rows.
- **The CLOSE SETTINGS button**, in the `minimap` cache's tray crop on the
  tray's 0.5 s grid: rows of one uniform grey through the screen centre whose
  edges agree from row to row, a button's width, dark beside it. Its fill is
  176 grey, or 232 under the pointer. A flash lights the tray to its edges and
  fails the edge test.

The first attempt read the tab strip at fixed rows and found it on one session
only; the second source showed the menu open on eight more, which is how the
second layout surfaced. Both fits now search.

## Results

Over the corpus the tab strip opens on
[metric:menu/witness@all-sessions#hud_open=542] of
[metric:menu/witness@all-sessions#hud_samples=87789] HUD samples and the
button on [metric:menu/witness@all-sessions#tray_open=290] of
[metric:menu/witness@all-sessions#tray_samples=62311] tray samples, on
[metric:menu/witness@all-sessions#sessions_with_open=36] of
[metric:menu/witness@all-sessions#sessions=58] sessions. Where both sources
sampled within 260 ms, the button agrees with
[metric:menu/witness@all-sessions#hud_open_tray_open=231] of
[metric:menu/witness@all-sessions#hud_open_tray_sampled=233] tab-strip
samples, and the tab strip with 231 of
[metric:menu/witness@all-sessions#tray_open_hud_sampled=241] button samples;
every disagreement inspected is a frame where the menu opens or closes. All
[metric:menu/witness@all-sessions#sheet_tab_hits_menu=46] tab-strip hits on a
random contact sheet show the menu. The agreement is consistency, not
accuracy: no player label scores the witness.

The readers that consult it:

- **Tray drops** (`ability_timeline.player_tray_casts`, `player-cast-0.7.0`):
  a drop at a covered instant is `menu_open`. The census's
  [metric:menu/census@demos#settings_drops=19] settings drops all read
  `menu_open` ([metric:menu/census@demos#menu_open_after=19]); before, all 19
  were refused only as `forced`, a reason that does not name the menu. On the
  match sessions [metric:menu/labels@all-sessions#menu_open_drops=40] drops
  become `menu_open`, [metric:menu/labels@all-sessions#menu_open_were_after_player_death=29]
  of them refused before as `after_player_death`; no accepted drop changes.
  The labelled casts pass
  [metric:menu/labels@all-sessions#passing_after=94] of
  [metric:menu/labels@all-sessions#labels=120], as before
  ([metric:menu/labels@all-sessions#labels_changed=0] changed).
- **The roster count** (`roster.resolve(menu=)`, `roster.refusals`):
  [metric:menu/roster@all-sessions#menu_rows=552] roster rows fall at menu
  instants; [metric:menu/roster@all-sessions#read_before=18] read a count
  before, among them three allies on `4f207c0c4e39` at 201.0 s, and
  [metric:menu/roster@all-sessions#read_after=0] after.
- **The minimap consumers** (`belief.absent_instants`,
  `round_entities.session_lifetimes`, `adjudication.smokes.tracks`):
  [metric:menu/minimap@all-sessions#menu_frames=1928] stored minimap frames
  fall at menu instants, [metric:menu/minimap@all-sessions#widget_drawn_true=360]
  of them passing `widget_drawn`; the consumers now treat all of them as
  unobserved. The stored `round_entity` and `smoke` rows were not rerun.

## Open

- The Trailblazer view [domain:hud/controlled-entity-view-tint] is not
  guarded; it needs its own witness.
- `adjudication.death` reads the stored roster counts directly and its board
  audit does not yet receive the witness.
- Widget-drawn at read time (`minimap.widget_drawn` inside the scan) is
  unchanged; the guard acts on the stored rows.
