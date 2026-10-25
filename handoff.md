# Session Handoff — 2026-10-25

## Goal
Fix the "15-day" site copy, then clear every open PR: agent review, audit, fix, merge, delete branch.

## Current State
- Zero open PRs. Main is at 037fb1a (PR 37 merge). rosa.surf deployed from main after the merges.
- `@claude` comment trigger on PRs works again (7dcff3f). It had been silently broken since 2026-09-25.
- `docs/SESSIONS.md` has the 2026-10-24/25 entry. `docs/OPEN-ITEMS.md` not touched (nothing opened or closed).

## Active Files
- `.github/workflows/claude.yml` - checkout no longer sets `persist-credentials: false` (comment in the file explains why).
- `web/edge/ig.js`, `web/scripts/edge.mjs`, `web/vercel-output.json`, `web/vite.config.ts` - the `/ig` edge redirect (PR 38).
- `web/index.html`, `web/src/head.ts`, `web/src/seo.ts`, `progress.md` - 16-day copy.

## Changes Made This Session
1. c215c9f: copy 15-day -> 16-day everywhere (pipeline horizon is 16).
2. PR 38: Workbox denylist fix `/^\/ig\/?(\?|$)/` (ab41993); operator merged.
3. Merged in order, squash, branch deleted: #35, #34, #31, #32, #37. Each SHA pin verified against its tag; ruff 0.17.1 run locally on the pipeline.
4. 7dcff3f: `claude.yml` keeps checkout credentials so the action's PR-branch fetch works in tag mode.
5. `cd web && npm ci && npm run deploy` from main. Verified `/ig` 302 (also `/ig/?fbclid=`), `/map` in headless Chrome with MapLibre 6.14: worker loads, no console errors, tiles render.

## Failed Attempts
- `@claude review` posted via `gh pr comment` on all five dependabot PRs: every run died at `git fetch origin <branch>` ("could not read Username"). That was the trigger bug, not a `gh` problem.
- The pre-push hook fails with `uv: command not found` unless `PATH=$HOME/.local/bin:$PATH` is exported first.

## Next Step
Nothing pending. If a future `@claude` PR run fails again, read the job log for the step after "This is an open PR, checking out PR branch..." first.
