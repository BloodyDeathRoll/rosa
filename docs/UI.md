# Rosa — UI spec (web/)

Read this before touching `web/`.

**Design system: "warm clay"** — warm cream/clay tokens, Inter (@fontsource-variable), light + dark themes (dark default), FIRING displays as **"Epic"**. All hexes confined to the two theme blocks in `styles.css`; tier colors only in the condition layer. Roomy and cozy, generous spacing, no decorative borders on cards. (`docs/rosa-conditions-color-system.md` is the older zine system — HISTORICAL, do not implement from it.)

Shell: **Today | Spots | Map | Profile**.
- **Today** — region chips + `planToday()` (chips from where you are + favorites + the ONE last-viewed spot; ≥5 spots per region; anchor leads; payloads load per region).
- **Map** — full-bleed MapLibre + viewport-synced card carousel (cards are exactly the spots visible on the map, minus those under the sheet), screen-space clustering with tier-blend rings, focused-spot surf-pill dot, search overlaid on the live map, locate + rotating-north fabs. Lazy-loaded, excluded from PWA precache; OpenFreeMap vector basemaps by theme - keyless (attribution required).
- **Spot page** — one-row header, DayScrubber (date label over that day's 3 bars, one draggable track, leftmost = selected, live re-render on scrub, bars condense on scroll), rating card, hourly grid (wind in knots), TideSection from the real per-hour series, "Other nearby spots" strip.
- All date strips anchor to the spot's real today via `todayIn(tz)` and drop past days.

**DESIGN RULE: swell events surface ONLY as push notifications.** The forecast itself is the in-app surface. Do not rebuild event banners, cards, or alert strips — they were built and killed on review.

**Push.** One swell = ONE notification: same region + peaks ≤12 h + dirs ≤45° cluster into a single push named for the best favorited spot "+N more"; sent-state carries ±1-day peak-drift tolerance; browser tag is a 2nd dedup layer. Notification tap deep-links `#/spot/{id}?ev=YYYY-MM-DD`. Opt-out must be clear and failures surfaced, never silent. iOS needs A2HS + a user gesture.

**Feedback ask is two steps:** "Surfed X?" ✓/✗ first, thumbs only on yes. Selection never crosses regions (the device sends its nearest spot id, never coordinates). Asked at most once a week, only about a GOOD-or-better day, and only for the favorite spot closest to the user's current location (2026-08-20).

**Period display ≠ scoring** — the swell readouts show the PEAK period while `period_score` and the shoaling march run on the mean. Deliberate; see `docs/ALGORITHM.md`. Disclosed at `#/about/reading`.

Data-point glossary lives in `AboutPage.tsx` → `ReadingTheForecast` (`#/about/reading`) — **keep in sync when a displayed field changes.**
