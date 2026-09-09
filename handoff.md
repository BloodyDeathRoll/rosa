# Session Handoff - 2026-09-08 (late evening)

## Goal
Give the Rosa web app a real desktop layout in Surfline's site structure (top nav, search,
account, favorites ticker, cards in a row, forecast beside conditions) in Rosa's own look,
reviewed on localhost and then shipped.

## Current State
DONE, committed as `5a6d2d1` on `main`, pushed, deployed to production (rosa.surf serves the
new build; verified the live HTML references `splash_16-9.png`). Working tree clean.

- Above 900px (`web/src/desk.ts` DESK_MQ, mirrored by the DESKTOP block at the end of
  `web/src/styles.css`) the app is a full-width page: sticky top bar
  (`components/DesktopBar.tsx`: brand, Today/Spots/Map/Charts links, search field that
  opens `#/search`, avatar into Profile) + favorites ticker (tier dot, name, today's range).
  Pill nav hidden. Document scrolls at every width (phone frame is gone).
- Today: cards in an auto-fill grid; coast chart shows every day across the row.
- Spot: 34px title, days spread across the row, hourly table under the days on the LEFT
  (`.spot-hours` wrapper), cam then rating card, tide, sun in a 420px RIGHT column. Pinned
  header shrinks to 22px when scrolled.
- Map: full width, card carousel in a band UNDER the map (not over it), focused card
  outlined. Search overlays the map, field + results in the 760px column.
- About pages: hero `position: fixed` on the viewport's left half flush with the edge,
  body in grid column 2 on the right.
- Spots / Profile / Search: 760px reading column; `AppHeader` has a `title` prop for the
  desktop heading.
- Phone layout verified pixel-unchanged at 390px. `tsc` clean, production build passes.
- User signed in on localhost and reviewed every screen before saying "Awesome. Commit".

Not verified: a 1024px window with the map band (only Today checked at 1024); the About
hero on very short windows (fixed hero height is `100dvh - --desk-top`).

## Active Files
- `web/src/desk.ts` - NEW, the one breakpoint (`DESK_MQ`, `isDesk()`).
- `web/src/components/DesktopBar.tsx` - NEW, top bar + favorites ticker.
- `web/src/styles.css` - DESKTOP block rewritten (was the phone-in-a-frame); `.signin-screen`
  16:9 splash media query.
- `web/index.html` - 16:9 splash media query.
- `web/public/splash_16-9.png` - user-supplied 2521x1418 PNG, 3.9 MB, used on wide
  landscape screens.
- `web/src/app.tsx` - renders DesktopBar, shared `active` tab computation.
- `web/src/pages/SpotPage.tsx` - `.spot-hours` wrapper around day title + table.
- `web/src/components/CoastChart.tsx` - `--days` on `.coast`; scrubber column width measured
  from the DOM (`colW`) instead of the 56px constant.
- `web/src/pages/MapPage.tsx` - `isDesk()` drops the sheet's bottom-strip exclusion;
  `.sheet-title` (desktop only).
- `web/src/components/parts.tsx` - `AppHeader` `title` prop; `SpotsPage.tsx` /
  `SettingsPage.tsx` pass it.
- `web/src/scroller.ts` - comment only (frame gone).
- `docs/UI.md` (Desktop paragraph), `docs/SESSIONS.md` (session entry).

## Changes Made This Session
1. Read Surfline screenshots + existing web code; replaced the desktop phone-frame block
   with a full-width layout. Kept the warm-clay tokens; nothing changes what a screen says,
   only where it sits.
2. Review round 1 (user): map search results unreachable, spot columns wrong way round,
   coast chart bars missing, 16:9 splash. Fixed: Search-page desktop rules had leaked into
   the map overlay (scoped to `.page:not(.map-page)`); columns swapped to forecast-left;
   `.chart-plot` width `calc(var(--col-w) * 0.84)` re-resolved the row-share `%` against
   the column - now `84%` on desktop; splash wired.
3. Review round 2: dates showed Aug 23 - the local `data/out` is a stale run and dev copies
   it; dev server now runs with `VITE_DATA_BASE=https://rosa-data-opal.vercel.app`. Map
   sidebar replaced by a carousel band under the map (user's call). About pages went
   two-column (user's call, after a demo from another project), then fixed + flush-left.
4. Sign-in on localhost failed twice for env reasons: Google's OAuth client allows
   `localhost:5173` not `127.0.0.1`; `.env.development` points `VITE_USER_API` at a local
   Worker (`localhost:8787`) that was not running. Dev run with the live Worker URL.
5. Commit + push + `npm run deploy` (prebuilt, prod) on "Commit".

## Failed Attempts
- Spot page first cut put the cam on the LEFT above the table (cam pushed the forecast down
  a screen). Rejected by the user; forecast must sit straight under the day selector.
- Map first cut was a 380px sidebar list. Rejected; user wants full-width map with the
  carousel below.
- About hero as `position: sticky` inside a centred 1440px column left a gutter on the
  left; fixed positioning flush with the viewport edge was required. Making the hero fixed
  pulled it out of the grid flow and the body vanished under it until `.about-body` was
  given `grid-column: 2` explicitly.
- A blanket `.spot-back { display: none }` for the spot header also hid the map search's
  close button; scoped to `.spot-top .spot-back`.
- `pkill -f vite` killed the shell running it (the command line matched); restart with
  `pgrep -fa vite | ... | xargs kill` instead.

## Next Step
1. Optional, flagged to the user, not asked for: `web/public/splash_16-9.png` is 3.9 MB
   (phone splash.jpg is 160 KB). A JPG export would cut first paint on desktop.
2. Consider making dev point at live data + the live user API by default
   (`web/.env.development`: `VITE_DATA_BASE`, `VITE_USER_API`) - every review this
   session needed both overrides. Ask before changing.
3. Check the map band and About hero at 1024x700 and a short window; `isDesk()` and the
   DESKTOP media query must stay in step if the breakpoint ever moves.
4. Dev server for review: from `web/`,
   `VITE_DATA_BASE=https://rosa-data-opal.vercel.app VITE_USER_API=https://rosa-user-api.einhanamer.workers.dev npm run dev -- --host localhost --port 5173`
