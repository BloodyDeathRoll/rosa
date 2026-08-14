# Session Handoff — 2026-08-13 (session 26)

## Goal
Work the Dream overnight review's pipeline findings into the repo, then chase a
web bug: the satellite thumbnails on "Other nearby spots" and the home hero were
unreadable dark rectangles.

## Current State
- **All committed, pushed, deployed.** `main` = `a002eaa`. Working tree clean
  apart from this file.
- Production: https://rosa-rust.vercel.app (HTTP 200). Verified the fix actually
  shipped by pulling the prod bundle - the minified zoom constant reads `Ze=13`.
- Pipeline: 404 committed tests green, plus 12 Dream report tests. A full
  `run --all` on the Oracle box published 199/199 spots, 0 warnings, 0 errors.
- **The box has not yet pulled the pipeline commits** - it picks them up on the
  next cron cycle (02:20/08:20/14:20/20:20 UTC). Nothing to do, just know it.
- Dev server is running on 5173 with `--host`, started with `setsid` so it
  survives tool teardown.

## Active Files
- `pipeline/src/rosa_pipeline/publish.py` - leading local day exempt from the
  `_covers_day` completeness filter.
- `pipeline/src/rosa_pipeline/cli.py` - `_cmd_verify` fleet summary + non-zero
  exit when nothing scored; new `run --skill <path>`.
- `tools/dream-review/run-report-tests.sh` - **new.** Runs Dream's shipped tests
  with `pipeline/.venv/bin/python` + `PYTHONPATH=pipeline/src`.
- `web/src/components/MiniMap.tsx` - `Z` 15 -> 13. This was the actual map bug.
- `web/src/styles.css` - `.map-card-body` text-shadow, `.map-card-sub` colour,
  plus the user's own token pass (glow, tide fill, card alpha, primary).
- `web/src/pages/MapPage.tsx` - **unmodified**, identical to HEAD (the shade span
  was removed and put back).

## Changes Made This Session
1. **Dream review applied** (report 2026-08-13): `leading-day-never-dropped`
   (today could vanish from the payload and `current` slide to tomorrow),
   `verify-fleet-exit-code` (publish.sh's `|| echo "warn: skill measurement
   failed"` was dead code), and proposal 1 `run --skill` (unblocks the ceiling
   A/B that was deferred 2026-08-12 for want of exactly this tool). Split into
   three atomic commits by staging each report diff into the index separately.
2. **Fleet smoke on the VM.** Ran from `~/rosa` with the changed modules overlaid
   via `PYTHONPATH=/tmp/rosa-smoke-src`, output to `/tmp` - live checkout,
   `data/out` and cron untouched, verified afterwards. `ceiling_source` came back
   `measured` at all 199 spots, so `--skill`'s default is bit-identical to before.
3. **Map thumbnails fixed by changing the zoom, not the overlay.** z15 frames
   ~1.2 km; spots whose coordinate sits offshore (Ollie's Point, Witch's Rock)
   had no coastline in frame at all. z13 is ~4.9 km and puts headland, bay and
   beach in the card. Proved by compositing the exact card window for four spots
   at z12-z15 against live tiles before touching any code.
4. **Text-shadow on the card readout**, because z13 delivers bright sand and
   rooftops where z15 delivered dark canopy, and white-on-sand is the case that
   fails. `.map-card-sub` moved off mid-grey `#a8a29e` for the same reason.
5. **Dream left untouched.** `bin/review-apply.sh` reverted, the `.applied`
   ledger lines and the playbook bullet reverted, and the `__pycache__` /
   `.pytest_cache` my test runs dropped in the report tree removed.

## Failed Attempts
- **The first map diagnosis was wrong.** I concluded the `.map-card-shade`
  gradient was hiding the imagery, and it wasn't - I tested on `beit-yanai`,
  which is beach-front and therefore one of the spots the real bug cannot
  affect. Test a Costa Rica spot (`ollies-point`, `witchs-rock`) before
  believing anything about these cards.
- **Softening the gradient** (top stop 50% -> 18% teal): rejected, "looks bad".
- **Removing the gradient entirely**: images finally visible, but at z13 the
  white type sat unreadable on bright sand. That is why the text-shadow exists -
  it is not decoration, and removing it will regress legibility.
- **Gradient is back** at the user's values (`--tide-fill`, 0.4 floor).
- **Local `run --all` cannot complete on this machine.** Dies with
  `httpx.ConnectTimeout: _ssl.c:1015 handshake timed out` on `api.open-meteo.com`
  partway through batch 2 of 4, reproducibly. curl and standalone httpx to both
  hosts work fine. `fetch_many` has **no retry**, so one flaky connect aborts the
  whole sweep and discards completed batches - a real fragility, flagged and not
  fixed. Use the VM for fleet smokes.
- **`pgrep -f "<pattern>"` self-matches the polling shell**, whose command line
  contains the pattern. It reported the VM run as RUNNING for 15 minutes after it
  had finished. Match on `ps -eo cmd | grep "[r]osa_pipeline"` instead.
- **Coverage probe using the payload's `hours` array was inconclusive** - `hours`
  is already filtered to the future, so it cannot reconstruct the pre-filter set
  `_covers_day` saw. It cannot tell you whether the leading-day fix fired.
- **Headless Firefox will not run here** (snap confinement); every invocation
  timed out. Chrome only.
- **Chrome screenshots the splash** unless you pass `--virtual-time-budget=9000`
  *together with* `--force-prefers-reduced-motion` (the latter skips the particle
  loops that make the budget hang - the gotcha from session 25 is real).
- **CDP `Page.captureScreenshot` `clip` is in page-absolute coordinates**, not
  viewport - add `scrollX`/`scrollY` and pass `captureBeyondViewport: true`, or
  you screenshot the top of the document.
- **`nohup npm run dev &` gets killed by the Bash tool teardown.** Use
  `setsid nohup ... < /dev/null &`.
- **`npm run deploy` breaks the running dev server** (sync-data `rm -rf`s
  `public/data`), surfacing as `JSON.parse: unexpected character at line 1
  column 1`. Restart vite after every build. Bit twice today.

## Next Step
1. **The leading-day fix is unproven in practice.** It is correct and tested, but
   nothing shows how often it fires live. Run the same-input A/B now that
   `--skill` exists: `run --all --capture F` once on the box, then replay
   `run --all --fixtures F` with and without `publish.py`'s exemption and diff
   the day lists. ~10 min on the VM.
2. **Dream's ledger was deleted at the user's instruction**, so tonight's
   reviewer has no record these three were applied and may re-file them. Expect
   that; do not re-apply blindly.
3. **`docs/SESSIONS.md` has no entry for sessions 19-26**, and `docs/UI.md` still
   does not describe the floating nav, bottom glow, desktop frame, sea rating
   scale, or now the z13 map framing. Both overdue.
4. Optional, flagged not done: the `Poor`/`Epic` pill on the map cards is
   low-contrast over bright tiles; and `.map-card.noimg` has no CSS rule at all,
   so a card outside `MapPage.tsx`'s `IMG_WINDOW` (focus +/- 2) is bare `#22262f`
   under the gradient.
