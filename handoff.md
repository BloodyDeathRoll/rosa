# Session Handoff — 2026-10-23

## Goal
Operator report: the Cloudflare D1 database `rosa-users` sat at 399 rows and a fresh sign-in added nothing. Find out why, then (asked later) remove the accounts that were never real users.

## Current State
- No code changed. The Worker, the D1 binding and the web bundle were checked and are correct.
- `rosa-users` now holds **33 rows** (was 399). 366 rows were deleted at 08:25Z on 2026-10-23 with
  `DELETE FROM users WHERE json_array_length(favorites)=0 AND last_seen_at-created_at < 86400000`.
- Full pre-delete export: `~/.config/rosa/d1-users-backup-20261023T082419Z.json` (399 rows, every column, mode 600). Restore = INSERT those rows back; nothing else references them.
- The "stuck at 399" had two parts, both verified, neither a fault:
  1. The operator's test sign-in (08:10Z) used a Google account already in the table (row created 2026-10-06). `signIn` in `deploy/user-api/src/index.ts` is `INSERT ... ON CONFLICT(sub) DO UPDATE`, so the same account can never add a row. Seen in D1 (`last_seen_at` = 08:10:33Z) and in D1 analytics (3 write queries in that hour).
  2. New sign-ups ran 5-18 a day from 09-18 to 10-18 and then stopped, because they were Tango Live promo visitors (SESSIONS 2026-10-06) signing in with Google on Rosa's first-load `SignInScreen`. GA4 loads with `webview=ANDROID_WEBVIEW` fell from 25-50 users a day to 1-2 on 2026-10-20. Israel traffic stayed flat (2-5 a day).
- Real-user sign-up rate is near zero and was before Tango too: 10 of the 399 rows had a favorite, 32 came back after the sign-up day.
- Untested: an actual new-account registration end to end (the operator has not yet signed in with an account unknown to the table while someone watched `wrangler tail`).

## Active Files
- `docs/SESSIONS.md` - 2026-10-23 entry (the only repo change).
- `handoff.md` - this file.
- `~/.config/rosa/d1-users-backup-20261023T082419Z.json` - outside the repo, the deleted rows.

## Changes Made This Session
1. Diagnosis, read-only: `wrangler d1 execute rosa-users --remote` (count, per-day sign-ups, last_seen, cohorts), Cloudflare GraphQL (`workersInvocationsAdaptive`, `d1AnalyticsAdaptiveGroups`), live Worker settings via the API (one D1 binding, id `b252d46b-…`), `wrangler d1 list` (one database), probes of `POST /auth/google` (401 `token:code` / `token:malformed` as designed), the live `index-*.js` on rosa.surf (correct Worker URL + client id), CSP header (GSI allowed), GA4 through `tools/ga-report/report.py`.
2. Operator asked which rows came from Tango. Answer: not identifiable - the table stores sub, email, name, picture, favorites, timestamps only. Offered the proxy "no favorites and never returned": 366 vs 33.
3. Operator said "remove all that have no favorites and never returned" (2026-10-23, ~08:24Z). Exported the whole table first, then ran the DELETE. 366 deleted, 33 remain. This was a one-time instruction; nothing is scheduled.

## Failed Attempts
- Vercel MCP `aggregate_pageviews` on project `rosa`: 404 "Web Analytics not found" - Web Analytics is not enabled there. GA4 is the only visitor source.
- Cloudflare `workers/observability/telemetry/query` with the wrangler OAuth token: "Authentication error" - that token has no Workers Logs scope. Request-level history is unavailable after the fact; `wrangler tail` live is the only view.
- `uv` is not on PATH in this worktree shell and `~/Projects/rosa/pipeline/.venv` does not exist here; system `python3` ran `tools/ga-report/report.py` fine (it needs only `cryptography`).
- GA4 `dateRange` is not a dimension (400); run one report per date range instead.

## Next Step
1. If the operator still wants proof that registration works: run `cd deploy/user-api && npx wrangler tail --format pretty`, have them sign in on rosa.surf with a Google account never used on Rosa (or Profile > delete account first), expect one `POST /auth/google` 200 and `SELECT COUNT(*) FROM users` to read 34.
2. If the real-vs-Tango split matters going forward: store the sign-in origin (e.g. a `source` column set from a client flag when the landing URL carried `webview=ANDROID_WEBVIEW` / `token`+`accountId`) - needs an operator decision, nothing built. Alternatively stop showing `SignInScreen` on first load for those visitors (`web/src/components/SignInScreen.tsx`, `TangoNotice.tsx` already detects the loads).
3. `docs/OPEN-ITEMS.md` was not touched; add an item only if 2 is wanted.
