# Session Handoff — 2026-10-26

## Goal
Change the launch flow so the splash lifts straight onto the app. A signed-in user stays signed in; a signed-out user sees the sign-in screen only when they try to save a spot.

## Current State
- Done and live. Commit 1af4101 is on main and deployed to rosa.surf (deployment `dpl_FYuRRChB4kA6JX8j4JxHjvHkym5R`, project "rosa").
- Verified: the live bundle has no `rosa.signin.seen` key and still has `rosa.signin.pending`.
- `tsc --noEmit` clean, vitest 47/47 pass. No test covers `SignInScreen` itself.
- Not checked on a phone or in a browser: the star-tap path to the sign-in screen and the save after sign-in.
- `docs/OPEN-ITEMS.md` not touched (nothing opened or closed).

## Active Files
- `web/src/components/SignInScreen.tsx` - starts closed; opens only on `SIGNIN_REQUEST_EVENT` (star tap via `requestSignIn` in `favorites.ts`, or Profile's Sign in).
- `docs/UI.md` - account paragraph says the screen is never shown on launch since 2026-10-26.
- `docs/SESSIONS.md` - 2026-10-26 launch-flow entry appended.

## Changes Made This Session
1. Removed the launch-time open from `SignInScreen.tsx`. The initial state was "open if signed out and not dismissed this launch". It is now `useState(false)`.
2. Removed `SEEN_KEY` (`rosa.signin.seen`, sessionStorage). "Not now" now just clears the pending spot and closes.
3. Kept as-is: the pending-spot replay after sign-in, the ACCOUNT_EVENT close, the splash look and particles.
4. Committed straight to main, pushed, and ran `npm run deploy` from `web/`.

## Failed Attempts
- `npx prettier --write` on the file reflowed unrelated lines. Prettier is not a project tool. The file was restored and only the intended edit re-applied.
- This worktree's `web/` had no `.vercel/project.json`. It was copied from `~/Projects/rosa/web/.vercel/project.json` (project "rosa") before deploying.
- The pre-push hook needs `PATH=$HOME/.local/bin:$PATH` or it fails with `uv: command not found`.

## Next Step
Nothing pending. Optional check: on rosa.surf while signed out, tap a spot's star, sign in, and confirm the spot is saved.
