# Session Handoff — 2026-08-04 (session 17)

## Goal
Run the first real batch of the satellite pin-verification loop: build a queue, judge the
tiles by eye, apply approved moves with their bathy/horizon consequences. Costa Rica's 12
weakest-authority (`approx`) pins were the batch.

## Current State
- **12 spots judged, 10 moved, 1 kept, 1 reverted. Nothing committed yet.** Working tree is
  dirty with the full change set (see Active Files).
- **372 pipeline tests pass.** `queue.py --status` now reads **80 verified / 119 outstanding**
  (was 69/130). Costa Rica went 0 → 11 verified.
- **Eleven of the twelve `approx` pins were sitting in open water.** This is a property of the
  tag, not noise — expect the same on the other regions' `approx` spots.
- **`queue.py --mark` has NOT been run.** The batch is not recorded as judged, so it will come
  back if someone builds another batch. `.state/judged.txt` is still empty.
- **The before/after pipeline A/B is COMPLETE — all 6 spots, and the moves are safe.** Three
  are **bit-identical** old vs new (dominical, esterillos, manuel-antonio); three shift
  slightly, none meaningfully:

  | spot | max H | mean rating |
  |---|---|---|
  | marbella | 2.00 → 1.80 m | 83.4 → 82.3 |
  | matapalo-osa | 1.90 → 1.80 m | 82.3 → 82.3 |
  | nosara-guiones | 1.80 → 1.90 m | 80.3 → 80.5 |

  marbella is the only one that *should* differ (19 km move = different coastline). matapalo-osa
  was re-run after its `shore_normal` re-cut and gave the identical result, so its number is
  trustworthy. **No spot collapsed or spiked — nothing here blocks the commit.**
- **`docs/SESSIONS.md` and `docs/OPEN-ITEMS.md` are NOT updated.** Session 17 needs an entry.
- `docs/SPOT-DB.md` still says "69/199 pins settled as of 2026-08-04" on the sat-verification
  line — **now wrong, should be 80/199.** Not yet fixed.
- Session 16's list is untouched: VM cycle unconfirmed, ISRAMAR email unsent, Portugal
  lead-time archive still accruing, privacy page still inaccurate.

## Active Files
- `data/spots/costa-rica.yaml` — 12 spot lines changed (10 moved pins, 1 keep retagged,
  1 reverted-with-note), plus two `shore_normal` corrections.
- `data/spots/derived/bathy/*.json` — 10 profiles re-cut. `ollies-point.json` restored from HEAD.
- `tools/spot-verify/satverify.html` — **bug fix**: crosshair and label were invisible.
- `tools/spot-verify/JUDGING.md` — NEW (untracked). `python` → `python3`; `keep` now retags.
- `tools/spot-verify/queue.py` — NEW (untracked), unchanged this session.
- `docs/SPOT-DB.md` — geocoding line rewritten.
- `.gitignore`, `docs/spot-mapping-approach.md` — carried in from the prior session, untouched here.

## Changes Made This Session
1. **Fixed the tile renderer before anything else.** `.xh` and `#lbl` were at `z-index: 9`,
   under Leaflet's tile panes (200-700), so **every tile this tool has ever shot had an
   invisible crosshair and no label**. Raised to 900. The first render came back bare; that is
   the symptom to recognise.
2. Built the batch, rendered at z16, then **re-rendered wide (z13/z10) for anything whose
   coastline was out of frame**, proposed a coordinate, and **re-rendered at z16 to confirm it**
   before proposing it. Six spots needed two iterations. Do this — a z13 eyeball alone put four
   pins in the wrong place on the first pass.
3. Tile geometry, measured: at z16 a 640 px tile spans **0.01373° lon / 0.01353° lat** (~1.5 km),
   i.e. 2.146e-5 °lon per px. **JUDGING.md's "≈0.0055° top-to-bottom" is wrong by 2.5x** — that
   is one 256 px tile, not the 640 px shot. Not yet corrected in the doc.
4. **`ollies-point`: move applied, then REVERTED.** GEBCO's ~450 m cell reads the headland as
   dry land, so a pin on the point cut a profile with **no clean seaward bearing at any of 16
   bearings tested**. The old pin was clean (30 m nearshore). Its yaml note already said "coord
   nudged seaward off the headland" — that was deliberate. Left at its original coordinate,
   tagged `approx`, reason written into the note.
5. **Two `shore_normal` corrections**, both forced by their moved pin, both chosen by sweeping
   bearings against GEBCO (`bathy --all --spots-dir <synthetic> --out <tmp>`) and taking the one
   with a clean wet march — not by eye:
   - `boca-barranca` 205 → **270** (old ray clipped the spit: 3 land samples, -13 m nearshore).
   - `matapalo-osa` 223.4 → **210** (march was starting at 92 m; now 10 m). `offshore_bearing`
     left at 223.4, still inside the 45° guard.
6. **Swell windows: all HOLD.** Every derived window differs from its yaml value, but no yaml
   window excludes its own shore normal, so `docs/SPOT-DB.md`'s adoption rule says hold.
   `marbella` is the one to revisit — its window was authored for a pin 19 km away.
7. **Google Geocoding API enabled** (user did the console work). Two distinct `REQUEST_DENIED`
   messages, now documented: *"not activated"* = the project, *"key is not authorized"* = the
   key's API restriction. Both had to be fixed, in that order.
8. **`keep` now retags `sat-verified`** (JUDGING.md changed, `mal-pais` applied). Previously a
   verified-correct pin stayed labelled `approx` and read as unchecked forever.

## Failed Attempts
- **Claimed the moved pins "contaminated" the bathymetry and nearly reverted the batch over it.
  Wrong.** `DepthProfile.wet_depths_deep_to_shallow()`
  (`pipeline/src/rosa_pipeline/bathymetry.py:87`) **drops land points** before the physics
  march. `land_samples > 0` is not by itself a defect — several untouched fleet spots (aoshima,
  arugam-bay, aver-o-mar, ba-a) already carry it. The metric that matters is the **shallowest
  wet depth**, and there 8 of 10 moves *improved*: marbella 119 m → 3 m, manuel-antonio 17 → 4,
  ostional 10 → 3. Only matapalo-osa regressed, and a bearing change fixed it.
  **Check shallowest wet depth, not land_samples.**
- `test_committed_profiles_reach_open_water` only checks the **deep end** of a profile, so it
  passes on one whose first 1 km is dry land. It will not catch this class of problem.
- A synthetic sweep yaml built from scratch fails with `KeyError: 'ideal'` — the loader needs
  the `&pac` / `&carib` anchors. Build sweep files by splitting the real yaml on `spots:` and
  reusing its header verbatim.
- Six sequential `rosa-pipeline run` calls blew the 10-minute Bash timeout (~2.5 min each).
  Backgrounding the remaining four worked (exit 0) but took ~20 min, during which its output
  file stayed empty — **an empty output file is not evidence the job died.** Run these in the
  background and wait for the completion notification.
- `python` is not on this box (`exit 127`). Only `python3`.
- `mcp__plugin_vercel_vercel__list_projects` still returns `[]` (carried from session 16).

## Next Step
1. **Mark and commit — the A/B is done and clean, nothing is blocking this.**
   ```
   python3 tools/spot-verify/queue.py --mark tools/spot-verify/work/2026-08-04/queue.json
   ```
   `--mark` records **all 12** including the reverted `ollies-point`, so it will not resurface
   in a future batch even though it is unresolved. Decide whether that is wanted first.
2. **Update `docs/SPOT-DB.md`**: "69/199 pins settled" → **80/199**.
3. **Fix JUDGING.md's zoom-16 geometry line** (change 3 above) — off by 2.5x, it will mislead
   the next judging pass.
4. Append a **session 17** entry to `docs/SESSIONS.md`; update `docs/OPEN-ITEMS.md`.
5. Commit as `data:` (spot moves). Commit means commit + push + deploy — **the VM pulls on its
   next cycle and these forecasts change**, so land it deliberately.
6. Next batch: Costa Rica's remaining 14, then Israel's 28.

## Constraints carried forward
- **Never import competitor spot data.** Satellite + geocoder + local knowledge only.
- **Neither geocoder is trustworthy alone on surf names** — Google put "Ollie's Point" 354 km
  away on a same-named inland Potrero Grande; Nominatim placed Marbella within 140 m. Always
  cross-check against a tile.
- `horizon` and the cam tools **report, never apply**.
- Session 15/16 items still open: VM cycle unverified, ISRAMAR email unsent, privacy page
  inaccurate by explicit user decision (re-offer before public launch), Open-Meteo quota watch.
