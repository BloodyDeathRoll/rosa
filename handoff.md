# Session Handoff — 2026-10-07

## Goal
Make info@rosa.surf a real Rosa sender and receiver, route all app contact/report mail there,
and work the Dream 2026-10-07 review. All done; three small threads remain (below).

## Current State
- **info@rosa.surf = shared mailbox "Rosa"** in the Cronus Media Microsoft 365 tenant (no
  licence, 50 GB). shahar@cronus.media has Send As + Full Access. The 10-06 alias is removed.
  Mail from it shows "Rosa". Verified by a Gmail round trip and a message trace. The operator
  has it on the Outlook phone app.
- **DKIM on** for rosa.surf (Status Valid). The selector1/selector2 `_domainkey` CNAMEs are at
  GoDaddy and resolve publicly.
- **Mailbox photo NOT set.** Graph `Set-MgUserPhotoContent` returned 404 twice (unlicensed
  shared mailbox). The tenant has 1 Business Basic seat and it is used. The operator said
  "try tomorrow". Memory `rosa-mailbox-photo-retry-due-2026-10-08` has the steps.
- **Contact Us + spot Reports mail to info@rosa.surf** (`512007c`). FormSubmit is activated
  for the new address. The operator confirmed reports now arrive after reopening the app.
- **CSP fix `d8b4ded`, live.** `formsubmit.co` was missing from `connect-src` from 2026-09-25,
  so no report was mailed in that window. The 3 real user reports from that window were resent
  to info@rosa.surf (FormSubmit said success; arrival not confirmed by the operator):
  ollies-point 09-26 and 09-27, witchs-rock 09-29.
- **Dream 2026-10-07: 3 items applied, committed `79f7654`, pushed.** Pipeline-only. The VM
  pulls it next cycle. VM pickup NOT verified yet.
- Dream backlog: 0 open except push-api rate limits (blocked on Vercel Hobby, OPEN-ITEMS 33a).
  Swarm: 2 audits, all closed.
- Working tree clean, HEAD = origin/main = `79f7654` before this handoff file.

## Active Files
- `web/src/contact.ts` - `CONTACT_EMAIL` is now info@rosa.surf (FormSubmit + mailto).
- `deploy/push-api/api/contact.js` - `CONTACT_TO` default is now info@rosa.surf.
- `web/scripts/csp.mjs` - `https://formsubmit.co` added to `connect-src`.
- `pipeline/src/rosa_pipeline/blend.py` - `fetch_weather_many` attributes bodies by
  `location_id` + coordinate. `BlendedSource.fetch_many` fetches weather before GFS.
- `pipeline/src/rosa_pipeline/fetch.py` - OM ensemble json/id-ordering is inside its degrade guard.
- `pipeline/tests/test_blend.py`, `pipeline/tests/test_fetch.py` - 3 new tests, red without the change.
- `docs/SESSIONS.md` (2026-10-07 entry), `docs/OPEN-ITEMS.md` 33(b) (the CSP crawl missed the mail hop).
- Memory: `rosa-email-address.md` rewritten. `rosa-mailbox-photo-retry-due-2026-10-08.md` is new.
- Dream `reports/.state/rosa.applied` - 4 lines appended for 10-07.

## Changes Made This Session
1. Dream review (morning): 29 nights through 10-06, nothing open.
2. Diagnosed "sent as Cronus Media": an Exchange alias keeps the mailbox display name. I
   replaced it with a shared mailbox via Exchange Online PowerShell (alias removed, mailbox
   created, Send As + Full Access granted).
3. DKIM: I created the config, the operator added the 2 CNAMEs, and I enabled it.
4. Message trace showed replies were delivered to the Rosa mailbox. The operator was looking
   in their own inbox.
5. Moved the app's contact address from einhanamer@gmail.com to info@rosa.surf. Deployed
   push-api (`rosa-push`) and web (`rosa`). Committed `512007c`.
6. "Not receiving reports": the live CSP blocked formsubmit.co. Fixed and deployed. Committed
   `d8b4ded` alone so another deploy cannot drop it.
7. Dream 10-07 (reviewer shell dead, nothing run there):
   - Ensemble diff applied with git apply.
   - Weather-leg diff conflicted (the 09-30 cache fallback had changed the code), so I ported
     it by hand. Before enabling the 0.3 deg cap I measured the VM's weather cache: max offset
     0.175 deg over 2741 points.
   - Weather-first proposal applied. Its premise is stale: a refusal already falls back to the
     cache, so the gain is only the nothing-cached case.
   - Proofs FAIL then PASS. Suite 695 passed, ruff clean.
8. Resent the 3 stored user reports via FormSubmit with their original dates noted.

## Failed Attempts
- `Set-UserPhoto` no longer exists in Exchange Online.
- Graph `Set-MgUserPhotoContent -UserId info@rosa.surf` returns 404 ImageNotFoundException
  (tried 11:52 and 13:05 local). Outlook web "edit photo" opens the Cronus Media profile, not Rosa.
- `Get-MessageTrace` is deprecated. Use `Get-MessageTraceV2`.
- The first device code expired before sign-in finished. Codes last about 15 min, and each
  script run needs a fresh one.
- `dig` is blocked in the sandbox (connection refused to every resolver). Use DNS-over-HTTPS:
  `curl -s -H 'accept: application/dns-json' 'https://dns.google/resolve?name=X&type=CNAME'`.
- `pkill -f` on a pattern matching the calling shell killed it (exit 144) again. Match the pid.
- `vercel link` in a worktree rewrites `.env.local`, and these are symlinks into ~/Projects/rosa.
  The push-api one now holds only BLOB_READ_WRITE_TOKEN + VERCEL_OIDC_TOKEN. Nothing broke.
- Worktree `deploy/push-api` has no node_modules. Run blob scripts from
  `~/Projects/rosa/deploy/push-api` (it has `@vercel/blob`).
- The 2026-09-25 CSP "zero violations" crawl never sent a message, so it missed the mail hop.

## Next Step
1. Verify the VM pulled `79f7654` and the next cycle ran clean. Check the deploy log or
   `fetched_at` on the CDN per memory `pipeline-change-smoke-rule`. Watch for a
   `came back at` ValueError from the new weather attribution.
2. On/after 2026-10-08: retry the mailbox photo with the object id (memory
   `rosa-mailbox-photo-retry-due-2026-10-08`). If it still 404s, ask the operator about a
   temporary licence. They have not approved spending on one.
3. Ask the operator to confirm the 3 resent reports arrived in the Rosa inbox.
4. Still open from 10-06:
   - Send the Tango email from info@rosa.surf to support@tango.me.
   - The operator posts the Reddit showreel text (in `docs/SESSIONS.md` 10-06 / git `bd68e65`
     handoff).
   - Decide where the showreel sources live. They were in a scratchpad and are likely gone.
5. Not changed, operator to decide: `VAPID_SUB` on the VM and `deploy/backup/freshness-watch.py`
   still say `mailto:shaharnaor@outlook.com`.

Tooling: `~/.local/opt/powershell/pwsh` (7.6.6) with ExchangeOnlineManagement 3.10.1 and
Microsoft.Graph 2.41.1. Sign in with `Connect-ExchangeOnline -Device` /
`Connect-MgGraph -UseDeviceCode`; the operator enters the code.
