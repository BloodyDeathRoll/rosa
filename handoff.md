# Session Handoff — 2026-07-23 (session 8)

## Goal
Surface pipeline `events[]` to users. Ended (after live user review) as **push-first**:
real Web Push swell alerts + a 👍👎 feedback loop, with ALL in-app event chrome removed.
Then a run of UI corrections (map fabs, themed attribution, Surfline-style tide times,
`tide_best` spot field).

## Current State
- **Web Push is LIVE end-to-end and verified on the user's Samsung phone** (real
  FCM sends from this machine). rosa-push.vercel.app (Vercel project `rosa-push`,
  private Blob store `rosa-push-subs`) stores subscriptions; `rosa-pipeline notify`
  groups events (one swell = ONE push; region + peaks ≤12 h + dirs ≤45°) and sends
  via pywebpush. Committed & pushed through 52340b4; VM pulled it and a dry-run
  found 85 real events → 7 groups → 2 pushes planned for the user's favorites.
  From the 20:20 UTC cron cycle on, the VM sends real swell pushes by itself.
- **DESIGN RULE (user, memory + CLAUDE.md): events surface ONLY as push.** Banner,
  Today alert strips, canvas share card were built, reviewed, and deleted. Also
  removed on review: Stage-3b "Sets" bar, amber missed-swell note, Profile "Spots"
  card. Do not rebuild any of these.
- **UNCOMMITTED batch (working tree, ~744 lines — user knows, says "commit" to ship):**
  feedback loop (evening 👍👎 push w/ lock-screen actions + next-open retro prompt +
  Profile "Spot feedback" toggle + `/api/feedback` + VM pull into
  data/verify/feedback), map locate/north fabs + geo cache-bust, themed bottom-left
  attribution, tide extreme time labels, `tide_best` field. All tested (230 pipeline
  tests, tsc clean) and DEPLOYED to rosa-rust.vercel.app + rosa-push — but the VM
  runs committed code only, so evening feedback asks + `tide_best` in payloads are
  INERT until commit+push.
- Notification icon anatomy (tested on One UI): left tile = Android app identity
  (uncontrollable), right slot NEVER stays empty (icon → image; none → "R" monogram;
  transparent PNG → still monogram). Shipped: waves badge in the right slot on
  Android, brand tile on desktop, waves as status-bar badge.
- Secrets: VAPID private key VM-only (`~/rosa-push/vapid_private.pem`), backup +
  admin secret in gitignored `web/.oracle/` (also in scratchpad, dies with session).
  VM `~/rosa/.env` has PUSH_SUBS_URL/PUSH_ADMIN_SECRET/VAPID_* (5 vars).
- rosa-demo.vercel.app = public throwaway deploy w/ synthetic events (CORS-allowed
  at the push API) for look-and-feel testing. LAN review server was
  `npm run dev -- --host --port 5173` from web/ (background task, dies with session).
- Fixed in prod: `--accent` CSS token was corrupted ("#Splash image not mirrored").

## Active Files
- pipeline/src/rosa_pipeline/notify.py — sender: event grouping + feedback-ask planning + pull_feedback (uncommitted half)
- pipeline/tests/test_notify.py — 27 tests incl. feedback planning/dedupe-merge
- pipeline/src/rosa_pipeline/{models,spots,publish}.py — `tide_best` low|mid|high passthrough (validated, never derived)
- pipeline/src/rosa_pipeline/cli.py — `notify` cmd (+feedback_dir wiring)
- deploy/push-api/api/{sub,subs,feedback}.js — subscription store + admin + feedback drop-box (private Blob)
- deploy/oracle/publish.sh — step 4: notify (guarded by env presence) [committed]
- web/src/push.ts — subscribe/unsubscribe/sync (+feedback pref rides on sub record)
- web/src/feedback.ts — NEW: stash day's promise on spot view → next-open 👍👎 prompt → POST
- web/public/push-sw.js — push/notificationclick handlers, 👍👎 actions POST from SW, per-platform icons
- web/src/pages/SettingsPage.tsx — Swell alerts + Spot feedback toggles (Spots card removed)
- web/src/pages/{TodayPage,SpotPage}.tsx — FeedbackRow; `?ev=` deep link (hashchange-reactive); stashView
- web/src/pages/MapPage.tsx — locate fab (refreshPosition), north compass fab, attribution bottom-left collapsed
- web/src/geo.ts — refreshPosition() busts the session null-cache (the "location not picked up" bug)
- web/src/components/TideSection.tsx — Surfline-style time+height labels at tide extremes; tide_best line

## Changes Made This Session
1. Built alerts 3 ways (banner/strips/share-card) → user killed all in-app chrome →
   push-first rule saved to memory. `?ev=` deep link kept (notification landing).
2. Web Push infra: VAPID keypair, rosa-push project + private Blob, SW handlers via
   workbox `importScripts` (generateSW kept), Profile toggle w/ surfaced errors.
   Committed as 5 commits (e92db54..52340b4), pushed, VM rolled out + dry-run verified.
3. Real push test loop with user: SW updates need app force-close+reopen on Android;
   CORS allowlist needed rosa-demo; icon probe rounds (see anatomy above).
4. Feedback loop (user: "Love it" + demanded "Spot feedback" toggle): evening ask
   17:00–22:00 spot-local, GOOD+ days, favorites only, hard 1/day/device;
   lock-screen 👍👎 answered by SW POST; retro prompt next open; VM pulls rows into
   the `feedback --report` store then prunes server-side.
5. UI corrections one-by-one (each deployed): Spots card removed; map locate+north
   fabs; attribution themed/bottom-left/collapsed (out-specify
   `.maplibregl-ctrl-attrib.maplibregl-compact`, collapse again on map `load`);
   locate aligned w/ attribution chip (+10px maplibre margin quirk); tide extreme
   labels (HTML overlay — svg is stretch-scaled); `tide_best` end-to-end (no data
   filled yet — local knowledge only, user fills YAML).

## Failed Attempts
- Payload-side icon removal on Android: omitting `icon` → "R" monogram; fully
  transparent PNG → still monogram. The right slot cannot be blanked on One UI.
- `vercel blob store add` (wrong syntax → `create-store`); PATCH project API for
  preview protection → 403, CLI has no raw token (plugin auth) → used a throwaway
  prod project (rosa-demo) instead of protected previews.
- Geolocation on the LAN dev URL can never work (http = insecure origin) — locate
  button only works on https (prod).
- Vite 6 dev server loses `public/data` when sync-data rm-rf's it mid-session →
  serves index.html for /data/* → "JSON.parse unexpected character" — fix: restart
  dev server after any `npm run build` while it runs.
- `tests/` imports between test files fail (not a package) — inline fixtures.
- Background tasks / new shells reset cwd to repo root — `cd web` explicitly.

## Next Step
1. User says "commit" → commit the uncommitted batch (suggest: feat(pipeline) notify
   feedback loop; feat(push-api) feedback endpoint; feat(web) feedback UI + map fixes
   + tide labels + tide_best; conventional, small) → push → VM picks up next cycle;
   then check `~/rosa/publish.log` after 20:20 UTC for "notify:" lines (swell pushes
   + `notify: N feedback rows pulled`).
2. Watch item: tonight's first autonomous pushes incl. "Epic at Zvulun ~0.8 m WNW"
   (calibration-suspect — Stage 2E fodder).
3. ~2026-07-30 archives mature: Stage 2E tuning + 3-way source verdict
   (`verify --buoy <id> --archive --source om|gfswave|ecmwf`) + 3b acceptance.
4. Parked: spot-DB ODbL seed; A1 watcher reboot-persistence; user fills `tide_best`
   values in data/spots/*.yaml.
