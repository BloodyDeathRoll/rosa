# Session Handoff — 2026-10-24

## Goal
Operator report (five phone screenshots): on the Charts page, rotating the map with two fingers turned the basemap but the swell field and arrows stayed north-up. Find and ship a fix.

## Current State
- Fixed, committed on main (`136adf3`), deployed to rosa.surf, operator confirmed on the phone.
- Pitch (tilt) is now disabled on the Charts map. Rotation works.
- `docs/SESSIONS.md` has the 2026-10-24 entry. `docs/OPEN-ITEMS.md` not touched (nothing opened or closed).
- The SESSIONS entry and this handoff are committed by the handoff commit.

## Active Files
- `web/src/pages/ChartsPage.tsx` - the draw loop (`draw` inside the frame effect) and the `maplibregl.Map` options.
- `docs/SESSIONS.md` - 2026-10-24 entry.
- `web/.vercel/project.json` (untracked, gitignored) - copied from `~/Projects/rosa/web/` so this worktree deploys to the `rosa` project, not a stray one.

## Changes Made This Session
1. Diagnosis: the overlay computed x from `m.project([lon,0]).x` and y from `m.project([0,lat]).y`. That separation only holds at bearing 0.
2. Fix in `draw`: positions come from an unrotated mercator plane (`worldW = 512 * 2 ** zoom`, `mercY(lat)` = MapLibre's `mercatorYfromLat`, both relative to `m.project(m.getCenter())`), and both the field context and the arrow context are rotated by `-bearing` around the screen centre. Sign verified in `node_modules/maplibre-gl/src/geo/projection/mercator_transform.ts` (`rotateZ(m, m, -this.bearingInRadians)`).
3. Culling bounds changed from `[0,W]x[0,H]` to the rotated screen's bounding box (radius `hypot(W,H)/2` around the centre) so rows and arrows are not dropped at the corners after rotation.
4. The field-to-screen composite is done with the transform reset (the field canvas is already in screen space).
5. `maxPitch: 0`, `pitchWithRotate: false` on the map: a 2D canvas cannot do perspective, so tilt is off rather than wrong.
6. `npx tsc --noEmit` clean, `vitest` 47/47. Committed, pushed, `npm run deploy` in `web/` (production, aliases rosa.surf + www).

## Failed Attempts
None. The worktree had no `.vercel/project.json`; copying the one from `~/Projects/rosa/web/` fixed the link before deploying (memory: worktrees can land on a stray "web" project).

## Next Step
Nothing pending from this session. If rotation looks off at high latitude, compare `yOfLat` in `web/src/pages/ChartsPage.tsx` against `m.project([lon, lat])` at bearing 0 in the browser console (they must match to the pixel); the formula is MapLibre's own.
