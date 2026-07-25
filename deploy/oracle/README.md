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
