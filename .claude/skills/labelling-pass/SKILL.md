---
name: labelling-pass
description: Build or run a tool that asks the player for ground truth — a frame labeller, a candidate classifier, a mask painter. Use when a perceptual question resists derivation, or before any measurement that needs labels to be scored at all. Carries the control layout every labeller in this repo shares, the file format, and the lessons each one learned by getting it wrong.
---

# Labelling Pass — Core Mechanics

## Trigger
Use on **first perceptual failure** (not fifth), or when a channel **cannot be scored at all** (no ground truth exists).

## Before Writing Code
1. Ask player: *what things can actually appear here?* — get the class list first
2. Verify the sampling population (e.g., `segment` calls buy phase "active" → 38% empty frames)

## Control Orthodoxy (every labeller shares these)
| Key | Action |
|-----|--------|
| `U` | unsure — recorded, kept OUT of scoring |
| `A` | back one |
| `Q` / `ESC` | save and quit |
| Right-click | undo last mark (click tools) |
| `SPACE` / `D` | save and advance (click tools) |
| `N` | nothing here, advance (click tools) |

- **Classes = digit keys** when "which of these" (`label_icon_agent`, `label_dynamic`)
- **Classes = modifier+click** when "mark every one" (`label_minimap`, `label_enemies`)
- **Always include escape hatch** (e.g., `7 = other`); `0 = nothing` is a claim, not a default

## File Format
- Append-only JSONL at `<store>/labels/<kind>/<session>.jsonl`
- **Last row for a key wins** (enables `A`-then-reanswer)
- Store: answer + `(t_ms, x, y)` to find pixel again (features recomputed)
- Record `by` (who answered) and `compared_against_derived` if shown derived mask
- **Resumable**: load existing, skip answered, safe to quit mid-run

## Never Seed
Seeding makes labeller skip seeded items → scoring clustering against itself. Start blank; offer flash key (`m` in `paint_map.py`) for comparison only.

## The Tile ≠ The Object
A 36px crop holds multiple overlapping things. Ring the candidate in **every panel** and ask about **the ringed thing**, never "what is in this tile".

## Tk Gotchas
- `root.bind("bracketleft", ...)` binds 11-key sequence; use `"<bracketleft>"` (angle brackets for named keysyms)
- Don't re-encode full PNG on mouse-motion — draw cheap feedback on canvas, recomposite on `ButtonRelease`
- Context panel resizing 1080p→tile height is unreadable; crop to what matters
- `PhotoImage` needs a reference kept or GC blanks it

## During Pass
- Restart only for changes affecting data produced (missing class key = yes; blurry panel = no)
- Read file as it fills (flushed per row) — interim analysis at 154/250 surfaced host-span feature

## After Pass
- Write scoring as **prototype** (e.g., `dynamic_eval.py`: takes session, recomputes features, prints operating points)
- Check: **does ground truth come from same population as thing being filtered?** (55 enemy icons ≠ ability glyphs)
