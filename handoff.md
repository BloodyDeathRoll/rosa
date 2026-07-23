# Rosa — Session Handoff (rewritten 2026-07-23 after full project review)

> **READ THIS WHOLE FILE, THEN CLAUDE.md, BEFORE ACTING. On any infra task, inspect the live
> system FIRST (SSH/curl/console) — never trust snapshots, including this one, for IPs or
> machine state.** This file was rewritten from scratch because a stale handoff caused a real
> incident (see "Process lessons" at the bottom).

## What Rosa is (one line)
Worldwide mobile-first PWA surf forecast: precompute everything on a schedule → static JSON on
a CDN → thin Preact client. Free forever. Product truth: `CLAUDE.md`; blueprints:
`docs/rosa-build-plan.md`, `docs/rosa-surfline-teardown.md`.

---

## INFRASTRUCTURE — live systems (all verified working 2026-07-23 ~09:00 UTC)

### Oracle VM — THE single scheduler (no GitHub Actions, no systemd — do not re-add either)
- Instance **`rosa-instance`**, il-jerusalem-1, Ubuntu 24.04 **x86_64**, account "einhanamer".
- **Public IP `82.70.218.149`** — the older `82.70.217.50` is **DEAD, never use it**. If SSH
  times out, check the Oracle console for state/current IP before concluding anything.
- SSH (from repo root): `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149`
- **Converged design** (2026-07-23, after two parallel sessions built competing variants):
  - crontab: `20 2,8,14,20 * * * /home/ubuntu/rosa/deploy/oracle/publish.sh`
  - `deploy/oracle/publish.sh` (canonical, in-repo) = `git pull` → `uv sync` →
    `rosa-pipeline archive` (buoy lead-time truth → `~/rosa/data/verify/archive/*.jsonl`,
    seeded 2026-07-23 with the 20,736 rows from the retired GH-Actions archive) →
    `rosa-pipeline run --all` (81 spots) → prebuilt Vercel deploy of `data/out` to
    **rosa-data** (CORS + 5-min cache on `/data/*`). Appends to `~/rosa/publish.log`.
  - `~/rosa` is a **git clone of main** (read-only deploy key `rosa-oracle-vm`) — pushes reach
    the box on its next cycle; `data/` + `.env` are gitignored so pulls never touch them.
  - `~/rosa/.env` (chmod 600): `VERCEL_TOKEN`. `~/rosa/publish.sh.pre-git` = retired copy, ignore.
  - Verified end-to-end 08:50Z: archive +3,456 rows, publish aliased, CDN advanced.
- Frankfurt ARM grabber (`deploy/oracle/grab-arm-frankfurt.sh`, laptop `~/grab.log`): **stopped**
  (last attempt 03:06Z, out of capacity). Moot now the x86 box works.
- Still-open nicety: move `web/.oracle/` keypair to `~/.ssh/` (gitignored + outside web/public,
  so not urgent).

### Vercel (account `bloodydeathroll`, org `team_jeHaUEFEe9q9CoUA71Vij1Kr`)
- **`rosa`** (`prj_byWctijqaVdOWxFOi5s0Z2E9I5kf`) — the app, https://rosa-rust.vercel.app.
  Deploy ONLY via CLI: `cd web && npm run deploy`. Git integration deliberately DISCONNECTED.
- **`rosa-data`** (`prj_yYmy2goOnyzwPquNauvg96zxkOhD`) — forecast CDN,
  https://rosa-data-opal.vercel.app — published by the VM cron. App reads it via
  `VITE_DATA_BASE` (`web/.env.production`, committed on purpose). Local dev serves same-origin
  `/data/` via sync-data.
- Freshness check: `curl -s https://rosa-data-opal.vercel.app/data/index.json | python3 -c "import json,sys; print(next(iter(json.load(sys.stdin)['spots'].values()))['generated_at'])"`

### Secrets (all gitignored — `git check-ignore` anything doubtful before staging)
- Root `.env.local`: **`VERCEL_TOKEN`** (real API token, validated), `GOOGLE_MAPS_API_KEY`.
- `web/.env.local`: only a stale `VERCEL_OIDC_TOKEN` — NOT an API token, don't use.
- VM `~/rosa/.env`: `VERCEL_TOKEN`. — SSH key: `web/.oracle/ssh-key-2026-07-23.key`.

### GitHub (`github.com/BloodyDeathRoll/rosa`, private)
- **Zero workflows** — `.github/` deleted 2026-07-23; scheduling is VM-only.
- Branch `data` = the retired GH-archive seed (Jul 22–23), already merged onto the VM disk;
  kept only as a backup copy. `gh` CLI is authenticated on the laptop.

---

## PIPELINE (`pipeline/`, Python/uv) — further along than CLAUDE.md admits
**157 tests green** (`cd pipeline && uv run pytest`). CLI:
`uv run --project pipeline rosa-pipeline <run|verify|archive|feedback|bathy>`.

- **Accuracy-roadmap Stage 2 is mostly DONE** (truth: `docs/rosa-stage2-plan.md`): hybrid
  physics transform (`physics.py`: dispersion → shoaling Ks → Snell refraction Kr → γ=0.78
  depth-limited breaking, marched over per-spot depth profiles in `data/spots/derived/bathy/`
  [82 committed] × `period_rideability`, the grounded reframing of q(T)); soft exposure window
  (25° cosine shoulder past `swell_window`); **tide from Open-Meteo `sea_level_height_msl`**
  (NOT EOT20 — approach changed 2026-07-22), feeding breaking depth AND published per-hour.
- **⚠️ CLAUDE.md IS STALE HERE**: its algorithm section still presents plain q(T) as the
  transform and says nearshore physics is "v2 — don't start"; its session log ends at
  SESSION 3 (2026-07-20). For the transform, `rosa-stage2-plan.md` + code are the truth.
  Update CLAUDE.md rather than "implementing" its old spec. (Flagged, not yet done.)
- `verify --buoy <id>` = nowcast skill vs NDBC obs; `--archive` = lead-time skill (needs the VM
  archive to mature — ~1 week from 2026-07-23). `archive` = what the cron appends.
- Fetch = Open-Meteo Marine+Weather, ONE fetch per unique offshore point (OM throttles
  per-spot bursts). Fixtures in `pipeline/tests/fixtures/` keep tests offline.

### Calibration (log: `docs/CALIBRATION.md` — READ before touching any constant)
- Rows 1–2 (Jul 19–20, Israel/Med): q exponent → 1.4, wind-gate denominator → 60.
- **2026-07-23 first multi-region buoy sweep** (6 NDBC stations): Open-Meteo Hs runs HOT
  everywhere, worst in the Pacific (+0.23–0.41 m, SI to 0.37); Pacific period ~+3 s hot →
  **Costa Rica over-called on BOTH axes (compounding — explains the generous "Epic" at
  Tamarindo)**; Atlantic tight; **Sri Lanka has no buoy anywhere — unvalidatable**. NO knobs
  changed (n=6–7, July = Pacific flat season; per methodology, constants move only on
  accumulated evidence). Pre-registered plan: archive matures → confirm bias per lead-time →
  input-side de-bias in extract, refitting Israel simultaneously (its constants were tuned WITH
  the hot input — de-biasing alone would double-correct it). Interim per-spot `height_coeff`
  on CR allowed but deliberately not applied.

---

## WEB (`web/`, Vite+Preact PWA, TS strict) — after the 2026-07-23 UI session
Prod deployed at `df834fe`; `tsc --noEmit` clean; dev server currently stopped
(`cd web && npm run dev` — add `-- --host` for phone testing on LAN).

Shipped today (`4aea2e5`, `df834fe`):
- **Map tab, Surfline-style rebuild**: full-bleed maplibre (⚠️ the canvas MUST have an explicit
  CSS height — a flex/absolute-only canvas measures 0 and renders blank; this bit us twice),
  floating back/search FABs, attribution top-left, no zoom buttons. **Viewport-synced
  carousel**: cards = spots visible on the map MINUS those hidden under the bottom sheet
  (`SHEET_H = 156` const in MapPage must track the sheet's real height). Screen-space
  clustering (46 px) with conic tier-blend rings; the focused spot's dot becomes a surf-range
  pill; card tap → spot page; carousel scroll ↔ map focus both ways. Satellite imagery on
  cards capped to focus ±2 (`IMG_WINDOW`). Search OVERLAYS the live map — unmounting the map
  orphans the maplibre instance (was a real bug). Cards: flat scrim `#ffffffcc` light /
  `#000000cc` dark, themed text, spot name directly above the surf value.
- **Spot page**: `DayScrubber` (in `components/CoastChart.tsx`) replaced DateBar + DayCarousel
  (both DELETED) — each column = date label stacked over that day's 3 bars in ONE track, so
  they drag as a unit; edge-to-edge, `COL = 56` must equal `.day-col` CSS width; leftmost
  day = selected; live `onScrub` re-renders the forecast panel instantly (no second scroller —
  the two-scroller design caused the lag/desync the user rejected). Bars condense to a
  date-only row on page scroll (hysteresis 72/24 px). Last ~6 days are tap-only (can't reach
  the left edge) — accepted trade-off.
- **Dates anchor to the spot's real today** via `todayIn(tz)` (`format.ts`) in THREE places —
  TodayPage, SpotPage, SpotsPage — dropping past days from stale runs. Keep any new date strip
  on the same helper.
- Deleted dead code: DateBar.tsx, DayCarousel.tsx, `Spark` (parts.tsx), `.range-row .spark` CSS.

### Open web TODOs
1. **TIDE IS STILL THE MOCK** (`components/TideSection.tsx`: hardcoded M2 sine + "High 14:20").
   The pipeline now publishes a real per-hour `tide` series (verified in payloads) but
   `web/src/types.ts` doesn't declare it. Wiring real tide (+ real high/low extraction) is the
   obvious next web task; the "keep the mock" instruction predates real data and is void.
2. Leftover dead CSS: `.coast-bars`, `.rank-n` (0 usages). Consider kph/short wind on SpotCard.
3. ⚠️ After any `npm run build`/`deploy`, RESTART a running dev server — sync-data wipes
   `web/public/data` under vite and the app then serves the SPA-fallback HTML for
   `/data/index.json` → "JSON.parse: unexpected character" (this happened; that's the cause).
4. Design system: the session-3 "Uptake" handoff (warm cream/clay, Inter, FIRING→"Epic") is
   CURRENT; `docs/rosa-conditions-color-system.md` is historical.

## SPOT DB (`data/spots/*.yaml`) — 81 spots: Israel 40, Costa Rica 25, Sri Lanka 16
- Spots are inline-map lists (`- { id: ..., <<: *anchor }`) — count with `grep -c "id:"` care.
- Authority ladder (tags per spot): user-verified > sat-verified > OSM > google-geocoded >
  approximation. Herzliya cluster is user-verified gospel. Never import competitor data.
- Sat-verification tooling exists: `tools/spot-verify/` (ESRI crosshair tiles, headless shots;
  method + planned Dream assignment in `docs/spot-mapping-approach.md`).
- Worldwide strategy (decided, `docs/spot-db-research.md`): open ODbL dataset seeded from
  Overture + broad-OSM + Wikipedia; WannaSurf = licensing target; the naotokui 6k-spot gist is
  a TRAP (no provenance — never ingest).

## DOCS INDEX (which doc is authoritative for what)
- `CLAUDE.md` — product principles, legal red lines, conventions (⚠️ algorithm + session-log
  sections stale, see PIPELINE).
- `docs/rosa-accuracy-roadmap.md` — THE staged accuracy plan. Stage 0 harness ✅, Stage 2
  mostly ✅, Stages 1/3/4/5 open. Also: scale posture (read-path stays static/CDN forever;
  write-path → Supabase when users demand it; archive → object storage) + free-tier stack.
- `docs/rosa-stage2-plan.md` — Stage-2 implementation truth (2A–2D DONE, 2E recalibration open).
- `docs/CALIBRATION.md` — calibration log + buoy-only methodology. Append, never tune silently.
- `rosa-forecast-improvements.md` (repo root) — Surfline-methodology study; superseded by the
  roadmap but its #1–#8 item numbers are referenced there.
- `docs/spot-db-research.md` / `docs/spot-mapping-approach.md` — spot-DB strategy + sat loop.
- `docs/rosa-surfline-teardown.md` / `docs/rosa-build-plan.md` — original blueprints.

## WHAT'S NEXT (agreed at session end)
1. **Wait for the VM archive to mature (~1 week from 2026-07-23)**, then
   `verify --buoy <id> --archive` → confirm the Pacific hot-bias per lead-time → the real
   tuning pass (input de-bias + Israel refit + γ/rideability/residual, i.e. Stage 2E). This is
   deliberately blocked on data, not effort — don't "tune" earlier.
2. **Web: wire the real tide series** into TideSection (types.ts + component + high/low).
3. Worldwide spot-DB scale-up (ODbL seed) — sequenced AFTER calibration per user decision;
   automation (its prerequisite) is now done.
4. Update CLAUDE.md's algorithm section + session log to Stage-2 reality (flagged above).

## PROCESS LESSONS — the reason this file is exhaustive. DO NOT REPEAT.
1. **2026-07-23 incident**: this session designed and shipped a systemd + GitHub-Actions
   automation for the Oracle box from a stale handoff (dead IP, "bare Ubuntu") while the
   user's PARALLEL session had already provisioned a working cron on the real box. Claude
   contradicted Claude; the user was rightly angry. Rule: **inspect live infra before designing
   for it; "unreachable + stale snapshot" means STOP AND ASK, not build.**
2. The user runs **parallel Claude sessions**. `git log`, the VM, and the CDN can all have
   moved under you — check them, and treat this file as a lead, not gospel.
3. Auto-memory `oracle-vm.md` holds the VM facts — update it whenever infra changes.
4. Environment-shape bugs to remember: maplibre needs an explicitly-sized container (blank map
   ×2); sync-data under a live dev server serves HTML as JSON. Check the environment before
   debugging the code.
