# Setting Rosa up on another machine

`git clone` is enough to **develop, test and run the pipeline**. It is not enough to
**deploy, send push, or reach the Oracle VM** - those need secrets that are deliberately
gitignored and must be copied off an existing machine.

---

## 1. Toolchain

| Need | Why | Install |
| --- | --- | --- |
| Python >= 3.11 | pipeline | system package |
| [uv](https://docs.astral.sh/uv/) | the only Python entry point used in this repo | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node >= 20 | Vite 6 | system package or nvm |
| eccodes | `pygrib` links against it (GFS-Wave / ECMWF GRIB reads) | `sudo apt install libeccodes-dev` |

```bash
git clone git@github.com:BloodyDeathRoll/rosa.git
cd rosa
uv sync --project pipeline
cd web && npm install && cd ..
```

Verify:

```bash
uv run --project pipeline pytest        # expect all green
uv run --project pipeline ruff check .
```

> Always run `uv run --project pipeline ...` **from the repo root**. Running `cd pipeline` first
> and then passing `--project pipeline` resolves to `pipeline/pipeline` and silently publishes
> nothing.

---

## 2. What the clone already contains

- the whole pipeline, its tests and its offline fixtures (`pipeline/tests/fixtures/`) - no network
  needed to run the test suite
- all 199 spot definitions (`data/spots/*.yaml`)
- all 199 committed depth profiles (`data/spots/derived/bathy/`) - these are the physics inputs,
  so `run` works immediately
- the web app plus `web/.env.production`, which is tracked on purpose: the data URL, push API URL
  and VAPID **public** key are all public values

**No API key is needed to produce a forecast.** Open-Meteo is unauthenticated, and `bathy` /
`horizon` read GEBCO through the OpenTopoData API rather than a local grid.

```bash
uv run --project pipeline rosa-pipeline run --spot santa-teresa   # one spot
uv run --project pipeline rosa-pipeline run --all                 # all 199, ~40 min
```

Output lands in `data/out/` (gitignored - it is a build artifact).

---

## 3. Secrets you must copy over

None of these are in git. Copy them from a working machine (or from the VM, where noted).

### `~/.config/rosa/` - the important one

Outside the repo on purpose (moved from `web/.oracle/` 2026-09-11, security audit): an agent
working in the repo tree should not be holding the box's key.

```
~/.config/rosa/ssh-key-2026-07-23.key   # Oracle VM access (chmod 600)
~/.config/rosa/ssh-key-2026-07-23.key.pub
~/.config/rosa/private_key.pem          # VAPID private key
~/.config/rosa/public_key.pem
~/.config/rosa/push-admin-secret.txt    # rosa-push admin surface
```

⚠️ **The VAPID private key cannot be regenerated.** Replacing it invalidates every existing push
subscription on every user's device. Back it up before you need it.

```bash
scp -r ~/.config/rosa/ user@newmachine:~/.config/
chmod 700 ~/.config/rosa
chmod 600 ~/.config/rosa/ssh-key-2026-07-23.key ~/.config/rosa/private_key.pem
```

Note the live VAPID private key also lives VM-only at `~/rosa-push/vapid_private.pem`; the copy in
`~/.config/rosa/` is the backup.

### `.env.local` (repo root)

```
GOOGLE_MAPS_API_KEY=...     # tools/spot-verify geocoding, and the cam sweep (YOUTUBE_API_KEY=$GOOGLE_MAPS_API_KEY)
VERCEL_TOKEN=...            # deploys
```

Only needed for deploying and for the spot/cam tooling. Not needed to run a forecast.

### `web/.env.development`

Local dev push config. Same public values as `web/.env.production`, so it is quicker to retype
than to copy:

```
VITE_PUSH_API=https://rosa-push.vercel.app
VITE_VAPID_PUBLIC=<same value as in web/.env.production>
VITE_USER_API=http://localhost:8787
VITE_GOOGLE_CLIENT_ID=<same value as in web/.env.production>
```

`VITE_USER_API` points at `wrangler dev` of `deploy/user-api` (see its README); use the
production URL `https://rosa-user-api.einhanamer.workers.dev` if you are not running it.

### Vercel project links

`.vercel/` is gitignored, so re-link on the new machine:

```bash
npx vercel login
cd web && npx vercel link          # -> the rosa project (https://rosa.surf, legacy rosa-rust.vercel.app)
```

---

## 4. Running the web app

The dev server serves data from `web/public/data`, which `sync-data` copies out of `data/out`.
**So you must produce forecast data before `npm run dev` will work** - otherwise `sync-data` has
nothing to copy and the app loads empty.

```bash
uv run --project pipeline rosa-pipeline run --all   # or --spot X for a quick loop
cd web && npm run dev
```

Deploying (only with `VERCEL_TOKEN` in place):

```bash
cd web && npm run deploy      # build + prebuilt static deploy to prod
```

> Vercel Git integration is deliberately **disconnected**. Deploys are CLI-only. Do not reconnect
> it: forecast data is gitignored, so a Git-triggered cloud build ships a dataless app.

---

## 5. Large optional downloads

Not needed for normal work. Skip unless you are doing the specific task named.

| Path | Size | Needed for | Recoverable? |
| --- | --- | --- | --- |
| `data/bathy/GEBCO_2024.nc` | 7.0 GB | `tools/spot-seed/` bulk spot seeding only | yes, re-download from GEBCO |
| `data/osm/<region>.osm.pbf` | 3.6 GB | `tools/spot-seed/` OSM flows only | yes, Geofabrik extracts |
| `data/verify/` | 25 MB | `verify`, `feedback`, the lead-time scorecard | **NO** |
| `data/out/` | - | build artifact | yes, `run --all` |

⚠️ **`data/verify/` is the calibration clock and cannot be back-filled.** It accumulates one row
per buoy per cycle and there is no way to recreate history. The authoritative copy lives on the
Oracle VM at `~/rosa/data/verify/`, mirrored nightly to the `rosa-backup` box. Pull a copy if you
want to run verification off-box:

```bash
rsync -avz -e "ssh -i ~/.config/rosa/ssh-key-2026-07-23.key" \
  ubuntu@82.70.253.255:~/rosa/data/verify/ data/verify/
```

The pipeline `bathy` and `horizon` commands do **not** need the GEBCO download - they use the
OpenTopoData API.

---

## 6. What still only runs on the VM

Cloning does not move the schedule. The Oracle VM `rosa-arm` (82.70.253.255, "the box" - see
`deploy/oracle/README.md`; `rosa-instance` is the idle spare since 2026-08-30) is the only
thing that publishes: cron 4x/day at 02:20/08:20/14:20/20:20 UTC runs
`deploy/oracle/publish.sh` (git pull -> buoy archive -> `run --all` -> swellmap -> prebuilt Vercel
deploy to `rosa-data` -> push notify).

A new machine can run everything locally for development, but **publishing to production stays on
the VM**. It pulls `main` at the start of each cycle, so pushing code is how changes reach it.

```bash
# check the last cycles from anywhere with the ssh key
ssh -i ~/.config/rosa/ssh-key-2026-07-23.key ubuntu@82.70.253.255 \
  'grep -nE "^=== |FAILED at:|warn:" ~/rosa/publish.log | tail -8'
```

---

## 7. Quick checklist

- [ ] `uv sync --project pipeline` and `npm install` both clean
- [ ] `uv run --project pipeline pytest` all green
- [ ] `~/.config/rosa/` copied, key files `chmod 600`
- [ ] `.env.local` created (only if deploying or using the spot tools)
- [ ] `vercel link` done in `web/`
- [ ] `rosa-pipeline run --spot santa-teresa` writes `data/out/spots/santa-teresa.json`
- [ ] `cd web && npm run dev` loads a forecast
