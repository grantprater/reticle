# Frame-time protocol: what reticle costs the game while it runs

Status: proposed, 2026-10-04. The player runs every step; agents never launch
the game, the Riot client or the tools below.

## The question, and the number that answers it

The player wants reticle to analyse during play on the same PC and accepts
about a 20% FPS cost (the player, 2026-10-04 (chat)). Riot's rules bar showing
conclusions during a match, so the case to measure is silent computation
beside the game (`docs/WIN_PROBABILITY_RESEARCH.md` section 2, branch
`winprob-research-20261004`). One session of about 30 minutes measures the
game's frame times under five arms and picks the highest reticle load that
fits the budget.

**Decided before the session** (`prototypes/frametime_results.py` applies it):

- **Reference arm:** the game alone (`base`). Costs against the game with OBS
  (`obs`) print beside, for information.
- **Median FPS** is 1000 over the median frame time. **1% low FPS** is 1000
  over the 99th-percentile frame time. Both pool an arm's two repeats.
- **Cost** = 1 - arm / reference, for each of the two.
- **A reticle level passes** when both costs are at most 20% and its load log
  shows the harness kept pace (`pace` at least 0.98; below that it did not
  apply its level's load).
- **Noise:** the two `base` repeats' median FPS may differ by at most 5%;
  above that the session is undecided and repeats. A cost below that drift
  reads as within noise.
- **The answer** is the highest level that passes: `light`, `medium` or
  `full`, or none.

## The load: `prototypes/live_load.py`

The harness replays a stored match's crop cache through the readers a live
pass would run, at the capture's own pace, at Below Normal priority on one
thread, and writes nothing to the store. Levels (rates in the harness's
`LEVELS`):

| Level | Readers |
|---|---|
| `light` | HUD and killfeed 2 Hz, ally icons 2 Hz, ability tray 2 Hz, the audio witness at each round end |
| `medium` | `light`, with ally icons and the self position at 5 Hz |
| `full` | today's scan rates: ally icons and self position 15 Hz, minimap dark 4 Hz, pings 10 Hz, plus the rest of `light` |

It replays session `043bafca271a` (capture
`C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`) from its first round. A live
pass would also copy the screen; the harness reads its crops from disk
instead, and the OBS arm carries the capture-and-encode path. The harness's
own CPU figures on 2026-10-04, taken on a busy machine, are in the store under
`analysis/live-load-0.1.0-20261004/`. They show `full` needs more than one
core, so on its one thread it falls behind and fails the pace rule by
construction; its arm still measures what one saturated Below Normal core
costs the game.

## Install (once, before the session)

1. **PresentMon 2.3.1**, Intel's open-source frame-time logger (it reads
   Windows' ETW present events; it injects nothing into the game). Download the
   console build `PresentMon-2.3.1-x64.exe` from the official releases page,
   https://github.com/GameTechDev/PresentMon/releases, into
   `C:\Users\grant\tools\presentmon\`. It needs an administrator PowerShell
   (or membership of the Performance Log Users group).
2. Confirm the flags this protocol uses exist in the build you downloaded:

   ```powershell
   cd C:\Users\grant\tools\presentmon
   .\PresentMon-2.3.1-x64.exe --help
   ```

   Look for `--process_name`, `--output_file`, `--delay`, `--timed`,
   `--terminate_after_timed` and `--v1_metrics`. If `--v1_metrics` is absent,
   drop it: the results reader also reads the 2.x `FrameTime` column.
3. **Fallback**, only if PresentMon records no VALORANT frames beside Vanguard
   (step 3 of the session checks): NVIDIA FrameView, which logs the same
   present-based CSV, https://www.nvidia.com/en-us/geforce/technologies/frameview/.
   Rename its CSVs to the names below.

## Fix the conditions

- **Nothing else heavy runs.** Stop `reticle scan`, Claude agents and any
  download for the whole session; close browsers. Note anything you cannot
  stop.
- **Same game settings in every arm:** your normal resolution (2560x1440),
  display mode and graphics preset; **FPS limits off** ("Limit FPS Always"
  off), V-Sync off, NVIDIA Reflex as you play. A frame cap hides the cost
  until the game falls below it. Screenshot the video settings page once.
- **Same place and view:** a custom game, alone, on one map you name in the
  notes; stand at the same spot in attacker spawn, aim at the same landmark,
  and do not move during a recording. Re-aim between arms.
- **Same power state:** plugged in, the same Windows power plan, the same
  NVIDIA control-panel profile.
- **Warm up:** play 5 minutes before the first arm so shaders are compiled.
- **OBS arms** use your normal recording settings; record to the usual disk.

## The session (about 30 minutes)

Make a folder for the day, for example `C:\Users\grant\frametime\20261005\`.
Each arm takes 150 s: PresentMon waits 30 s for the arm to settle, then records
120 s. Each arm runs twice, mirrored, so warming drifts both ways equally:

| # | Arm | OBS recording | Reticle load |
|---|---|---|---|
| 01 | `base` | off | none |
| 02 | `obs` | on | none |
| 03 | `light` | on | `--level light` |
| 04 | `medium` | on | `--level medium` |
| 05 | `full` | on | `--level full` |
| 06 | `full` | on | `--level full` |
| 07 | `medium` | on | `--level medium` |
| 08 | `light` | on | `--level light` |
| 09 | `obs` | on | none |
| 10 | `base` | off | none |

1. Launch VALORANT, start the custom game, take your spot, warm up.
2. Open two PowerShell windows: one administrator window in
   `C:\Users\grant\tools\presentmon`, one ordinary window in
   `C:\Users\grant\reticle`.
3. **Check once (10 s):** in the administrator window run

   ```powershell
   .\PresentMon-2.3.1-x64.exe --process_name VALORANT-Win64-Shipping.exe --output_file C:\Users\grant\frametime\20261005\00_check.csv --timed 10 --terminate_after_timed --v1_metrics
   ```

   and confirm the CSV has rows. If it is empty, use FrameView.
4. **For each row of the table, in order** (`NN` and `ARM` from the row):
   1. Start or stop OBS recording as the row says.
   2. If the row has a reticle load, start it in the ordinary window:

      ```powershell
      .\.venv\Scripts\python.exe prototypes\live_load.py 043bafca271a --level LEVEL --seconds 160 --out C:\Users\grant\frametime\20261005\NN_ARM.load.json
      ```

   3. At once, in the administrator window:

      ```powershell
      .\PresentMon-2.3.1-x64.exe --process_name VALORANT-Win64-Shipping.exe --output_file C:\Users\grant\frametime\20261005\NN_ARM.csv --delay 30 --timed 120 --terminate_after_timed --v1_metrics
      ```

   4. Hold still until PresentMon exits (150 s). Wait for the harness to
      print its JSON before the next row. Its setup must finish inside
      PresentMon's 30 s delay: if the load log's `setup_s` exceeds 25, rerun
      the row.
5. Write `notes.txt` in the folder: the map, the spot, the OBS output
   settings, anything that ran that you could not stop, anything that
   happened mid-arm (a stutter, a notification).

Optional, beside each arm and not part of the decision: GPU load with
`nvidia-smi --query-gpu=timestamp,utilization.gpu,clocks.gr,temperature.gpu --format=csv -l 1 -f C:\Users\grant\frametime\20261005\NN_ARM.gpu.csv`
(installed with the NVIDIA driver; stop it with Ctrl+C).

## Read the results

```powershell
.\.venv\Scripts\python.exe prototypes\frametime_results.py C:\Users\grant\frametime\20261005 --json C:\Users\grant\frametime\20261005\decision.json
```

It prints one row per arm (frames, median FPS, 1% low FPS, p99 frame time,
both costs, the harness's pace) and the verdict. An agent then copies the
folder into the store as a new dated directory under `analysis/frametime/`
and records the verdict.

## What this does not measure

- The cost of copying the screen live (Windows.Graphics.Capture); OBS's
  arms bound the capture-and-encode path, the harness reads stored crops.
- The live log-mel extraction the audio witness would need; the harness
  scores stored features only, and its round-end call reads the whole
  session's features, an upper bound on a live per-round call.
- Fights, smokes and movement: a still view in a custom game measures the
  load's cost on a steady scene. A deathmatch repeat of `base` and the chosen
  level, after the decision, checks the cost in play.
