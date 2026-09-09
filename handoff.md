# Session Handoff - 2026-09-09

## Goal
Tell new users that a spot page carries a **Report an issue** button: phrase the message,
then build it as a scheduled full-screen popup, matching the user's own Figma frames.

## Current State
DONE, committed as `c441880` on `main`, pushed, deployed to production, verified live on
rosa.surf (popup appears on a fresh visit: full-screen at 390px, 582px card at 1440px).

- Copy shipped: "Know a spot better than we do? / Check your favorites. / Wrong pin, wrong
  name, missing break? Tap **Report an issue** on the spot. / A person reads every one."
- Schedule works: first launch on the device, every sign-in, then once a week for 4 more
  weeks (5 showings per run). X and OK only close it.
- Sign-in error messages were also split (see below) and verified in a real browser.
- **Untested by a human:** nobody has actually completed a Google sign-in since the error
  split; only the failure paths were exercised. Also nobody has read the popup on a real
  phone - all checks were headless Chrome at 390px.
- One pre-existing thing noticed, not investigated: rosa.surf rendered in LIGHT theme with
  the browser set to dark. Local dev honoured dark correctly. Site default, not the popup.

## Active Files
- `web/src/nudge.ts` - NEW. The schedule only: `nudgeDue()`, `nudgeDueOnSignIn()`,
  `markNudgeShown(reason)`. State is `rosa.nudge.report` in localStorage
  (`{started, shown, last}`).
- `web/src/components/ReportNudge.tsx` - NEW. The popup. Mounted in `app.tsx` above
  `<InstallPrompt/>` and `<SignInScreen/>`.
- `web/src/components/icons.tsx` - added `XIcon`.
- `web/src/styles.css` - `.nudge-*` block (phone) + desktop rules at the END of the
  `@media (min-width: 900px)` DESKTOP block.
- `web/src/account.ts` - `AccountError` kind union gained `"unreachable"`; `loadGsi`'s
  offline branch now throws `offline`, not `google`.
- `web/src/components/GoogleButton.tsx` - one message per kind.
- `docs/UI.md`, `docs/SESSIONS.md` - updated.
- `web/public/splash_16-9.png` - the user replaced it before this session; committed along.

## Changes Made This Session
1. Phrasing first. The user's draft was rewritten to name the real button
   ("Report an issue") so people can find it, and to drop the exclamation marks and the
   "make Rosa better for you" tagline. The user picked the shorter of two options.
2. Built it as a page, not an overlay - same reason `ReportSheet` is a page: `--background`
   is 11% white over a photo, so a translucent sheet lets the forecast bleed through.
   `--body-bg` is the one opaque token.
3. z-index 59, one under the install sheet (60) and sign-in screen (9998), so a fresh
   install answers those first and finds this waiting.
4. Schedule: a sign-in restarts the run; a sign-in within 10 min of a showing is treated as
   the same event, so a first launch that goes straight into Google does not show it twice.
   Storage blocked (private mode) degrades to once per page load.
5. User asked for centred text and two line breaks; then handed over the Figma frames and
   the layout was rebuilt from them (file `Rosa`, page `designs`): **mobile** node 1:21,
   **desktop** node 1:42. Desktop = the same block as a 582px modal card over the app,
   80px padding, radius 16, on a 60% `--body-bg` scrim (`color-mix`, so it dims in either
   theme). The mock's 6%-black shadow is invisible on the dark ground, so dark gets a
   `--border` hairline - the only deliberate deviation from the mock.
6. The user hit "Couldn't reach Google" on a review server. Root cause was environment
   (below), but it exposed two real mislabels, now fixed: an unreachable Rosa user API was
   thrown as the `offline` kind, and a device with no connection was thrown as `google`
   inside `loadGsi`. Each side now names itself:
   google -> "Couldn't reach Google...", offline -> "You're offline...",
   unreachable -> "Rosa couldn't be reached...", api -> "Sign-in didn't complete...".

## Failed Attempts
- **Review server on port 5199 broke sign-in twice over.** 5199 is NOT in the OAuth client's
  `javascript_origins` (only `https://rosa.surf`, `www`, `rosa-rust`, `rosa-demo`,
  `http://localhost:5173`, `http://localhost`), AND it inherited `.env.development`'s
  `VITE_USER_API=http://localhost:8787`, a Worker that was not running. **Always review on
  `localhost:5173` with `VITE_USER_API` set to the live Worker and `VITE_DATA_BASE` set to
  the CDN** - the local `data/out` is a stale run and `npm run dev` copies it.
- Playwright is NOT installed in `web/`; its browsers are not downloaded either. What works:
  import from `/home/shahar/Projects/uptake/node_modules/playwright/index.mjs` and launch
  with `executablePath: "/usr/bin/google-chrome"`.
- First screenshots came out light in both themes: `colorScheme` alone does not drive the
  app, it reads `localStorage["rosa.theme"]`. Set that in an init script.
- A probe that called `startGoogleSignIn()` after the page had already warmed GIS hung
  forever - the real popup opens and nothing resolves it. Stub
  `window.google.accounts.oauth2.initCodeClient` to fire the callback instead, or block
  `**accounts.google.com/**` from before `goto`.
- Clicking `.google-btn` in a fresh context times out: the sign-in screen and the nudge
  itself cover it. Dismiss `.signin-later` and `.nudge-ok` first.
- `pkill -f "vite --port 5199"` returns exit 144 and kills the rest of the compound command
  with it. Run it alone.

## Next Step
Nothing is pending. The work is shipped and verified.

Follow-ups, in order of value:
1. Look at the popup on a real phone (rosa.surf, fresh profile) - every check so far was
   headless at 390px.
2. Decide whether the copy should read "missing **a** break?" - the user's message quoted it
   with the "a", the shipped copy has no "a". One word in
   `web/src/components/ReportNudge.tsx`, and the same line in the Figma frames.
3. Work out why rosa.surf renders light when the browser is set to dark. Start at
   `web/src/theme.ts` (`initialTheme`) and the `rosa.theme` key; local dev was correct, so
   suspect the stored value or the prefers-color-scheme fallback on a first visit.
