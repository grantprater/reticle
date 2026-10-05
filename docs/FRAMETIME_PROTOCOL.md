# Frame-time protocol: what reticle costs the game while it runs

Status: proposed, 2026-10-04. The player runs every step; agents never launch
the game, the Riot client or the tools below.

**Nothing is shown on screen during a match.** Reticle draws no overlay,
opens no window over the game and shows no conclusion while you play. In this
session the load harness only computes: it runs hidden, with no window, and
writes its log to the session folder as `NN_ARM.load.json`, with its printed
output in `NN_ARM.load.txt` and its errors in `NN_ARM.load.err.txt`. You read
the results after the session, with the game closed.

## The question, and the number that answers it

The player wants reticle to analyse during play and accepts about a 20% FPS
cost (the player, 2026-10-04 (chat)). Riot's rules bar showing conclusions
during a match, so the case to measure is silent computation beside the game
(`docs/WIN_PROBABILITY_RESEARCH.md` section 2, branch
`winprob-research-20261004`). This protocol runs reticle on the gaming PC
itself; that placement is the kit's choice, not something the player said.
One session of about 35 minutes measures the game's frame times under five
arms and picks the highest reticle load that fits the budget.

**Decided before the session** (`prototypes/frametime_results.py` applies it):

- **Reference arm:** the game alone (`base`). Every reticle arm also runs OBS,
  so this reference charges OBS's cost to reticle's 20%. That is the kit's
  choice; the player has not said which reference he meant. The results print
  the same rule against the game with OBS (`obs`) beside it, so he can pick.
- **Median FPS** is 1000 over the median frame time. **1% low FPS** is 1000
  over the 99th-percentile frame time. Both pool an arm's two repeats.
- **Cost** = 1 - arm / reference, for each of the two.
- **A reticle level passes** when both costs are at most 20% and both of its
  load logs show the harness kept pace: `pace` (stored seconds over wall
  seconds, a ratio over the whole run) at least 0.98, and the 95th
  percentile of call lateness (`lag_s.p95`) at most 1 s, since a run can keep
  the whole-run ratio while falling seconds behind in stretches. A level with
  a missing load log fails: nothing shows its load ran. So does a log whose
  `ready_s` (harness launch to its first call) exceeds 25 s, since PresentMon
  starts recording 30 s after the launch; the reason names the row to rerun.
- **Noise:** the two `base` repeats' median FPS may differ by at most 5%;
  above that the session is undecided, names no level, and repeats. A cost
  below that drift reads as within noise.
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
| `full` | the scan's minimap rates: ally icons and self position 15 Hz, minimap dark 4 Hz, pings 10 Hz, plus the rest of `light` |

**`full` is not the whole production scan.** `reticle scan` also runs the
roster reader, the combat report reader, the lineup reader, the ability shape
and icon readers and, when asked, the scoreboard reader. No level runs them,
so every level understates what a live copy of today's scan would cost.

It replays session `043bafca271a` (capture
`C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`) from its first round. Each
replay window mixes round time with a gap between rounds: the minimap crop
cache covers only round time, so the minimap readers idle in the gap while
the HUD readers keep running. A recording's load is therefore lighter on
average than the load inside a round. Which FPS figure, median or 1% low,
tracks the in-round load is untested: the slowest frames may come as well
from the round-end audio call or from OBS.

A live pass would also copy the screen; the harness reads its crops from disk
instead, and the OBS arm carries the capture-and-encode path. The harness's
own CPU figures on 2026-10-04, taken on a busy machine, are in the store under
`analysis/live-load-0.1.0-20261004/`; they are averages over a 120 s window
that includes a gap between rounds. They show `full` needs more than one core,
so on its one thread it falls behind and fails the pace rule by construction;
its arm still measures what one saturated Below Normal core costs the game.
The protocol runs each load with `--seconds 160 --max-wall 170`: a harness
that keeps pace ends after its 160 stored seconds, and one that falls behind
stops 170 s after its first call instead of running minutes past the
recording; its log then says `stopped_early` and counts only the stored
seconds it reached.

## Install (once, before the session)

1. **Get the kit.** It lives on branch `frametime-kit-20261004` until it
   merges. In an ordinary PowerShell window:

   ```powershell
   git -C C:\Users\grant\reticle fetch origin frametime-kit-20261004
   git -C C:\Users\grant\reticle worktree add C:\Users\grant\reticle-frametime origin/frametime-kit-20261004
   ```

   This makes a separate folder, `C:\Users\grant\reticle-frametime`, and
   leaves the main checkout's branch alone. The commands below run the kit
   from that folder with the main checkout's Python. If the folder already
   exists from an earlier try, update it instead of adding it:

   ```powershell
   git -C C:\Users\grant\reticle fetch origin frametime-kit-20261004
   git -C C:\Users\grant\reticle-frametime checkout --detach origin/frametime-kit-20261004
   ```

   If the branch has merged into `master` and the main checkout is on
   `master`, use `C:\Users\grant\reticle` as the kit folder instead.
2. **PresentMon 2.3.1**, Intel's open-source frame-time logger (it reads
   Windows' ETW present events; it injects nothing into the game). Download the
   console build `PresentMon-2.3.1-x64.exe` from the official releases page,
   https://github.com/GameTechDev/PresentMon/releases, into
   `C:\Users\grant\tools\presentmon\`. It needs an administrator PowerShell
   (or membership of the Performance Log Users group).
3. Confirm the flags this protocol uses exist in the build you downloaded:

   ```powershell
   C:\Users\grant\tools\presentmon\PresentMon-2.3.1-x64.exe --help
   ```

   Look for `--process_name`, `--output_file`, `--delay`, `--timed`,
   `--terminate_after_timed` and `--v1_metrics`. If `--v1_metrics` is absent,
   drop it from every command: the results reader also reads the 2.x
   `FrameTime` column.
4. **Fallback**, only if PresentMon records no VALORANT frames beside Vanguard
   (step 3 of the session checks): NVIDIA FrameView, which logs the same
   present-based CSV, https://www.nvidia.com/en-us/geforce/technologies/frameview/.
   Rename its CSVs to the names below.

## Fix the conditions

- **Nothing else heavy runs.** Stop `reticle scan`, Claude agents and any
  download for the whole session; close browsers. Note anything you cannot
  stop.
- **Same game settings in every arm:** the resolution, display mode and
  graphics preset you play with (you play on a 2560x1440 monitor
  [domain:capture/capture-resolution]; write the in-game resolution in the
  notes); **FPS limits off** ("Limit FPS Always" off), V-Sync off, NVIDIA
  Reflex as you play. A frame cap hides the cost until the game falls below
  it. Screenshot the video settings page once.
- **Same place and view:** a custom game, alone, on one map you name in the
  notes; stand at the same spot in attacker spawn, aim at the same landmark,
  and do not move during a recording. Re-aim between arms.
- **Same power state:** plugged in, the same Windows power plan, the same
  NVIDIA control-panel profile.
- **Warm up:** play 5 minutes before the first arm so shaders are compiled.
- **OBS arms** use your normal recording settings; record to the usual disk.

## The session (about 35 minutes)

Each arm takes 150 s: PresentMon waits 30 s for the arm to settle, then records
120 s. Each arm runs twice, mirrored, so warming drifts both ways equally:

| # | Arm | OBS recording | Reticle load |
|---|---|---|---|
| 01 | `base` | off | none |
| 02 | `obs` | on | none |
| 03 | `light` | on | `light` |
| 04 | `medium` | on | `medium` |
| 05 | `full` | on | `full` |
| 06 | `full` | on | `full` |
| 07 | `medium` | on | `medium` |
| 08 | `light` | on | `light` |
| 09 | `obs` | on | none |
| 10 | `base` | off | none |

1. Launch VALORANT, start the custom game, take your spot, warm up.
2. Open one **administrator** PowerShell window and paste these lines once.
   They name the tools and make the day's folder (change the date to today's):

   ```powershell
   $dir = 'C:\Users\grant\frametime\20261005'
   $kit = 'C:\Users\grant\reticle-frametime'
   $py  = 'C:\Users\grant\reticle\.venv\Scripts\python.exe'
   $pm  = 'C:\Users\grant\tools\presentmon\PresentMon-2.3.1-x64.exe'
   New-Item -ItemType Directory -Force $dir
   function Arm([string]$nn, [string]$arm, [string]$level) {
     $h = $null
     if ($level) {
       $h = Start-Process $py -PassThru -WindowStyle Hidden -RedirectStandardOutput "$dir\${nn}_$arm.load.txt" -RedirectStandardError "$dir\${nn}_$arm.load.err.txt" -ArgumentList "$kit\prototypes\live_load.py 043bafca271a --level $level --seconds 160 --max-wall 170 --out $dir\${nn}_$arm.load.json"
     }
     & $pm --process_name VALORANT-Win64-Shipping.exe --output_file "$dir\${nn}_$arm.csv" --delay 30 --timed 120 --terminate_after_timed --v1_metrics
     if ($h -and -not $h.WaitForExit(90000)) { $h.Kill(); "row ${nn}: the load overran the recording by 90 s and was stopped" }
     if ($h -and -not (Test-Path "$dir\${nn}_$arm.load.json")) { "row ${nn}: the load wrote no log; see ${nn}_$arm.load.err.txt, then rerun the row" }
     "row $nn done"
   }
   ```

   The harness, when a row has one, runs hidden and at Below Normal priority
   (it lowers itself); running it from an administrator window gives it no
   extra rights it uses.
3. **Check once (10 s):** run

   ```powershell
   & $pm --process_name VALORANT-Win64-Shipping.exe --output_file "$dir\00_check.csv" --timed 10 --terminate_after_timed --v1_metrics
   & $py "$kit\prototypes\frametime_results.py" --check "$dir\00_check.csv"
   ```

   The second line prints how many VALORANT frames the file holds and which
   frame-time column it read. If it says `no game frames`, use FrameView; if
   it says `no frame-time column`, PresentMon wrote columns this kit does not
   know: stop and send the line it printed. Leave the file where it is; the
   results reader skips it.
4. **For each row of the table, in order:** set OBS recording as the row
   says, then run the row's line and return to the game at once. Hold still
   until the window prints `row NN done` (about 150 s for a row with no load,
   about 3 minutes for a row with one). If it also prints `wrote no log`,
   rerun that row with the same line before going on.

   ```powershell
   Arm 01 base
   Arm 02 obs
   Arm 03 light light
   Arm 04 medium medium
   Arm 05 full full
   Arm 06 full full
   Arm 07 medium medium
   Arm 08 light light
   Arm 09 obs
   Arm 10 base
   ```

   The harness must start inside PresentMon's 30 s delay. The results reader
   fails a level whose log's `ready_s` exceeds 25 s and names the file; rerun
   that row with the same line (it overwrites the row's files), then read the
   results again.
5. Write `notes.txt` in the folder: the map, the spot, the in-game
   resolution, the OBS output settings, anything that ran that you could not
   stop, anything that happened mid-arm (a stutter, a notification).

Optional, beside each arm and not part of the decision: GPU load with
`nvidia-smi --query-gpu=timestamp,utilization.gpu,clocks.gr,temperature.gpu --format=csv -l 1 -f C:\Users\grant\frametime\20261005\NN_ARM.gpu.csv`
in a second window, with the day's folder and the row's `NN_ARM` in the file
name (installed with the NVIDIA driver; stop it with Ctrl+C).

## Read the results

After the session, with the game closed, in the same window (if you closed
it, open PowerShell and paste the four `$` lines of step 2 again first):

```powershell
& $py "$kit\prototypes\frametime_results.py" $dir --json "$dir\decision.json"
```

It prints one row per arm (frames, median FPS, 1% low FPS, p99 frame time,
both costs, the harness's pace) and the verdict, then the level the same rule
picks against the game with OBS. An agent then copies the folder into the
store as a new dated directory under `analysis/frametime/` and records the
verdict.

## What this does not measure

- The cost of copying the screen live (Windows.Graphics.Capture); OBS's
  arms bound the capture-and-encode path, the harness reads stored crops.
- The readers no level runs: roster, combat report, lineup, ability shape
  and icon, scoreboard.
- The load inside a round alone: each recording averages round time with a
  gap between rounds.
- The live log-mel extraction the audio witness would need; the harness
  scores stored features only, and its round-end call reads the whole
  session's features, an upper bound on a live per-round call.
- Fights, smokes and movement: a still view in a custom game measures the
  load's cost on a steady scene. A deathmatch repeat of `base` and the chosen
  level, after the decision, checks the cost in play.
