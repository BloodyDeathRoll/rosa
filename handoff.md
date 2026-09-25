# Session Handoff - 2026-09-25

## Goal
Security pass on rosa: run `/security-audit`, have Dream's codebase-reviewer run a security
review with proper tests, apply what holds up, deploy.

## Current State
- **Committed, pushed to main, deployed** (cf295ae..f9fc42f):
  - user-api: a re-created account starts a fresh `session_epoch` (`wrangler deploy` done,
    version 22b5f71b; live `/` 200, bogus bearer 401).
  - web: `?import=` hardening; CSP ENFORCED for the app + a new `/widget/` CSP (live headers
    confirmed on rosa.surf and /widget/).
  - `.github/workflows/claude*.yml`: actions pinned by SHA + `persist-credentials: false`.
  - `deploy/oracle/publish.sh`: `vercel deploy` without `--token` (box CLI 59.10.0 reads
    `VERCEL_TOKEN` from env, checked in its dist). **Not yet run on the box** - first cycle
    that pulls it is 11:20 local (08:20Z) 2026-09-25.
- **Not tested:** the Google sign-in popup under the enforced CSP (GSI script + button load
  cleanly; the popup/code exchange was never clicked through).
- **Blocked:** push-api per-IP rate limits (Dream finding 4, LOW). Vercel Hobby refuses
  rate-limit rules ("Rate limiting is not available for this plan (401)"); nothing staged.
- **Uncommitted:** `docs/SESSIONS.md` (this session's entry) and this `handoff.md`, in the
  worktree `~/.superset/worktrees/rosa/clumsy-rule` (branch `session-on`). `~/Projects/rosa`
  also has an uncommitted `handoff.md` from an older session.
- Dream ledger (`~/Projects/Dream/assignments/codebase-reviewer/reports/.state/rosa.applied`)
  closed through 2026-09-25: everything applied except the blocked rate-limit item. Dream
  itself not committed (never from a project session).

## Active Files
- `deploy/user-api/src/index.ts` - sign-in INSERT seeds `session_epoch` with `now`.
- `web/src/main.tsx` - `importFromQuery`: strip first, try/catch decode, cap 200.
- `web/scripts/csp.mjs` - emits enforced `Content-Security-Policy` for site + widget (widget
  inline-script hash; throws if the widget has != 1 inline script).
- `.github/workflows/claude.yml`, `claude-code-review.yml` - SHA pins, no persisted creds.
- `deploy/oracle/publish.sh:217` - no `--token`.
- `SECURITY.md`, `docs/OPEN-ITEMS.md` 33 (corrected: no rule was ever staged), `docs/SESSIONS.md`.
- Outside the repo: `~/Projects/swarm/audits/rosa/2026-09-25/` (audit report, tests),
  `~/Projects/swarm/audits/rosa/ledger.jsonl` (ROSA-004 appended as `open` - now fixed and
  deployed, status line not updated).

## Changes Made This Session
1. `/security-audit` (delta since 2026-09-11): one proven finding, ROSA-004 MEDIUM (tag-pinned
   actions holding the Claude OAuth token). Dropped leads: undici 6.27.0 (unreachable),
   dev-only npm advisories, `/yt-feed`, widget innerHTML. Missing scan tools: semgrep,
   pip-audit, checkov, zizmor.
2. Wrote the operator a prompt for a Dream session to run codebase-reviewer security-focused on
   rosa; Dream ran it (report 2026-09-25) and found the token-revival bug the audit missed.
3. `/dream-review`: applied the token fix + `?import=` diffs with `git apply` in the worktree
   (review-apply.sh targets `~/Projects/rosa`), used the audit's full SHA pin instead of
   Dream's partial one. Then all 3 proposals by hand.
4. CSP: push-api has no runtime logs (Vercel MCP returned nothing, any window), so evidence =
   headless Chrome (system `/usr/bin/google-chrome` + playwright in scratchpad) crawling live
   pages with the built enforced headers injected via `route.fulfill`: 0 violations; an
   injected inline script was blocked on both site and widget.
5. Superset "no Run button": `~/Projects/rosa` was 2 commits behind (no `.superset/`); pulled.
6. Operator said "apply all" and later "commit, push and deploy" on 2026-09-25 - history
   only, not standing approval.

## Failed Attempts
- Vercel firewall via MCP (`update_firewall_config` schema rejects, `put_firewall_config` 404)
  and CLI (`vercel firewall rules add` -> plan 401). Rate limiting needs Pro or another path.
- `wrangler deploy` failed "Authentication error [10000]" while logged into the
  shaharnaor@outlook.com Cloudflare account; the Worker is in einhanamer@gmail.com's account
  (c283cc56...). `wrangler login` via `!` timed out at 120 s - run it in a real terminal.
- Playwright's bundled browser is not installed; use `executablePath: "/usr/bin/google-chrome"`.
- The live site shows a "Continue with Google / Not now" sheet that blocks the page in headless
  runs - click "Not now" before probing.
- Dream reviewer's jail has no network, so it cannot resolve action SHAs.

## Next Step
1. After the 11:20 local cycle, check the box's deploy still works without `--token`:
   `ssh -i ~/.config/rosa/ssh-key-2026-07-23.key ubuntu@82.70.253.255 'cd ~/rosa && git log --oneline -1 && tail -30 publish.log'`
   - expect HEAD f9fc42f or later and a "Production ... Aliased" deploy line; then check
   `curl -s https://rosa-data-opal.vercel.app/data/spots/carcavelos.json` has a fresh `fetched_at`.
2. Test Google sign-in on rosa.surf under the enforced CSP (real browser, click through).
3. Ask the operator: commit `docs/SESSIONS.md` + `handoff.md`; update ROSA-004 to fixed in
   `~/Projects/swarm/audits/rosa/ledger.jsonl`.
4. push-api rate limits (OPEN-ITEMS 33a): options are Vercel Pro, a KV counter, or moving
   contact/feedback/sub into the user-api Worker (Workers Rate Limiting is free) - ask first.
5. Carried from 2026-09-18 handoff, not re-verified: smoke check of the 09-18 fixes, Frankfurt
   `rosa-vcn` delete question, dated reads (C3b wind A/B 26 Sep, IMS beach wind 28 Sep, SWAN
   A/B 5 Oct - drop pre-fix `.swan` rows).
