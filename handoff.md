# Session Handoff — 2026-08-04 (session 16)

## Goal
Answer "how many users do we have?" — find out what Rosa could actually measure, then wire
up visitor counting. Short session, one shipped change.

## Current State
- **Visitor analytics are LIVE and verified on production.** `250117b` pushed, built, and
  deployed CLI-only to the `rosa` project. Confirmed against the real domain:
  `https://rosa-rust.vercel.app/_vercel/insights/script.js` → **200**, and the served bundle
  (`/assets/index-D--PDFpn.js`) contains the insights reference. Numbers were still 0 at
  deploy time — expected, nothing had loaded the new bundle yet. **Nobody has yet confirmed
  a non-zero visitor count**, so the end-to-end read is unproven.
- **Web Analytics was already enabled** on the project. No dashboard toggle was needed (see
  Failed Attempts).
- **The privacy page is now inaccurate, by explicit user decision.** `AboutPage.tsx:303` still
  says "your data stays on your device" and lists Vercel as "hosting" only. The user was
  offered the fix and chose "No, just deploy". Do not silently change it — re-offer before a
  public launch.
- **Everything from session 15's Next Step list is untouched.** The VM has *still* not been
  confirmed to have run a cycle on `814ebf1`/`106ac2b`. The ISRAMAR email is still unsent.
  Portugal's lead-time archive has been accruing for about a day.
- **`docs/SESSIONS.md` and `docs/OPEN-ITEMS.md` were NOT updated this session** — the
  session-off skill scopes to handoff.md only. Session 16 still needs a log entry.
- 372 pipeline tests were green at session start; no pipeline code was touched.

## Active Files
- `web/src/analytics.ts` — NEW. `initAnalytics()`: injects the script with
  `disableAutoTrack: true`, sends a pageview on load and on every `hashchange`.
- `web/src/main.tsx` — imports and calls `initAnalytics()` after `render`.
- `web/src/app.tsx` — `parseRoute` and `type Route` are now **exported** (analytics reuses
  the real routing rather than duplicating the hash regexes).
- `web/package.json` / `package-lock.json` — added `@vercel/analytics` ^2.0.1.
- `handoff.md` — this file.
- `~/.claude/projects/…/memory/plain-language-explanations.md` — NEW memory: when the ask is
  "explain", drop the file paths and caveat lists.

## Changes Made This Session
1. **Audited what Rosa can measure.** Found exactly one real counter: the push-subscription
   list in Vercel Blob, readable at `GET https://rosa-push.vercel.app/api/subs` with the
   `x-admin-secret` header (`deploy/oracle/README.md:84` already dumps it). It counts
   *devices that opted into notifications*, not users — undercounts by an unknown factor.
   The secret lives in `~/rosa/.env` on the VM, **not** on the dev box.
2. **Confirmed no analytics existed.** `@vercel/analytics` was absent from `web/package.json`
   and Vite gets no auto-injection, so nothing was ever sent. The dashboard's 0 was a
   guaranteed 0, not a traffic reading.
3. **Added `@vercel/analytics` with auto-track OFF.** The one non-obvious decision: the
   injected script hooks `history.pushState`, but Rosa navigates by assigning `location.hash`
   (`app.tsx:81`), which the script never sees. Left on defaults it would have recorded
   **one pageview per cold start and nothing else**. Driving every view manually from
   `hashchange` also rules out a double count on the back button (the script may also listen
   to `popstate`, which fires alongside `hashchange`).
4. **Spot pages report as `/spot/[id]`, not per-spot.** Keeps the report reading as five
   screens instead of a 199-row spot leaderboard. `path` still carries the real hash if the
   individual spot ever matters.
5. **Checked `data/out` staleness before deploying.** Local copy was from 08-02. Harmless:
   `web/.env.production` sets `VITE_DATA_BASE=https://rosa-data-opal.vercel.app`, so
   production reads forecasts from the separate CDN project, never from the bundled copy.
   **Keep making this check** — `npm run deploy` runs `sync-data` unconditionally.
6. Build clean: `tsc --noEmit` passed, bundle +1.2 KB gzip.

## Failed Attempts
- **Claimed the user had to click "Enable" in the Vercel Analytics dashboard. Wrong — there
  is no such button, and analytics was already on.** The `get_web_analytics` MCP tool
  returning `visitors: 0, pageviews: 0` was read as "not enabled"; it only ever meant "no
  data". The Analytics tab shows a **"Get Started" install panel** (npm install / add the
  component / deploy) *above* a live 0-value stats panel — that panel is instructions for a
  project with no data yet, **not** an enablement gate. Do not infer enablement from a zero
  count, and do not send the user to the dashboard to flip a switch.
- **`mcp__plugin_vercel_vercel__list_projects` returns `{"projects": []}`** for
  `team_jeHaUEFEe9q9CoUA71Vij1Kr` even though `get_project` resolves
  `prj_byWctijqaVdOWxFOi5s0Z2E9I5kf` fine. Read `web/.vercel/project.json` for the IDs
  instead of listing.
- **Repeatedly answered a plain question with a dense technical report.** The user asked
  "how can we tell how many users we have", then twice more in escalating caps for a simple
  answer. Cost three round trips. Saved as a memory.
- Rejected as worse than analytics, for the record: counting `index.json` fetches on the
  `rosa-data` CDN (service-worker revalidation and the PWA offline cache distort it badly),
  and a self-hosted `/api/hit` counter in the push API (a new write endpoint to rate-limit).

## Next Step
1. **Confirm a real visitor count lands.** Open `https://rosa-rust.vercel.app` on a device
   with no ad blocker, navigate between two tabs, then re-query:
   ```
   get_web_analytics projectId=prj_byWctijqaVdOWxFOi5s0Z2E9I5kf \
     teamId=team_jeHaUEFEe9q9CoUA71Vij1Kr mode=count
   ```
   Want `visitors ≥ 1` and `pageviews ≥ 2` (proves the `hashchange` path fires, not just the
   cold start). If pageviews stays at 1 while visitors is 1, the manual pageview call is
   broken — look at `initAnalytics` in `web/src/analytics.ts`.
2. **Still the highest-value unverified thing shipped — session 15's flock + 3 extra buoys:**
   ```
   ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
     'git -C ~/rosa log --oneline -1; grep -nE "^=== |FAILED at:|skipped -" ~/rosa/publish.log | tail -4'
   ```
   Want HEAD at `fe36295` or later and a clean `done`, then
   `ls ~/rosa/data/verify/archive/ | grep -ci coast-buoy` (expect ≥3).
3. **Append a session 16 entry to `docs/SESSIONS.md`.** Not done here.
4. Send the ISRAMAR email — `info@ocean.org.il`, Dr. Isaac Gertman, must ask for the
   **route** as well as permission. CAMERI (`sea21@technion.ac.il`) stays held until they
   answer.
5. Re-run Portugal with lead time around 2026-08-11:
   `uv run --project pipeline rosa-pipeline verify --buoy Leixoes-coast-buoy --archive`.
6. Re-offer the privacy-page fix before any public launch (see Current State).

## Constraints carried forward from session 15 — do not retry
- **Do not add auth to `CMEMSSource`.** The CMEMS per-platform files are on public S3; the
  Copernicus credentials in `.env.local` are unused at runtime.
- **Israel Meteorological Service is ruled out as ground truth** — it is model output.
- **Do not guess Dr. Gertman's direct email** from the `firstname@ocean.org.il` pattern.
- **Run the fleet sweep before stating a bias conclusion** — one buoy gave the opposite sign
  to the fleet mean.
- Buoy-to-spot distance is irrelevant to validation; the harness scores at the buoy's own
  coordinate.
- Watch the Open-Meteo daily quota — `archive` now covers 15 buoys on the budget that ran
  out on 08-03, and a failed `archive` still aborts the whole cycle (open item 9).
