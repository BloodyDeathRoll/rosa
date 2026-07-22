# Session Handoff — 2026-07-23

## Goal
UI polish pass on `web/`: build a MagicSeaweed-style forecast chart on Today,
restructure Search/Spots, rebuild the Map tab (tabs + list + in-map search), add
region group-chips to Favorites & Map, redesign the compact spot card, and flip
the splash image. All frontend-only.

## Current State
All below builds clean (`cd web && npx tsc --noEmit` → 0; dev server on
`localhost:5173` serves everything 200). **Nothing committed or deployed.**
- **Today chart** (`CoastChart`): 3 daypart bars/day (morning·midday·evening),
  bars colored by the day's condition tiers (teal experiment reverted), plain
  surf-value text below (10.5px/600), no bottom rule, card-less rows, 50px cols.
  It is the ONLY forecast view (list toggle + `CoastGrid` removed).
- **Search** = its own focused screen (`#/search`, `SearchPage`): autofocused
  field with a right→left `clip-path` open animation, recents when empty,
  card-less results with an inline fav star. Search icon on Home & Spots → `#/search`.
- **Spots tab** = favorites only, grouped by a Surfline-style region chip bar
  ("All" + one chip per region), redesigned cards.
- **Map tab** rebuilt to: header (logo+search) · Favourites/Nearby underline tabs ·
  map (upper half, `calc(50dvh-78px)`) · scrolling spot list (fav star + distance).
  Tabs sit ABOVE the list; map+tabs fixed, only the list scrolls
  (`.map-screen` height-bounded to viewport). In-map search centers the map on a
  result (never opens the spot). Group chips under the tabs on the Favourites tab.
  Map load made instant: fetch index → render shell → `signalReady()` BEFORE
  importing maplibre + geolocation.
- **Compact card** (`SpotCard`) redesigned: title + rating pill (line 1),
  surf range + wind (line 2), fav star pinned right. Used only on Spots now.
- **Spot screen** now shows the bottom nav (no tab lit; it's "deeper" than a tab).
- **Splash image** (`web/public/splash.jpg`) mirrored: woman left / surfboard right.
- **Icons** (favicon/icon/icon-maskable): committed earlier (`bb22cac`, `561a876`).
- **CALIBRATION.md** honesty note: committed (`84d534b`).

## Active Files
- `web/src/components/CoastChart.tsx` (NEW) — MSW daypart bar chart for Today.
- `web/src/components/GroupChips.tsx` (NEW) — `groupsOf()` + `<GroupChips>` region bar.
- `web/src/pages/SearchPage.tsx` (NEW) — focused search screen with recents.
- `web/src/components/CoastGrid.tsx` (DELETED) — old list view, fully removed.
- `web/src/pages/MapPage.tsx` — full rebuild (tabs/list/in-map search/group chips/instant load).
- `web/src/pages/SpotsPage.tsx` — favorites-only + group chips + new cards.
- `web/src/pages/TodayPage.tsx` — renders only `CoastChart`; search icon → `#/search`.
- `web/src/components/SpotCard.tsx` — new 2-line layout, star right (dropped Spark + km).
- `web/src/app.tsx` — `#/search` route; nav shown on spot pages; `TabBar active: Tab|null`.
- `web/src/styles.css` — chart, group chips, card, map layout, search-head/anim.
- `web/public/splash.jpg` — horizontally mirrored.

## Changes Made This Session
Order: (1) MSW chart built as secondary→promoted to primary→sole view; iterated
bar count (hourly→3 dayparts), color (tier→single teal→back to tier), removed the
day-condition bottom rule, card-less rows, tighter columns, no header border.
(2) Split Search into `#/search`; Spots became favorites-only. (3) Map rebuilt to
the MSW screenshot layout; multiple iterations on tab position, half/half sizing,
scroll containment, in-map search behavior. (4) Bottom nav added to spot screen
(user chose "bottom tab bar" from options). (5) Favorites/Map region group chips +
"All". (6) SpotCard redesigned. (7) Splash flipped. (8) Map instant-load via early
`signalReady()`. Design decisions driven by user screenshots (MSW) each step.

## Failed Attempts
- **Splash flip via `sharp` CLI**: first `flop` wrote output to the SAME path as
  input (`-o "$SCR/"` + same basename) → overwrote the backup in place, so repeated
  flip attempts netted an EVEN number of flips = original orientation ("not
  mirrored"). Fixed with Python PIL `FLIP_LEFT_RIGHT` and verified by pixel compare
  (red skirt now at x≈0.36). Lesson: never point sharp `-o` at the input's dir.
- **`sharp` `flop` appeared to "do nothing"**: the Read-tool image previews were
  cached, showing identical images for orig/flipped — trust pixel checks, not previews.
- **Nested `<button>` in map/card rows**: a `StarButton` (button) cannot nest inside
  a row `<button>`. Map rows split into a `.map-loc-main` select-button + sibling
  star; card rows are `<a>` (star-in-anchor is valid).
- **Splash-on-map "bug"** the user reported (search→click spot→splash→back to map):
  could NOT find a reload trigger in code (no `<form>`, no `location.reload/href`,
  clicks don't navigate). Most likely a Vite dev HMR full-reload during editing.
  Mitigated by making the map lift the splash instantly regardless.

## Next Step
1. Visually verify on the phone (`http://192.168.1.133:5173/`), esp. Map half/half
   + group chips, and the new Spots cards.
2. Commit in focused chunks, then deploy: `cd web && npm run deploy` (CLI-only prod).
   Suggested commits: chart(Today), search/spots split, map rebuild, card+groups,
   splash flip, spot-screen nav.
3. Optional cleanup: delete now-unused `Spark` in `web/src/components/parts.tsx`;
   strip dead `.coast-cell/.coast-bars/.rank-card .side/.rank-n` CSS.
4. Watch: wind on the new card uses `windLabel` (`SW 4 kt offshore`) — user may want
   kph / shorter. Group-chip default is "All".
5. Unrelated background: Oracle A1.Flex grabber (`~/grab.log`) still looping for
   Frankfurt capacity — not this session's work; leave running.
