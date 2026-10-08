# Rosa on the Oracle VM - the single scheduling home

## The machines

Rosa's whole backend is always-on Oracle VMs in one VCN. Nothing else runs on a schedule -
no GitHub Actions, no systemd timers, no request-time backend.

| | **`rosa-arm`** - "the box" (since 2026-08-30) | **`rosa-backup`** |
|---|---|---|
| Shape | A1.Flex, 4 OCPU / 24 GB, aarch64, 153 GB disk (2026-10-07; with the backup's 47 GB that is the 200 GB Always Free cap) | E2.1.Micro, 1/8 OCPU / 1 GB |
| Address | `82.70.253.255` (public), `10.0.0.35` | `10.0.0.11` (private, reach it *through* the box) |
| Job | **Does the work.** Runs the whole forecast cycle. | **Watches the box.** Holds the off-box archive copy. |
| Schedule | `publish.sh` 4×/day (02:20/08:20/14:20/20:20 UTC); 03:40 archive rsync to the backup; `cam-watch.sh` Mondays 05:40 | `freshness-watch.py` hourly at :17; receives the 03:40 archive rsync |
| Checkout | `~/rosa`, **read-only** deploy key - it can pull, never push | `~/rosa-watch` (watchdog), `~/rosa-archive-backup` (rsync target) |
| Key logs | `~/rosa/publish.log`, `~/rosa/cam-watch.log` | `~/rosa-watch/watch.log` |

```bash
ssh -i ~/.config/rosa/ssh-key-2026-07-23.key ubuntu@82.70.253.255       # the box
ssh -i ~/.config/rosa/ssh-key-2026-07-23.key ubuntu@82.70.253.255 \
  'ssh ubuntu@10.0.0.11 "tail -3 ~/rosa-watch/watch.log"'               # the backup, via the box
```

When these docs say **"the box"** they mean `rosa-arm`, and "reaches the box on the next
pull" means the change is on `main` and `publish.sh` will `git pull` it at the top of the next
cycle - there is no separate deploy step for VM code.

`rosa-instance` (E2 micro, ran the cycle 2026-07-23 -> 2026-08-30, idle spare after) was
**terminated 2026-10-07** with its boot volume; its 47 GB went to `rosa-arm`. Its buoy archive
(48 files) was checked present in full on `rosa-arm` first.

**Why the move (2026-08-30, OPEN-ITEMS 24):** the E2 micro is a burstable 1/8-OCPU shape.
`sar` during a 624-spot cycle read 6% user / ~45% steal for six hours - the box was getting
about 1/16 of a core - so a cycle took 6-7 h and every other cron slot was skipped on the
lock. `rosa-arm` had been launched by the capacity watcher on 2026-07-26 and sat idle (SWAN
is built on it for Stage 4; the two share the box). Migration = deploy key + Node 20 (NodeSource
arm64) + Vercel CLI + `uv sync` + `rsync` of `data/verify/`, `data/out/`, `~/rosa/.env`,
`~/rosa-push/` from the micro, then the same three cron lines. The micro's crontab was emptied
first so no two boxes ever ran a cycle at once. Its `id_ed25519` is authorized on the backup
for the rsync; the old box's key is NOT authorized on rosa-arm.

**Why two:** a watchdog on the machine it watches is not a watchdog. `rosa-backup` exists so a
dead box, a dead cron, or a hung cycle still pages someone. It is deliberately dumb - it reads
the *published* data over HTTPS and never talks to the pipeline.

## The cycle (`publish.sh`)
0. **`flock -n` single-instance guard** - one checkout and one stage dir are shared, so an
   overrun could deploy a half-written tree. Non-blocking: a second instance logs a skip and
   exits 0. Sits above the ERR trap, so a skip is never an ops alert.
1. `git pull` - code pushes reach the box on the next cycle (`data/` + `.env` are gitignored)
2. `rosa-pipeline archive` - append the model's forecast at every registered buoy to the VM's
   persistent disk (`data/verify/archive/`). This is the calibration lead-time clock - the one
   thing that can't be back-filled.
2c. **Stage-4 pilot (since 2026-09-14, `docs/rosa-stage4-plan.md`)** - for each region with
   committed SWAN grids (`data/swan/<region>/`, SoCal only today): `rosa-pipeline swan`
   rebuilds the boundary from this cycle's GFS-Wave partitions, `run.sh` runs the SWAN
   chain with `~/bin/swan-omp.exe` (outer + nests, days 0-7, ~40 min), `swan-archive`
   appends SWAN's sea at the registered buoys as the `.swan` archive member. RECORDING
   ONLY - the publish below stays on the march until the A/B on those rows says otherwise.
   Non-fatal and silent: a failure prints one warn line and the cycle goes on. Per-run
   timings: `data/swan/<region>/run/run.log` (gitignored, one cycle deep).
3. `rosa-pipeline run --all` - refresh all per-spot forecasts. Since 2026-08-26 this is the
   GFS-Wave+ECMWF blend arm by default (waves from global files downloaded once per cycle,
   tide from committed EOT20 constants, SST from OISST - ZERO marine-host units a run since
   2026-09-12, when the SST/tide fallback request was removed; `--wave-source om` is the
   per-spot fallback at 7.69 units/spot, i.e. one 1947-spot run a day fits the budget).
   **Exit 3 is the daily-quota guard, not a failure, and only the om arm can raise it**:
   `rosa_pipeline.quota` keeps a per-UTC-day ledger of Open-Meteo marine-host units in
   `data/verify/quota.json` and refuses an om-arm fetch when the next fleet run would cross
   the budget (default 9,400 units; `ROSA_OM_DAILY_BUDGET` moves it, `--ignore-quota`
   overrides once). The cycle then alerts, pings the dead-man anyway, and exits 0 with the
   previous payloads still serving. The blend arm's one per-spot Open-Meteo call is the
   WEATHER host (1.21 units/spot, ~2,730 a run at 2254 spots, ~10,900 a day plus ~916 for the
   station wind archive - at the vendor's 10,000/day line; OPEN-ITEMS 34 tracks the exit,
   plan C3b lost its A/B 2026-09-26), which the ledger does not meter. On the om arm a fifth fleet run of
   any kind - including an ad-hoc one from a laptop against the same IP - is what the guard
   exists to stop. It fired for real on 2026-08-15 before it existed (OPEN-ITEMS 19).
   **Exit 4 is a PARTIAL run, and it DEPLOYS**: a small share of the fleet failed and the
   rest published, so the cycle alerts and ships anyway. The failed spots keep serving their
   previous payload - prune is keyed on the DB, not on this run's output - so the cost is a
   few stale spots instead of every spot going stale. Above `PARTIAL_FAILURE_MAX_SHARE` (5%
   of the fleet), or with nothing published at all, `run --all` still returns 1 and the trap
   kills the cycle: a schema break hits ~100% of spots and must never reach the CDN. Added
   2026-08-28, after 3 shallow-profile spots raising one ValueError kept 621 healthy spots
   and six freshly seeded regions off the CDN for a day.
4. `vercel deploy --prebuilt` of `data/out` → the **rosa-data** project
   (https://rosa-data-opal.vercel.app, `/data/*` with permissive CORS; the app fetches it via
   `VITE_DATA_BASE`). Logs to `~/rosa/publish.log`.
5. `rosa-pipeline notify` - grouped swell-alert Web Pushes (one swell = one notification)
   to every subscription stored by https://rosa-push.vercel.app. Skipped silently unless the
   push secrets are in `~/rosa/.env`; sent-state lives in `data/verify/push-state.json`.

**Secrets** in `~/rosa/.env` (chmod 600, gitignored): `VERCEL_TOKEN`, plus for pushes
`PUSH_SUBS_URL=https://rosa-push.vercel.app/api/subs`, `PUSH_ADMIN_SECRET=...` (matches the
rosa-push Vercel project env), `VAPID_PRIVATE_KEY=$HOME/rosa-push/vapid_private.pem`,
`VAPID_SUB=mailto:...`, plus `GOOGLE_MAPS_API_KEY` (carries the YouTube Data API, used by
`cam-watch.sh`) and `HEALTHCHECK_URL` (healthchecks.io ping URL - a capability in its own
right: anyone holding it can suppress your outage alerts). Open-Meteo and NDBC are keyless.

## Bootstrap a fresh VM
1. Create the instance (Oracle console), note the public IP; `ssh ubuntu@<ip>`.
2. Repo access (private repo → read-only deploy key):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/rosa_deploy -N ""
   cat ~/.ssh/rosa_deploy.pub   # add on GitHub: Settings → Deploy keys (read-only)
   printf 'Host github.com\n  IdentityFile ~/.ssh/rosa_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   git clone git@github.com:BloodyDeathRoll/rosa.git ~/rosa
   ```
3. `~/rosa/deploy/oracle/setup.sh` - installs uv/Node/Vercel CLI and the cron.
4. `echo 'VERCEL_TOKEN=...' > ~/rosa/.env && chmod 600 ~/rosa/.env`
5. Force a cycle and watch it: `~/rosa/deploy/oracle/publish.sh; tail -f ~/rosa/publish.log`
6. Verify: `wc -l ~/rosa/data/verify/archive/*.jsonl` grows each cycle, and
   `curl -s https://rosa-data-opal.vercel.app/data/index.json` shows a fresh `generated_at`.
7. Moving the cycle to another box: empty the old crontab FIRST (`crontab -l > bak; crontab -r`),
   then `rsync` `data/verify/` (the calibration clock - it cannot be back-filled), `data/out/`
   (so a partial first run has previous payloads to keep), `~/rosa/.env`, `~/rosa-push/`, and
   only then install the cron on the new box. On arm64, Node comes from NodeSource
   (`setup_20.x`), not Ubuntu's `nodejs` package.

## Notes
- **Archive persistence:** lives on the VM's block volume; back it up by copying
  `data/verify/` off-box. The retired GH-Actions seed (Jul 22-23) was merged in already.
- **ISRAMAR (optional):** copy `data/verify/isramar/` to the VM by `scp` only - it's
  all-rights-reserved and gitignored, it never travels via git.
- **Skill checks (after a week of archive):**
  `uv run --project pipeline rosa-pipeline verify --buoy 46042 --archive`
- **Coastal wind truth (2026-08-29):** step 4c (`archive --stations only`; it rode inside step 1
  until 2026-09-17, where its paced NOMADS leg held the forecast back ~70 min) archives the model's 10 m wind at
  every station in `data/stations/` (90 METAR airfields within 25 km of a spot) to
  `data/verify/stations/<id>.jsonl` (the published model, GFS since 2026-08-30) and
  `<id>.icon.jsonl` (ICON, the A/B member - archived 2026-08-30 to 2026-09-16, dropped
  when the A/B confirmed GFS) and `<id>.gfs_grib.jsonl`
  (the raw GFS 0.25 atmos GRIB from NOMADS, plan C3b's candidate to replace the
  Open-Meteo weather call - archived 2026-09-12 to 2026-09-26, dropped when its A/B lost
  to Open-Meteo, docs/CALIBRATION.md 2026-09-26; unpaced it tripped NOMADS and killed the
  2026-09-12 14:20Z cycle),
  and step 4d scores the published one by lead with `verify --stations --archive` (one
  station: `verify --station LLBG --archive`; the other members: `--wind-model icon` /
  `--wind-model gfs_grib`). Wind columns only, evidence only - the bias it
  measures is the coastal-cell damping OPEN-ITEMS 25 is about. IMS stations (`data/stations/ims.yaml`, 21 within 25 km
  of a spot, five of them on the beach) read `IMS_API_TOKEN` from `~/rosa/.env` (there
  since 2026-09-14; free, by mail from ims@ims.gov.il). Without it those stations fail
  per station and the pass is METAR-only.
- **Measured confidence ceilings (2026-08-07):** every cycle ends with
  `verify --all-buoys --archive --write-skill`, which scores the whole fleet
  (ISRAMAR buoys skipped - legal red line) and writes `data/verify/skill.json`;
  the next cycle's `run --all` publishes ceilings derived from it, with the
  contributing buoys named in each payload's `confidence_meta.ceiling_source`.
  Single-buoy spot checks like the one above never touch skill.json - persisting
  requires the explicit `--write-skill`. Non-fatal: on failure (or while tiers
  are still under the 100-hour sample floor) publishing falls back to the static
  ceilings and says so.

## Self-hosted Open-Meteo (2026-10-07, OPEN-ITEMS 34)

`rosa-arm` runs Open-Meteo's own API in Docker (`deploy/oracle/open-meteo/docker-compose.yml`, copied to
`~/open-meteo/`; `cd ~/open-meteo && sudo docker compose up -d`), on `http://127.0.0.1:8080` only. A second
container (`open-meteo-sync`) keeps a local copy of the files our 5 fields come from (GFS 0.11 for
temperature and 10 m wind, GFS 0.25 for gusts and MSL pressure, HRRR for all five over the US),
checking Open-Meteo's AWS open-data bucket every 5 min; anything else is read from the bucket on
demand into a 40 GB `cache.bin` allocated in full at start. On-demand alone was too slow: a cold
pass over all 2765 points ran > 50 min. Both `restart: always`.
The weather leg uses it (see ON below). The switch: `ROSA_WEATHER_URL=http://127.0.0.1:8080/v1/forecast` in `~/rosa/.env` sends the weather leg here first, and any failure sends that batch and the rest of the run back to the public API (`blend.fetch_weather_many`). First reading, two points,
`gfs_seamless`, 16 days: wind speed and temperature byte-identical to the public API; gusts and
pressure differ on most hours (up to 38 km/h and 4.6 hPa), and Miami's wind direction on 85 of 408
hours - the public API was still serving the 06Z GFS 0.25 run (where gusts and pressure live) while
the bucket already had 12Z. Same-run comparison pending.

**Measured 2026-10-07 (154-spot sample, then the fleet):** wind speed and temperature identical to the
public API at every hour of every spot. Fleet speed with the sync done: all 2765 points in 43 s cold,
4 s warm, no bad batch. **Blocker:** wind direction differs at the US (HRRR) spots for the first ~3.5
days by a steady rotation of 0.62 x (lon + 97.5) deg - the HRRR grid-to-true-north turn. Open-Meteo
fixed it on 2026-09-28 (open-meteo/open-meteo#2157); the newest image, 1.6.0 (2026-09-10), predates
it and 1.7.0 is unreleased. **Resolved 2026-10-08:** both containers now run `open-meteo-local:290493f`, built on the box
from open-meteo main (build steps in the compose file; back to the official image once 1.7.0+ ships).
Same-run comparison, 154 spots, all three GFS sources on the same run as the public API: **all five
fields identical at every hour (62,832 values each)**.

**ON since 2026-10-08 07:10Z:** `ROSA_WEATHER_URL=http://127.0.0.1:8080/v1/forecast` in `~/rosa/.env`
(backup `~/rosa/.env.bak-2026-10-08`; delete the line to go back). Pre-flight on the box, the real
`fetch_weather_many` over all 2765 points: 2765 full bodies (408 h each), 0 public-API calls, 11 s.
A `warn: self-hosted weather failed` line in `publish.log` means that run fell back to the public API. Cold request ~25 s, warm ~1.3 s.

## Ops alerting (2026-07-28, third eye live 2026-08-04)
Three independent eyes, after two silent run-crash incidents left stale data serving. They
escalate outward - the box reports its own failures, the backup catches a box that has gone
quiet, and healthchecks.io catches both boxes going quiet together:
- **Failure push (this VM):** publish.sh traps any essential-step failure and runs
  `rosa-pipeline alert` - a plain Web Push to the devices in
  `~/rosa-push/admin-subs.json` (a hand-maintained snapshot of the ADMIN's own
  subscriptions, never the public list; refresh it after re-subscribing:
  `curl -s -H "x-admin-secret: $PUSH_ADMIN_SECRET" $PUSH_SUBS_URL > ~/rosa-push/admin-subs.json`).
- **How many users (not a monitor, a recipe):** signed-in accounts live on the Cloudflare
  user API, not here - `curl -s -H "x-admin-secret: <ADMIN_SECRET of rosa-user-api>"
  https://rosa-user-api.einhanamer.workers.dev/admin/stats` (`deploy/user-api/README.md`).
  `$PUSH_SUBS_URL` still counts devices that opted into push; Vercel Analytics counts visitors.
- **Stale-data watchdog (rosa-backup, 10.0.0.11):** hourly cron runs
  `~/rosa-watch/freshness-watch.py` (source: `deploy/backup/freshness-watch.py`) -
  alerts when rosa-data's `fetched_at` is > 8 h old or unreadable, so a dead VM or
  dead cron still pages. Re-alerts at most every 12 h. (8 h, not 7: `fetched_at` is
  stamped at cycle START and publishing takes 60-90 min, so served age legitimately
  peaks near 6.9 h - 7 h left ~6 min of headroom and a slow cycle paged falsely.)
- **Third eye - healthchecks.io (LIVE since 2026-08-04):** `HEALTHCHECK_URL` is set in
  `~/rosa/.env`; publish.sh pings it on success and `$HEALTHCHECK_URL/fail` (with the
  failed step in the body, so the email names the command that died) on failure. This is
  the only layer outside Oracle entirely, so it covers "both VMs die together" and
  "the Oracle account/region is gone". Check config: **cron schedule**
  `20 2,8,14,20 * * *` UTC, **grace 2 h** - deliberately alerting at 8 h of silence to
  match the watchdog's 8 h staleness limit rather than crying first. Cron mode, not
  "every 6 h", so a missed 08:20 is caught at 10:20 instead of drifting. Both paths were
  tested end to end on 2026-08-04 (fail → DOWN email → success → recovery email).
  Unset = no-op, which is how it silently did nothing from 07-28 until 08-04.
  **What pings and what does not (read this before chasing a DOWN email):** a cycle that
  COMPLETES pings, and so does one that skips on the Open-Meteo daily quota - that skip
  is a decision, not silence. A cycle that skips on the single-instance lock pings
  NOTHING, deliberately: an overrun is the thing the dead-man is for. So while a cycle
  takes longer than the 6 h cron gap (OPEN-ITEMS 24), every other cron slot skips on the
  lock and pings land ~12 h apart - past the 6 h + 2 h window - and the check goes DOWN
  on a fleet that is publishing fine. First seen 2026-08-29: last ping 09:20:06Z for the
  02:20Z cycle, 08:20Z skipped on the lock, 10:20Z deadline missed. **The fix is the
  cycle duration, not the check** - pinging on a lock-skip would trade a false alarm for
  silence about a real overrun.
- **Weekly cam rot check (this VM, 2026-07-29):** `deploy/oracle/cam-watch.sh`, cron
  Mondays 05:40 UTC, log `~/rosa/cam-watch.log`. A cam dies with nobody touching it -
  YouTube rotates the video id whenever a 24/7 stream restarts - so an embed can sit
  dark for months. One admin push when anything is dead, naming the spots and how many
  are auto-repairable. Needs `GOOGLE_MAPS_API_KEY` in `~/rosa/.env` (the project's
  Google key carries the YouTube Data API). Cost: ~1 unit on a clean week (one batched
  `videos.list`), +100 per dead cam, against 10,000/day.
  **It never runs `--apply`, by design:** this box holds a READ-ONLY deploy key, so it
  cannot push a repair, and applying here would leave `data/spots` dirty and make the
  next `git pull --ff-only` fail - silently freezing the VM on local code. Repair is a
  one-command human action from a clone that can push:
  `YOUTUBE_API_KEY=$GOOGLE_MAPS_API_KEY python tools/cam-scan/scan.py verify --resolve --apply`
  (rewrites only cams whose replacement still carries the same title; everything else
  prints as NEEDS A HUMAN). If the VM is ever given a write-capable key, the apply +
  commit + push could move here.
