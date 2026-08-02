# Rosa - conditions color system (dark + light themes)

> **HISTORICAL (superseded 2026-07-20).** The session-3 "warm clay" design handoff (warm
> cream/clay, Inter, FIRING→"Epic") replaced this zine system and is what `web/` implements.
> Kept for context only - do NOT implement from this file. See CLAUDE.md §UI.

Directions for this session. We are implementing Rosa's theme system and the 5-tier condition color coding. Read this whole file before writing code.

## Brand context (do not violate)

Rosa's visual direction is raw / lo-fi: monospace for all data, blunt verdict-first copy, one signal red accent. **Dark is the default theme** - the app is checked at 5am in the dark. Light theme exists for daylight readability but keeps the same attitude: paper-and-ink zine, not friendly pastel. The condition scale is a **functional data layer**, not decoration - it is the only place multi-color is allowed. Everything else stays base / ink / gray / signal red.

The tier-1 red reuses the brand red in each theme so red remains a single, unambiguous signal: red always means "bad / don't bother / alert."

## Base theme tokens

| Token | Dark (default) | Light |
|---|---|---|
| `--bg` | `#1A1A1A` | `#F1EFE8` |
| `--bg-raised` | `#242424` | `#FFFFFF` |
| `--ink` | `#F1EFE8` | `#1A1A1A` |
| `--ink-secondary` | `#B4B2A9` | `#5F5E5A` |
| `--ink-muted` | `#888780` | `#888780` |
| `--rule` | `#444441` | `#D3D1C7` |
| `--signal` | `#E24B4A` | `#C93532` |
| `--on-signal` | `#F1EFE8` | `#F1EFE8` |

Light mode background is bone paper, not pure white - pure white kills the zine feel. Raised cards go white on light so hierarchy still reads.

## Condition scale - both themes

Five tiers, worst to best. Dark hexes are brightened for `#1A1A1A`; light hexes are darkened for `#F1EFE8`. Do not swap them or "average" them.

| Token | Tier | Dark | Light | Verdict register (examples) |
|---|---|---|---|---|
| `--cond-1` | Blown / flat | `#E24B4A` | `#C93532` | "Go home." / "It's a lake." |
| `--cond-2` | Poor | `#EF8A3C` | `#C56A1B` | "Junk. Desperation only." |
| `--cond-3` | Fair | `#E8C547` | `#9C7E0E` | "Rideable. Manage expectations." |
| `--cond-4` | Good | `#8FCE5A` | `#4E8A1F` | "Go." |
| `--cond-5` | Firing | `#23A05C` | `#146C43` | "Drop everything." |

Yellow is the hard one: on dark it must be bright (`#E8C547`); on light it must be pulled way down toward olive (`#9C7E0E`) or it disappears against paper. Resist the urge to keep them similar.

Also define muted companions (`--cond-N-dim`) for fills behind sparkline segments and chart bands: 25% opacity of the tier color on dark, 15% on light (light backgrounds tint faster). Dim variants are fills only - never text or dots.

## Theme implementation

- Declare all tokens as CSS custom properties on `:root` (dark values), with a `[data-theme="light"]` override block on `html`. Components reference tokens only - **zero raw hexes outside the two theme blocks.**
- Respect the OS: initialize from `prefers-color-scheme`, but let the user override in settings, persisted. Rosa's default when the OS expresses no preference is dark.
- Centralize the rating→token mapping in one function/module (e.g. `conditionColor(rating: 1..5)` returning `var(--cond-N)`), so components never know which theme is active.
- The rating comes from the forecast engine as an integer 1-5. Never interpolate between tier colors - conditions are discrete verdicts, not a gradient. A chart segment is one tier's color until the rating changes.
- Theme switch must not flash: set `data-theme` before first paint (inline script in `<head>`).

## Where the colors appear

1. **Spot list**: one small dot (8px) per spot, left of the spot name. Dot only - row text stays `--ink` / `--ink-secondary`.
2. **Verdict line**: headline stays `--ink`. A thin (3px) left rule in the tier color sits next to it. Never color the headline text itself.
3. **24h sparkline**: stroke each time segment in its tier color; optional `--cond-N-dim` fill below the line.
4. **Alert badges / notifications**: tier color as badge background. Badge text: `#1A1A1A` on tiers 2-4 dark theme; `#F1EFE8` on tier 1 (both themes) and on all tiers in light theme (light-theme tier colors are dark enough to carry bone text). Verify each combination at 4.5:1 - if one fails, adjust the text side, not the tier hex.
5. **Week strip**: seven small squares, one per day, tier-colored, monospace day labels in `--ink-muted` underneath.

Nowhere else. If you're tempted to tint a card background or nav element with a tier color, don't.

## Accessibility - non-negotiable

- Never rely on color alone. Every color-coded element pairs with text or a glyph: dots sit next to a mono rating label (`1/5` … `5/5`), sparkline segments have the verdict nearby, badges contain text.
- Red/green confusion: tiers 1 and 5 must be distinguishable without hue - tier 1 pairs with "×" or a down glyph, tier 5 with "✓" or an up glyph in badges and the week strip. Tabler outline icons, not emoji.
- Contrast: every tier hex must pass 3:1 against its theme's `--bg` for graphical elements; badge text combinations must pass 4.5:1. Run the check in both themes before calling it done.
- Respect `prefers-reduced-motion` for any pulsing indicators (e.g. "firing right now"). Static fallback: same color, no pulse.

## Voice coupling

The tier drives copy, not just color. Verdict strings live in a `verdicts` map keyed by tier, 3-5 rotating variants each so it never feels canned. Register: blunt, dry, honest. Sentence case; exclamation marks only ever on tier 5, and sparingly. Voice does not change between themes.

## Definition of done

- Both theme blocks declared once; mapping function centralized; zero stray hexes.
- Spot list, verdict rule, sparkline, badge, and week strip all consume tokens and render correctly in both themes.
- No flash of wrong theme on load; OS preference respected; manual override persists.
- Contrast checks pass in both themes; glyphs present on tier 1 and 5 indicators.
- Quick visual check at 320px width in both themes: dark at "5am dawn patrol" and light at "beach parking lot, full sun."
