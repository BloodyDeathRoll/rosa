# Rosa on the Oracle VM - the single scheduling home

One small always-on VM runs the whole cycle by cron, 4×/day (02:20/08:20/14:20/20:20 UTC,
shortly after each NOAA run publishes). No GitHub Actions.

**The cycle (`publish.sh`):**
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
`VAPID_SUB=mailto:...`. Open-Meteo and NDBC are keyless.

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

## Ops alerting (2026-07-28)
Two independent eyes, after two silent run-crash incidents left stale data serving:
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
- **Optional third eye:** set `HEALTHCHECK_URL` in `~/rosa/.env` (healthchecks.io
  ping URL) - publish.sh pings it on success and `$HEALTHCHECK_URL/fail` on failure,
  covering the "both VMs die together" case. Unset = no-op.
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
