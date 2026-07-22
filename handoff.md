# Session Handoff — 2026-07-22 (icons / branding polish)

> This was the **branding/UI-polish** track in `web/`. A separate **accuracy/Stage-2
> bathymetry** session shares this same working tree — its uncommitted `shore_normal`
> work in `pipeline/` leaves the pipeline **non-loadable** (see Coordination Hazard).
> Do NOT touch `pipeline/` or `data/spots/derived/` here.

## Goal
Refresh the app's brand marks (new wave/rose artwork the user redrew), wire the About
pages + branded loading splash, and ship it. Also: keep the Oracle A1.Flex grabber alive.

## Current State — DONE, committed & pushed & deployed
- **New icon artwork.** User redrew `web/public/favicon.svg`, `icon.svg`, `icon-maskable.svg`
  (same brand red `#d82619`, new path art; `icon.svg` cleaned of the old hidden wave strokes).
  Every icon/logo surface references these three by path, so the new art propagated with **no
  code change**: browser favicon (`icon.svg`), iOS `apple-touch-icon` + PWA manifest
  (`icon-maskable.svg` maskable + `icon.svg` any), header brand mark & About hero logo & splash
  mask (`favicon.svg`). Verified: clean `npm run build`, all three SVGs ship to `dist/`,
  manifest points at them.
- **Branded splash + About pages.** `index.html` splash (bg `splash.jpg`, favicon-masked wave
  mark, "rosa" wordmark, min-1s hold); About page renders `/about/{how,terms,privacy}.jpg`.
  New assets committed: `web/public/splash.jpg`, `web/public/about/how.jpg|terms.jpg|privacy.jpg`.
- **Touched:** `web/index.html`, `web/src/pages/AboutPage.tsx`, `web/src/pages/SettingsPage.tsx`,
  `web/src/styles.css`, the 3 SVGs + the image assets above.
- **`.gitignore`** now excludes `web/public/olderIcons.zip` (user's icon backup) and
  `web/,oracle/` (**private SSH keypair — never commit**).

## Oracle A1.Flex grabber — RUNNING
- `deploy/oracle/grab-arm-frankfurt.sh` still looping (single clean process tree, ~4h uptime):
  cycles EU-FRANKFURT-1 AD-1/2/3 every ~100 s for a `VM.Standard.A1.Flex` (1 OCPU / 6 GB).
  All attempts so far **"out of capacity"**. Log: `~/grab.log`. Root PID 2637216 (bash -c
  wrapper) → `grab-arm-frankfurt.sh` → `oci compute instance launch`.
- To restart if it dies (env vars are baked into the running invocation; re-export before rerun):
  `COMPARTMENT_ID=… IMAGE_ID=… SUBNET_ID=… deploy/oracle/grab-arm-frankfurt.sh 2>&1 | tee ~/grab.log &`
  (the three OCIDs are visible in the current process args / prior shell history).
- The keypair it authorizes lives at `~/.ssh/oracle_rosa[.pub]`; the stray `web/,oracle/`
  dir holds an older copy — now gitignored, safe to delete.

## Not Committed (deliberate)
- `web/,oracle/` — private SSH key (gitignored).
- `web/public/olderIcons.zip` — icon backup (gitignored). Safe to delete once happy with new art.
- `todo.md` — 1-byte scratch belonging to the other session; left untracked.
- `data/out/` + `web/public/data/` — build artifacts (gitignored), regenerated locally.
- All `pipeline/` `shore_normal` work — the other session's; **untouched**.

## Coordination Hazard (unchanged from prior handoff)
The shared tree's pipeline is **non-loadable**: `pipeline/src/rosa_pipeline/models.py` has a
`shore_normal` field with no default that `spots.py` never sets → `load_spots()` throws. That's
the accuracy session's in-progress Stage 2. Don't "fix" it here. None of this session's commits
touch `pipeline/`, so the deployed web app is unaffected.

## Deploy
`cd web && npm run deploy` — prod, prebuilt static (`build` → `prepare-output` →
`vercel deploy --prebuilt --prod`). CLI-only (Vercel Git integration stays disconnected;
forecast data is gitignored so a Git-triggered cloud build would ship a dataless app).
Live: https://rosa-rust.vercel.app

## Next Step
1. On the phone: hard-refresh / clear site data to pick up the new SW + icons; confirm the
   new home-screen icon and splash render.
2. Watch `~/grab.log` — when the grabber finally lands an instance, provision the pipeline
   there (that's the whole point of the loop).
3. Optionally delete `web/,oracle/` and `web/public/olderIcons.zip` once satisfied.
