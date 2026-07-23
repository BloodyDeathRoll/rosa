# Session Handoff — 2026-07-23 (session 7, PM)

## Goal
Build accuracy-roadmap Stage 3b (ECMWF spectral-lite: second wave member, missed-swell
guard, consistency proxy, parametric spread + measured validation), then parallel tracks
while VM archives mature: swell-event detection, web rendering of the new fields, CDIP
spread arbitration, and free-tier infra expansion (backup micro + A1 hunt).

## Current State
Everything built this session is committed, pushed, and deployed. 203 pipeline tests
green, ruff clean, web TS clean. Standing rule (from a real incident): on any infra
task, inspect the live system first (SSH/console) — never trust this snapshot for IPs
or machine state.

- **3b member live in production**: `ecmwf.py` fetches ECMWF open data by index +
  byte-range (11 params ≈ one ~10 MB range/step, 41 six-hourly steps to 240 h, 00z/12z
  cycles, 9 h lag). Payload carries per-hour `spectral{consistency,missed[]}`, per-swell
  `spread`, `spectral_meta`, ECMWF CC-BY attribution; ECMWF swh = 5th agreement member.
  Guard already caught a real unaccounted 10–12 s band on 2026-07-25 at Beit Yanai
  (the old calibration watch-item date). `run` is ~2 min slower (shared global fetch).
- **3-way buoy A/B running**: `archive --wave-source all` (VM default via git pull,
  verified live 11:09 UTC cycle) writes `<buoy>.ecmwf.jsonl` (hs / tp=pp1d↔DPD / mwd
  + mwp/mp2 for the consistency model-leg). `verify --archive --source ecmwf` works.
- **Spectra harness done + first verdicts** (`spectra.py`, `verify --spectra`):
  NDBC `.data_spec`/`.swr1` → moments (Tp/Tm-1,0/Tm02, Goda Qp), σ=√(2(1−r1))@peak.
  12-station ~22k-hr sweep (CALIBRATION.md, two entries dated 2026-07-23): discus-hull
  σ is instrument-broadened (39–64°) — never tune from it; Waverider truth moved
  `SPREAD_LONG_SWELL_DEG` 15→24 (only knob changed); proxy↔Qp positive at all 12
  stations (+0.34…+0.72). 4 CDIP Waverider stations added (`data/buoys/cdip.yaml`).
- **Swell events**: `events.py` (spec-exact + floored median + GOOD-at-peak gates) →
  payload `events[]`. In production data from the 14:20 UTC VM cycle onward. NOT yet
  rendered in the web UI.
- **Web deployed** (rosa-rust.vercel.app): "Sets" 4th quality bar (day-mean
  consistency) + amber missed-swell note under the day title; `types.ts` mirrors all
  new payload fields. Verified headless on the Jul-25 day (screenshot, 0 console errors).
- **Infra** (VM design unchanged: rosa-instance 82.70.218.149, cron 4×/day publish.sh —
  see CLAUDE.md + memory): NEW `rosa-backup` micro claimed (public 82.70.222.233,
  private 10.0.0.11); nightly 03:40 UTC rsync of `data/verify/` from rosa-instance
  (first sync verified, 27 files). A1 4/24 capacity watcher running on rosa-instance
  (`~/arm-watch.log`, auto-launches `rosa-arm` on capacity; OUT_OF_HOST_CAPACITY all
  session). Two OCI accounts: local `~/.oci/config` [DEFAULT]=Frankfurt (abandoned),
  [ISRAEL]=live infra (key `~/.oci/israel_api_key.pem`); VM's DEFAULT = Israeli.
  Watcher and backup-cron are NOT reboot-persistent.

## Active Files
- `pipeline/src/rosa_pipeline/ecmwf.py` — NEW: ECMWF open-data source (index+range, capture/replay)
- `pipeline/src/rosa_pipeline/spectral.py` — NEW: missed-swell / consistency / spread (+ calibrated constant)
- `pipeline/src/rosa_pipeline/spectra.py` — NEW: NDBC measured-spectra harness
- `pipeline/src/rosa_pipeline/events.py` — NEW: swell-event detection
- `pipeline/src/rosa_pipeline/{models,extract,publish,verify,archive,cli}.py` — wiring (SpectralSea,
  hour join ≤3 h, payload blocks, events[], `.ecmwf` keys, `--spectra`, `--wave-source all`)
- `pipeline/tests/test_{ecmwf,spectral,spectra,events}.py` + fixtures `tests/fixtures/{ecmwf,spectra}/`
  (real captures; the ecmwf grib fixture is 4.4 MB — flagged, user accepted)
- `data/buoys/cdip.yaml` — NEW: 4 Waverider stations
- `web/src/types.ts`, `web/src/pages/SpotPage.tsx`, `web/src/styles.css` — spectral UI
- `docs/CALIBRATION.md`, `docs/rosa-stage3-plan.md`, `CLAUDE.md` — synced to all of the above

## Changes Made This Session
1. Live spikes first: ECMWF index format/lag (00z fully published by ~10:15 UTC; 06/18z
   skipped — 90 h horizon only), pygrib shortNames (`h1012`…), NDBC spectral file formats.
2. Built 3b member + spectral-lite pure functions; joined per published hour (nearest
   6-hourly step ≤3 h); consistency anchors from JONSWAP/PM ratios (documented proxies).
3. Missed-swell accounting is deliberately conservative: a partition's FULL height
   credits a (±1 s padded) band — a guard must not cry wolf; residual RMS ≥0.3 m surfaces.
4. Committed e9ed2d2; built spectra harness (2502517); ARCHIVE_PARAMS gained mwp/mp2
   (`rows_from_spectral`) so the model-side consistency leg matures in the archive.
5. Pushed; manually ran the VM publish cycle; verified `.ecmwf` keys + spectral fields
   in deployed rosa-data payloads.
6. OCI: generated a dedicated Israeli-account API key (user uploaded via console; user
   REJECTED reusing the Frankfurt keypair — keep accounts separate), discovered OCIDs
   from rosa-instance, installed oci-cli on the VM (`uv tool install oci-cli`), started
   the 4/24 watcher. First auth attempt 401'd — IAM propagation (~20 s), not a bug.
7. User picked all 4 parallel tracks (micro, web, events, CDIP) → built in that order;
   committed d6c7359 / 9e5b460 / 606de76; pushed; web deployed.
8. Spread knob 15→24 justified as measured-truth calibration (1,471 Waverider ≥14 s
   hours, two independent instruments) — logged in CALIBRATION.md before changing.

## Failed Attempts
- `tests/test_events.py` importing `from tests.test_spectral import SPOT` —
  ModuleNotFoundError (tests aren't a package). Inline the fixture Spot instead.
- First ssh nohup of publish.sh held the session open ~25 min (stdin not redirected);
  `< /dev/null` fixes detachment.
- 51101 has no `.data_spec` → harness crashed on 404 mid-sweep; now returns an honest
  "no spectral files" message (fixed in d6c7359).
- Headless "today" screenshot caught the splash overlay despite waiting for
  `.why-bars` — wait for the splash fade (or screenshot after an interaction) instead.
- Frankfurt grabber path is dead: local [DEFAULT] creds authenticate but that tenancy
  is only subscribed to eu-frankfurt-1; Always-Free compute is home-region-only.

## Next Step
Check the A1 watcher: `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149
'tail ~/arm-watch.log'` — if `rosa-arm` landed, bootstrap it (aarch64; earmarked for
Stage 4 + heavy verify jobs, NOT the publish cron; smoke pygrib wheels first).

Then, in order:
1. ~2026-07-30 (archives mature): Stage 2E tuning (input de-bias + Israel refit
   together) AND the 3-way source verdict — `verify --buoy <id> --archive --source
   om|gfswave|ecmwf` per region; promote GFS-Wave where it wins (full ForecastSource
   swap per docs/rosa-stage3-plan.md §3a).
2. 3b acceptance leftovers (archive-gated): missed-swell backtest; model-side
   consistency check (archived mwp/mp2/tp vs `verify --spectra` measured Qp).
3. Web: render `events[]` (alerts/swell-stories surface).
4. If the 4/24 watcher stays dry for days: drop to `OCPUS=2 MEM_GB=12` (sometimes
   launchable when 4/24 isn't).
