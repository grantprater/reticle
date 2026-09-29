# The spike carrier on the Iso capture

On the Iso capture `4f207c0c4e39` (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`)
`reticle spike` (`spike-0.1.0`) saw a carrier on
[metric:iso_spike/stored-0.1.0@4f207c0c4e39#rounds_carrier_seen=18] of
[metric:iso_spike/stored-0.1.0@4f207c0c4e39#rounds=22] rounds. The capture's
widget is a variant (`widget_frame`): 1.18x the baked Split static, drawn
turned 180 degrees before 1192767 ms and upright after, and `RoiCache.samples`
resamples it into the baked frame. The resample turns the map back, and the
icons with it: the map turns on the screen and the icons do not
[domain:minimap/upright-icons-on-turned-map]. `spike-0.1.0` read every dropped
glyph of the turned half as carried. `spike-0.2.0` turns the glyph's
orientation test and the carrier's offset with the placement, and the carrier
falls to [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#rounds_carrier_seen=10]
rounds, the ten our team attacked.

The work decoded no video: the stored `spike`, `spike_carrier`, `rounds` and
`self_icon` rows and a few dozen frames of the crop cache.

## Per round

The two channels, per round, from the stored `spike-0.1.0` rows:

| rounds | widget | roster marker | carried glyph | dropped glyph | disagreements |
|---|---|---|---|---|---|
| 1-12 | turned 180 | none | 8 rounds, 1-7 frames each | none | `glyph_without_marker` on every carried frame; `no_carrier_before_plant` on rounds 2 and 3 |
| 13-22 | upright | every round | every round | 6 rounds | `marker_without_glyph` 18, `loss_unwitnessed` 1 |

The roster marker never passes through the widget transform. It read no slot
before 1192767 ms and
[metric:iso_spike/stored-0.1.0@4f207c0c4e39#second_half_marker_frames=479]
frames after it: our team defended the first half and attacked the second.
Every first-half carried glyph
([metric:iso_spike/stored-0.1.0@4f207c0c4e39#first_half_carried_frames=31]
frames) stood without a marker, and the first half stored no dropped glyph at
all. On `b7d24102a6f6`, a Split session with the baked placement, the defending
half stores dropped glyphs and never a carried one, and the carrier appears on
[metric:iso_spike/baseline-rerun-0.2.0@b7d24102a6f6#rounds_carrier_seen=7] of
[metric:iso_spike/baseline-rerun-0.2.0@b7d24102a6f6#rounds=19] rounds, all in
its attacking half.

## The first failure

The glyph channel failed first, on the turned half. The contact sheet
`~/reticle-store/analysis/iso-spike-20260929/iso_rot_carried.png` shows eight
first-half frames that `spike-0.1.0` read carried; each row holds the raw
capture crop, the resampled crop with the baked static's edges drawn over it,
and the glyph zoomed as the reader met it and turned back upright. On the
screen every glyph points its base down, a dropped spike; the resampled crop
points it base up. Refitted upright,
[metric:iso_spike/stored-0.1.0@4f207c0c4e39#sampled_upright_dropped=8] of
[metric:iso_spike/stored-0.1.0@4f207c0c4e39#sampled_first_half_carried=8] read
dropped, each at a higher correlation than the turned fit.

The instrument is sound. The baked static's edges lie on the walls of the
resampled crop in both halves, so the transform places the widget correctly;
it only turns icons that the game never turns.
`iso_unrot_carried.png` beside it shows four upright-half carried glyphs, each
at the lower left of an icon and matched by a roster marker.

## The fix

`spike.glyph_fits`, `spike.on_glyph` and `spike.carrier_offset` take the
placement's `rotation` (default 0). At 180 the dropped template points base up
in the baked frame and the carrier sits below and to the left of its glyph.
`cli._spike_session` reads the rotation per frame from `WidgetFrame.at` and
each `spike` row stores it; `adjudication.spike_carrier.frame_state` passes the
stored rotation to `carrier_offset` (`spike-carrier-0.2.0`).

Rerun in process over the crop cache and compared with the stored rows:

- `4f207c0c4e39`: [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#frames_changed=44]
  of [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#frames=1655] frames changed,
  none after 1192767 ms;
  [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#carried_to_dropped=31] turned
  from carried to dropped and the rest changed only rejected candidates.
  `glyph_without_marker` fell to
  [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#glyph_without_marker=0] and
  `no_carrier_before_plant` to
  [metric:iso_spike/rerun-0.2.0@4f207c0c4e39#no_carrier_before_plant=0].
- `b7d24102a6f6`: [metric:iso_spike/baseline-rerun-0.2.0@b7d24102a6f6#frames_changed=0]
  of [metric:iso_spike/baseline-rerun-0.2.0@b7d24102a6f6#frames=1394] frames
  changed, and the carrier check reproduced its stored coverage row.

The rerun wrote nothing to the store. `reticle spike 4f207c0c4e39` after the
merge replaces the stored rows; every other session reads the same fits and
needs only a restamp.

## The self icon

The self icon shares the cause in part. Its portrait is drawn upright and the
resample turns it over on the first half. Over the stored scored frames the
art scores rank Iso
[metric:iso_spike/self-icon-halves@4f207c0c4e39#rot180_iso_rank=19]th on the
[metric:iso_spike/self-icon-halves@4f207c0c4e39#rot180_frames=171] turned
frames and [metric:iso_spike/self-icon-halves@4f207c0c4e39#rot0_iso_rank=2]nd on
the [metric:iso_spike/self-icon-halves@4f207c0c4e39#rot0_frames=82] upright
ones, where Astra leads
([metric:iso_spike/self-icon-halves@4f207c0c4e39#rot0_top_mean=1.807] against
[metric:iso_spike/self-icon-halves@4f207c0c4e39#rot0_iso_mean=1.694]). So the
turned half drags the witness's mean down, and a second cause keeps even the
upright half from naming Iso. The resample's 1/1.18 shrink of the portrait is
the first suspect; nothing here tests it.

## Open

- `self_icon` and `minimap.AllyIconReader` still call `glyph_fits` and
  `on_glyph` unturned, so on the turned half the refusal of a fit on the glyph
  still reads a dropped glyph as carried. Wiring the rotation there restamps
  `self_icon` and `ally_icon`.
- `self_icon` scores the turned portrait as it arrives; turning it upright and
  testing the shrink is its own change.
- No turned-half round has a true carried glyph, so the turned carrier offset
  rests on synthetic tests (`tests/test_spike.py`).
