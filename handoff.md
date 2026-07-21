# Session Handoff — 2026-07-21 (accuracy + Oracle track)

> This is the **algorithm/infra** session (accuracy roadmap, pipeline Stages 0–1, Oracle
> scheduling). A separate **UI-polish** session works `web/` independently — see "Parallel
> track" at the bottom; do not touch `web/`.

## Goal
Make Rosa the most accurate free surf forecast. This session: authored the full staged
roadmap, built the entire Stage-0 verification backbone + most of Stage 1, produced a
turnkey Oracle deploy kit, and walked through provisioning the Oracle VM (stuck on ARM
capacity — see Oracle state).

## Read first
`docs/rosa-accuracy-roadmap.md` — the authoritative plan (§1 accuracy definition, §2 source
keep/join/replace, §3 architecture, §4 the 6 stages, §5 sequencing, §6 compute+Oracle
decision, §7 spikes, §8 legal, §9 scale posture + verified free-tier stack). Everything below
implements it.

## Current state (all committed + PUSHED to origin/main)
- **Stage 0 COMPLETE** — the verification harness ("most accurate" is now a *measured* number):
  - `verify.py` + `observe.py` + `buoys.py`: NDBC nowcast skill (bias/MAE/RMSE/scatter-index/
    circular dir error). `verify --buoy 46042` or `--near <spot>`.
  - `archive.py`: forecast archive → lead-time skill (`archive` cmd + `verify --archive`).
    R2-ready store behind an interface; accrues over time (clock that can't be back-filled).
  - ISRAMAR **manual-import** adapter (local-only, never fetched/committed — robots-disallowed
    + all-rights-reserved). `--near beit-yanai` finds Hadera (10 km).
  - `feedback.py`: surfer 👍👎 loop (rating/height vs eyes) → bucket-bias signal + CALIBRATION
    rows. `feedback --spot X --verdict up|down` / `feedback --report --markdown`.
- **Stage 1 PARTIAL** (committed):
  - `confidence.py`: REAL multi-model agreement (4 members: ncep_gfswave016/ewam/gwam/
    meteofrance_wave) via a separate lightweight ensemble fetch → per-hour confidence capped by
    horizon. Replaced the placeholder. Live: beit-yanai current 0.95/4 models.
  - Peak period: additive display field (mean period still drives scoring — calibration intact).
  - **DEFERRED**: bias-correction (#Stage1) + Stage-1 validation — both need accumulated archive
    data, i.e. the Oracle cron running for ~a week. Not speculative-coding it before data exists.
- **Oracle deploy kit COMMITTED** (`deploy/oracle/`): `setup.sh` (one-command bootstrap),
  `run-cycle.sh` (archive + run --all), `rosa-cycle.{service,timer}` (systemd --user, 4×/day at
  05/11/17/23 UTC), `README.md` (runbook). No secrets needed (Open-Meteo + NDBC keyless).
- **Tests**: `cd pipeline && uv run pytest` → **96 green**; `ruff check` clean. Standard is
  ample tests per stage (unit + offline fixture + live smoke) — keep it.

## Oracle VM state (IN PROGRESS — the active blocker)
- Account: **Individual, Free Trial**. Home region **Israel Central (Jerusalem)** — PERMANENT,
  can't change for free tier.
- **Network fully built** (done, via the standalone VCN flow — inline instance-wizard networking
  was broken): VCN `rosa-vcn` (10.0.0.0/16) → Internet Gateway `rosa-igw` → route `0.0.0.0/0 →
  rosa-igw` → public subnet `public-subnet` (10.0.0.0/24, Default Security List = SSH open).
- **Instance**: Ubuntu 24.04, shape **VM.Standard.A1.Flex (ARM)**. Tried 2 OCPU/12 GB then
  **1 OCPU/6 GB** → both fail with **"Out of capacity for A1.Flex in AD-1."** SSH: chose "Generate
  a key pair for me" and **downloaded the private key** (need it: `ssh -i <key> ubuntu@<ip>`).
- **BLOCKER = ARM free capacity in Jerusalem.** Jerusalem offers **no free AMD micro** (only paid
  E4/E5 Flex, ~€1.85 est). So the free path is A1.Flex ARM only. Capacity fluctuates —
  retry off-peak (late-night Jerusalem) or use an **auto-retry** (OCI CLI loop, ~15 min setup,
  grabs the instance the moment capacity opens). User chose to WAIT for now.

## Next step (resume here on the other machine)
1. **Land the Oracle ARM VM** (retry off-peak, or set up the auto-retry). Then per
   `deploy/oracle/README.md`: add a read-only **deploy key** for the private repo (§2) →
   `git clone` → run `deploy/oracle/setup.sh`. Cron then accumulates the archive 4×/day.
   *(Optional: `scp -r data/verify/isramar` to the VM to also archive Hadera/Ashdod.)*
2. After ~1 week of accumulation → build **Stage-1 bias-correction** + **validate confidence**
   against real buoy error (both were deferred waiting on this data).
3. **OR, data-independent (no waiting) — start Stage 2**: bathymetry physics (GEBCO/EMODnet
   shoaling + refraction + depth-limited breaking) replacing the single `height_coeff`. Biggest
   accuracy win for the Med; recommended if you don't want to wait on the cron.

## Failed attempts / lessons (don't repeat)
- Oracle **inline** networking in the instance wizard: public-IP toggle greys out, subnet-prefix
  dropdown not clickable → build VCN/IGW/route/subnet separately (now done). Always "Select
  existing" in the instance wizard afterward.
- A1.Flex **2 OCPU** capacity is worse than 1 OCPU → use 1/6 for the current pipeline (heavy SWAN
  box is a later concern; AMD micro + ARM are separate free quotas and can coexist).
- "Too many requests" on Create = transient API rate-limit from rapid clicks, not capacity.
- Cost estimator shows €1.85 for A1.Flex but the **"Always Free-eligible" badge** is the truth —
  actual bill €0 (estimator ignores the free-tier discount).
- Bias-correction & Stage-1 validation are **data-gated** — don't build them before the archive
  has real history.

## Parallel track (separate UI session — leave alone)
A UI-polish session independently edited/committed `web/` (commits `a5d6561`, `754e7ca`): compact
2-col spot card, inline best-session tag, stripped spot-screen chrome, today-only Home; deployed
to https://rosa-rust.vercel.app (Vercel project is named **`rosa`**, not `rosa-rust`). Not our
work — don't touch `web/`.

## Git / housekeeping
- All work committed AND pushed to `origin/main` (12 commits this session + the 2 UI commits).
- `.gitignore` updated to ignore `.vercel` + `.env*` (committed). `env.local` no longer exists.
- `todo.md` left **untracked** (user scratch — per established convention, not committed).
- Gitignored build artifacts on THIS machine only (won't travel via git): `data/out/`,
  `data/verify/` (archive + local ISRAMAR csvs + feedback), `web/public/data/`. On the other
  machine, regenerate with `uv run --project pipeline rosa-pipeline run --all`.
