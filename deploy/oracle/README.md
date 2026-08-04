# Rosa on the Oracle VM - the single scheduling home

## The two machines

Rosa's whole backend is two small always-on Oracle VMs. Nothing else runs on a schedule -
no GitHub Actions, no systemd timers, no request-time backend.

| | **`rosa-instance`** - "the box" | **`rosa-backup`** |
|---|---|---|
| Address | `82.70.218.149` (public) | `10.0.0.11` (private, reach it *through* the box) |
| Job | **Does the work.** Runs the whole forecast cycle. | **Watches the box.** Holds the off-box archive copy. |
| Schedule | `publish.sh` 4×/day (02:20/08:20/14:20/20:20 UTC); `cam-watch.sh` Mondays 05:40 | `freshness-watch.py` hourly at :17; receives the 03:40 archive rsync |
| Checkout | `~/rosa`, **read-only** deploy key - it can pull, never push | `~/rosa-watch` (watchdog), `~/rosa-archive-backup` (rsync target) |
| Key logs | `~/rosa/publish.log`, `~/rosa/cam-watch.log` | `~/rosa-watch/watch.log` |

```bash
ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149          # the box
ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
  'ssh ubuntu@10.0.0.11 "tail -3 ~/rosa-watch/watch.log"'               # the backup, via the box
```

When these docs say **"the box"** they mean `rosa-instance`, and "reaches the box on the next
pull" means the change is on `main` and `publish.sh` will `git pull` it at the top of the next
cycle - there is no separate deploy step for VM code.

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
3. `rosa-pipeline run --all` - refresh all per-spot forecasts
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

## Notes
- **Archive persistence:** lives on the VM's block volume; back it up by copying
  `data/verify/` off-box. The retired GH-Actions seed (Jul 22-23) was merged in already.
- **ISRAMAR (optional):** copy `data/verify/isramar/` to the VM by `scp` only - it's
  all-rights-reserved and gitignored, it never travels via git.
- **Skill checks (after a week of archive):**
  `uv run --project pipeline rosa-pipeline verify --buoy 46042 --archive`

## Ops alerting (2026-07-28, third eye live 2026-08-04)
Three independent eyes, after two silent run-crash incidents left stale data serving. They
escalate outward - the box reports its own failures, the backup catches a box that has gone
quiet, and healthchecks.io catches both boxes going quiet together:
- **Failure push (this VM):** publish.sh traps any essential-step failure and runs
  `rosa-pipeline alert` - a plain Web Push to the devices in
  `~/rosa-push/admin-subs.json` (a hand-maintained snapshot of the ADMIN's own
  subscriptions, never the public list; refresh it after re-subscribing:
  `curl -s -H "x-admin-secret: $PUSH_ADMIN_SECRET" $PUSH_SUBS_URL > ~/rosa-push/admin-subs.json`).
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
