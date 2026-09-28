# Session Handoff — 2026-09-28

## Goal
Swim mode for Rosa: a per-device Profile toggle (Surf / Swim) that re-reads the same
published forecast for sea swimmers on every screen, with surf mode unchanged. Later in
the session: calibrate swim chop from the operator in the water at Hilton, show wind in
km/h for metric users, +10% type app-wide, and track the mode in GA.

## Current State
- All shipped: `origin/main` = 015b5e7, web deployed to rosa.surf after cdf0a92 (last
  web change). 38 web tests pass (`cd web && npm test`), `tsc --noEmit` clean.
- Work was done on the Superset worktree branch `add-swim-mode`
  (`~/.superset/worktrees/rosa/denim-polyanthus`) and pushed with
  `git push origin add-swim-mode:main` (fast-forward; no PR, no remote branch).
- Swim mode covers: spot page (hour-ribbon strip, words card, swim hourly table, tide
  slack/flow), Today cards + coast rows, Spots, search, desktop ticker, map pins/clusters/
  cards, nearby cards, report tags, About page section.
- GA: app sends user property `mode` at boot and on switch; the operator registered the
  user-scoped custom dimension `mode` on 2026-09-28 ~evening. `tools/ga-report` accepts it
  (all rows "(not set)" so far - data needs 24-48 h).
- NOT done: **no GitHub agent review has run on any of today's commits** - the Claude
  GitHub App is not installed on BloodyDeathRoll/rosa (every `claude-review` run since
  2026-09-13 fails "401 ... install the Claude Code GitHub App at
  https://github.com/apps/claude"). Operator step, not done.
- Two open Dependabot PRs (#25 ruff lock, #26 npm bumps) unreviewed for the same reason.
  #25's `pipeline` check fails only because its base predates 3028cb5 (sdb.py format).
- Known mismatch, reported, NOT fixed: the spot page day note (`swimNote`) uses all hours
  incl. night while the pill uses daylight - e.g. Santa Teresa "Choppy" pill vs "Easy going".

## Active Files
- `web/src/lib/swim.ts` - every swim derivation + named constants (chop calibrated today).
- `web/src/swimData.ts` - on-demand payload fetch for index-only screens (6 in flight, IO).
- `web/src/mode.ts` - mode store (localStorage `rosa.mode` + event), copy of units.ts.
- `web/src/units.ts` - `fmtWind` / `windUnit`: km/h with metres, kt with feet.
- `web/src/pages/SpotPage.tsx` - `SpotPanel` (pure), `SwimHourRow`, `SwimWordsCard`.
- `web/src/components/CoastChart.tsx` - `swimColumn`, `SwimRibbon`, `SwimMiniBars`, legend.
- `web/src/pages/{TodayPage,SpotsPage,SearchPage,MapPage,SettingsPage,AboutPage}.tsx`,
  `components/{SpotCard,DesktopBar,ReportSheet,TideSection,parts,icons}.tsx` - swim branches.
- `web/src/styles.css` - swim rules (classes surf never emits), every font-size x1.1.
- `web/src/test/` - surf snapshots (`__snapshots__/`), swim render tests, bondi fixture.
- `pipeline/src/rosa_pipeline/{models,spots,publish}.py` - optional `shore` field (unset).
- `tools/ga-report/report.py` - reports `mode`; survives it being unregistered.
- `docs/mockups/swim-layout/option-{a,b,c,d}.png` - the four layouts shown to the operator.
- Docs: `docs/UI.md`, `docs/CALIBRATION.md` (2026-09-28 entry), `docs/OPEN-ITEMS.md` 40,
  `docs/SPOT-DB.md` (`shore`), `docs/SESSIONS.md`.

## Changes Made This Session (in order)
1. Extracted `SpotPanel`, added vitest, froze surf snapshots from pre-swim code (5cd59b1).
2. Swim mode on the spot page (b631cc4); card said "no pollution data" twice -> fixed.
3. Operator: "card says Poor, inside says Calm" -> froze surf render of all other cards
   (0daec38), then swim branches everywhere (9a4340c). Index `h` is the CURRENT hour, so
   swim screens show the DAY figure from `swimDayView`, "…" until loaded.
4. Operator called the layout unclear -> 4 mockups from live Hilton numbers; picked A strip
   + B card (ea8dc7a), then D strip (hour ribbon) + D's words card with notes (8120df3,
   2b421ea), chop line removed then restored (97bfa71). Operator-approved on 2026-09-28.
5. Hilton "forecast way off": Surfline's 20/23 are km/h = Rosa's GFS knots; IMS Tel Aviv
   Coast read 11-13 kt g16 = Rosa 10-12 kt. Real miss: swim chop scored 12 kt onshore over
   a 4 s sea Calm 81. `CHOP_PER_KT` 1.6->3.5, `CHOP_MAX` 35->70 -> Choppy 58 (a36491d).
   Wind now km/h for metric users (deliberate surf change; snapshots re-baselined, only
   wind numbers/unit changed).
6. Selector icons (aa4f2d7); note under selector removed + every font +10% (aaf33cf);
   home-card air/water/suit forced to one line: "air"/"water" words dropped for icons,
   long suit labels step to 11.4/10.8 px (cdf0a92).
7. IMS read (OPEN-ITEMS 25) for station 178 only: bias ~0, MAE 0.7 m/s, fitted diurnal
   correction +3.1% worse -> no correction.

## Failed Attempts
- `pkill -f <pattern>` from the Bash tool kills its own shell (exit 144) every time; use
  `kill $(pgrep -f "patter[n]")` (bracket trick) and check ports with `ss -ltnp`.
- Workspace browser pane lost WebGL (map "couldn't load" in BOTH modes); use headless
  Chrome: `google-chrome --headless=new --remote-debugging-port=9333 --use-angle=swiftshader --enable-unsafe-swiftshader`.
- VM verify: from `~/rosa/pipeline` the station registry is empty; run from `~/rosa` with
  `set -a; . ./.env; set +a; ~/.local/bin/uv run --project pipeline rosa-pipeline verify --station <id> --archive --bias-profile`.
- GA Admin API from the service account: 403 "Admin API not enabled in project
  889597220636"; account is `rosa-ga-reader` (read-only); no gcloud installed. GA UI needs
  the operator's sign-in.
- `superset browser` Superset pane and first vitest config: a `/** ... **/*.test ... */`
  comment closes itself - avoid `*/` inside JSDoc.
- Map carousel landed on the wrong card in swim mode when readings arrived mid centring
  scroll -> fixed by not re-setting an unchanged card list on data-only redraws.

## Next Step
1. Ask the operator to install the Claude GitHub App on the repo
   (https://github.com/apps/claude), then post "@claude review" on #25, #26 and trigger a
   review of today's commits on main; audit the answers (global rule 6).
2. After 24-48 h: `GA_SA_KEY=~/.config/rosa/ga-sa.json uv run --project pipeline python tools/ga-report/report.py` - read PREFERENCE: mode.
3. Read the other four IMS beach stations (46, 124, 208, 106) with the VM command above.
4. Offer: make `swimNote` (SpotPage day note) use daylight hours like the pill.
5. Stage 4 SWAN A/B read due 2026-10-05 (memory note).
