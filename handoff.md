# Session Handoff - 2026-07-30

## Goal
Run Stage 2E for real, now that the VM archive had matured. Both halves ran: the buoy half
concluded the input needs no correction at all, the Israel half moved one knob. A Surfline
side-by-side afterwards then turned up a separate and larger finding about Open-Meteo's
partition fields.

## Current State
- **All committed and pushed**, main at `3be95b3`, working tree clean. **318 pipeline tests
  green**, `ruff check` + `ruff format` clean. Full `run --all` clean (199 spots, 0 warnings).
- **Stage 2E is DONE.** `period_rideability` keys on the PEAK period; `RIDEABILITY_EXP` stays
  1.4. Nothing else moved - not gamma, not `height_coeff` (still 1.0 at all 199 spots), and no
  input de-bias of any kind.
- Web deployed and verified live: `index-tWop6GtP.js` on rosa-rust.vercel.app, with the
  rewritten `#/about/reading` disclosure confirmed present in the shipped bundle.
- **UNVERIFIED: the VM has not yet run any cycle carrying today's work.** At 08:18Z it was still
  on `cb5cda9`; the last completed cycle was 02:20Z. The 08:20Z cycle is the first to pull both
  the 2E forecast change and the closure ratio. **Check this first.**
- **UNVERIFIED, carried from session 10:** the notify fix has still never fired a real push in
  production - verified by simulation only.
- Local `data/out` is a fresh post-2E fleet run (carries `closure`). Local
  `data/verify/archive/` is rsynced from the VM (25 MB, 12 stations, ~1 week).

## Active Files
- `pipeline/src/rosa_pipeline/transform.py` - new `rideability_period()` (peak-keyed) and
  `partition_closure()`; `breaker_height_from_profile`'s default factor changed.
- `pipeline/src/rosa_pipeline/experiment.py` - `BASELINE` is now `key="peak"`; report footer
  prints both ranking criteria and no longer promises a buoy de-bias.
- `pipeline/src/rosa_pipeline/models.py` - `HourForecast.total_hs_m` (trailing default).
- `pipeline/src/rosa_pipeline/extract.py` - carries `wave_height` through; it was previously
  read only as the horizon null-sentinel and dropped.
- `pipeline/src/rosa_pipeline/publish.py` - per-hour `closure` key (omitted, not null, when the
  source published no total).
- `data/calibration/frames.yaml` - Poleg 2026-07-27 added; 5 frames now.
- `web/src/pages/AboutPage.tsx` - period disclosure corrected.
- `pipeline/tests/{test_transform,test_experiment,test_publish}.py` - 12 new tests.
- `docs/CALIBRATION.md` (five entries today), `CLAUDE.md` (SESSION 11 + NEXT rewritten).

## Changes Made This Session
1. **2E buoy half: no input correction is defensible.** Swept 12 stations x 3 sources on the
   session-10-fixed harness. Open-Meteo, n=45,252: period bias **+0.21 s** (the "hot period" is
   dead for good), Hs fleet **-0.005 m which is pure cancellation** (CDIP Waverider -0.299 vs
   NDBC discus +0.088; Hawaii's 51201 +0.232 against 51202/51205 -0.498/-0.466), direction
   +15.6 deg. **No source swap:** GFS-Wave runs 0.12 m low and loses Hs mae at every lead. It is
   the better direction source but that is measured on total-sea `mwd`, not the per-partition
   directions `spread_exposure()` consumes, so still not actionable.
2. **2E Israel half: knob moved.** Added the Poleg frame the 07-27 log entry earmarked (tide
   reconstructed from the OM marine archive, which corroborated the logged partitions within
   0.04 m / 0.2 s). Every mean-keyed candidate under-calls 3 of 5 frames by -0.22..-0.43 m;
   every peak-keyed one fixes them. **No exponent reconciles all five - checked out to exp 3.0** -
   because the split is by SPOT, not by period regime. Chose frames-passed over min-max-error;
   held the exponent at 1.4 because lowering it inflates the smallest hours most (fleet p10
   x1.25 at exp 1.0), the false-hope direction. Effect is surgical: rideability saturates at its
   1.0 cap above ~10 s, so every >=8 s region is bit-identical. 3.39% of 25,472 hours change
   bucket, **POOR->FAIR 734 against 2 downgrades total**.
3. **Surfline side-by-side, 5 spots** (Zvulun, Hilton, Beit Yanai, Supertubos, Hikkaduwa,
   Popoyo). In clean conditions our 0.3-0.5 sits inside their 0.3-0.6 at all three Israeli
   spots. Direction agrees within a few degrees with inconsistent sign, supporting the reading
   that the +15.6 deg is a blending artifact.
4. **Found and wired up partition closure.** Open-Meteo's four partition fields do not always
   hold all of its own energy; Rosa reads only partitions. Published `closure` =
   RMS(partitions)/total. Fleet over 25,136 hours: israel 1.00, japan 0.97, philippines 0.96,
   nicaragua/hawaii 0.95, portugal/costa-rica 0.94, california 0.91, sri-lanka 0.90. Every
   region except Israel and Hawaii has hours below 0.60. **Diagnostic only - nothing scores on
   it**, deliberately, because a low ratio says energy is missing but not its direction or
   period.
5. Corrected `#/about/reading`, which said the surf height is computed from the mean period -
   no longer true after change 2, and principle #3 requires the disclosure be accurate.

## Failed Attempts
- **Three of my own conclusions were wrong today and had to be walked back in the log.** Every
  one was caught by adding a control, not by reasoning harder.
  - *"We read bigger than Surfline on the small hours."* Drawn from Zvulun alone. Their own
    Zvulun reads 0-0.3 at 3am where their Hilton and Beit Yanai read 0.3-0.6 on identical input.
    Their spot-to-spot spread was as wide as the gap being chased.
  - *"Open-Meteo is ~0.8 m low in Sri Lanka."* **Wrong, and I was one step from proposing a
    regional Hs correction on it.** A control group made it look clean (+0.00 across 7
    buoy-checkable regions vs +0.60 for Sri Lanka). Deep water then showed OM and ECMWF agreeing
    to 0.01 m, and a transect showed Arugam Bay's gap was **ECMWF's 0.25 deg grid failing to
    resolve the island sheltering its own east coast** (OM 1.32 m at the coast to 2.61 m at
    120 km). At Hikkaduwa OM's total (2.32) matched ECMWF's (2.18). OM was never low.
  - *"A third of the sea is missing."* Closure is a ratio of HEIGHTS; energy is `closure^2`, so
    0.73 is ~27% of the height but ~47% of the energy.
- **Third comparison artifact this month**, after APD-vs-Tm-1,0 and blended `mwd`: a coarse grid
  against a sheltered coast. **A control group plus a deep-water check are what caught it -
  build both into any future cross-source claim.**
- **ECMWF's period bands start at 10 s**, so they cannot referee a 4 s vs 9 s question directly.
  `swh` plus the Tm02/Tm-1,0 moments do - Tm02 weights short waves as H^2/T^2, which is what
  ruled out Surfline's 9 s reading at Hikkaduwa.
- **`Spot` has no `offshore_bearing`** - it is consumed when deriving `offshore_point`. Compute
  the bearing from the pin if you need it.
- **Bash cwd persists between calls** - bit me again after a `cd pipeline`. Use absolute paths.
- **`run --all` died once on an Open-Meteo TLS handshake timeout mid-batch**, exit 1, and needed
  a plain retry. Transient, not a code fault - do not go hunting for a bug.
- **Do not use `verify --resolve --apply` for cams unattended** (standing, from session 10).

## Next Step
1. **Confirm the 08:20Z cycle** - the first production run carrying 2E and closure:
   `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 'grep -E "^=== |FAILED at:" ~/rosa/publish.log | tail -4'`
   Expect the VM to move off `cb5cda9`. A failure means stale data for 6 h and an admin push.
2. **User action, highest value: eyeball a flat Israeli morning.** The residual 2E error is
   per-spot (Poleg -0.12 m under, the 07-19 Beit Yanai flat frame +0.15 m over) and
   `height_coeff` is 1.0 everywhere. Surfline could not settle it; only eyes can. Prefer
   **as-logged** frames - provenance confounded the existing five, since both frames resisting
   peak-keying are hindcast-reconstructed and all three demanding it are as-logged.
3. **In a week, once `closure` has accumulated:** does it track the sea state or the spot? Is
   the missing energy short-period, where `period_rideability` floors it anyway and this is
   nearly harmless, or long? **Do NOT scale partitions to close the gap** - that invents
   direction and period the model never gave. A confidence penalty is the honest option.
4. **A product decision nobody has made:** Surfline's surf height drops a band in an onshore
   afternoon; ours does not, because wind lives in the rating and not the height. Should a
   blown-out 0.6 m read smaller?
5. Backlog: watch for the first real notify push; chigasaki cam replacement (nearest official is
   Kanagawa's 平塚海岸 `62_twW5uXd4`, ~6 km west); `hagolshim` points at a Rishon LeZion stream
   ~5 km south; `tide_best` values; 79 ruff findings in `tools/` + `deploy/`.

---

# Session Handoff - 2026-08-02 (parallel web session)

Appended, not overwritten: another session was mid-rewrite of the 07-30 handoff above and owns
the uncommitted `pipeline/` work (`horizon.py`, `cli.py`, `extract.py`, `fetch.py`,
`test_peak_period.py`, `data/spots/costa-rica.yaml`). None of that is described here.

## Goal
A user asked for a link that installs the PWA immediately; that turned into a bug report - an
Android user got no install popup and no menu entry at all. Find out why and fix it.

## Current State
- **Done, committed, pushed, deployed.** main at `0cd273b`; production aliased to
  rosa-rust.vercel.app. `tsc --noEmit` and `npm run build` clean.
- **Android install was broken and is now fixed.** Live manifest serves four PNG icons, each
  200 `image/png`. Verified via CDP on the built app: manifest parses them at real `192x192` /
  `512x512`, `Page.getInstallabilityErrors` -> `[]`, `beforeinstallprompt` fires.
- **The install sheet no longer burns itself on sight.** Verified 4-state: first load shown /
  reload unanswered shown again / after "Not now" gone with `seen=1` / reload still gone.
- Profile has a standing **App -> Install Rosa** row; verified rendering in the built app.
- **UNVERIFIED: no real Android device has been tested.** Everything above is desktop Chrome 151
  headless. The Android WebAPK path itself cannot be exercised from here - the reporter is the
  only real test. He may need one reload if Chrome cached the old manifest.
- There is no "install link" and there cannot be: no browser lets a URL trigger an install.

## Active Files
- `web/public/icon-{192,512}.png`, `icon-maskable-{192,512}.png` - new, rasterized from the
  existing SVGs by headless Chrome screenshot (no rasterizer is installed on this box).
- `web/vite.config.ts` - manifest `icons` lists the PNGs first, SVGs kept as trailing extras.
- `web/src/install.ts` - new `manualInstallOffer()` (same detection, no session gate);
  `installOffer()` delegates to it.
- `web/src/components/InstallPrompt.tsx` - marks seen on answer, not on render.
- `web/src/pages/SettingsPage.tsx` - new `InstallCard`, above `NotificationsCard`.
- `web/src/styles.css` - `.settings-install` (shape for the standalone button).

## Changes Made This Session
1. **Diagnosed, did not guess.** Drove headless Chrome 151 over CDP against the live site:
   `getInstallabilityErrors` came back `[]` and `beforeinstallprompt` fired, so desktop was
   fine and the manifest was not obviously broken. Polling the DOM then showed the sheet
   appearing at ~1 s on a fresh session - so the app logic worked too.
2. **Found the real fault: SVG-only manifest icons.** Both entries were `type: image/svg+xml`
   with `sizes: "any"`; Chrome's own parser reported both as `0x0`. Desktop accepts that;
   Android mints a WebAPK and needs raster icons, so installability fails there - no popup, no
   "Install app" menu entry, which is exactly the report. Matches Chromium issue 40925759.
3. **Added 192/512 PNGs for `any` and `maskable`**, ahead of the SVG entries. The `any` pair is
   the red mark on transparency with 6% padding; the maskable pair is the full-bleed red tile
   (its SVG already insets the mark).
4. **Fixed the one-shot sheet.** `markInstallSeen()` ran when the sheet *rendered*, so a sheet
   the user scrolled past was spent for the whole tab session - and sessionStorage survives
   reloads and Chrome's tab restore. Now it marks on answer.
5. **Added the Profile row** as the standing way back in, since the sheet was previously the
   only install affordance in the entire app.

## Failed Attempts
- **`Page.getInstallabilityErrors` cannot prove the Android case.** It returned `[]` for the
  broken manifest, because it runs the desktop check. Do not treat a clean desktop CDP result
  as "installable on Android" - that is what made the bug invisible.
- Three CDP setup dead ends, all fixed: `/json/new` now needs PUT (use `/json/list` and attach
  to the existing tab); the WS handshake 403s without `--remote-allow-origins=*`; top-level
  `data:` URL navigation is blocked, so rasterizing needs `Page.setDocumentContent` on an
  `about:blank` frame.
- WebFetch on `issues.chromium.org/issues/40925759` returns only the sign-in shell - unreadable,
  the finding rests on the search summary plus the direct CDP evidence.
- First read of the symptom assumed Chrome-on-iOS (which genuinely shows nothing, since
  `install.ts` excludes `CriOS`). The user corrected it to Android; that path is still a real
  hole and is still unaddressed.

## Next Step
1. **Ask the reporter to reload rosa-rust.vercel.app on his Android** and confirm either the
   popup or Chrome's menu now saying "Install app" (not "Add to Home screen"). This is the only
   remaining verification and nothing here substitutes for it.
2. If it still fails, get `chrome://webapks` from his device - it names the WebAPK failure.
3. Unaddressed by choice: **Chrome on iOS still gets nothing at all** - no sheet, no Profile
   row, no "open in Safari" sentence. `manualInstallOffer()` in `web/src/install.ts` is the one
   place to fix it.
4. Never built: the `#/install` deep link that force-shows the sheet. The Profile row covers the
   same need.
