# Session Handoff — 2026-07-23

## Goal
Ship the UI overhaul (commit + push) and stand up an Oracle Cloud instance to
run the Rosa pipeline on a schedule. UI is done/pushed; instance is up and
reachable but NOT yet provisioned.

## Current State
- **UI overhaul: committed & pushed to `origin/main`** (`6294ed1` feat + `574a17a`
  docs). NOT deployed. Deploy with `cd web && npm run deploy` (CLI-only prod).
  Verified no data/secrets/keys were staged.
- **Oracle instance: LIVE and SSH-reachable.** User created it on the **Israeli
  (main) account**. Public IP `82.70.217.50`, private `10.0.0.10`, hostname
  `instance-20260723-0605`. **Ubuntu 24.04.4 LTS, x86_64** (`6.17.0-oracle`),
  ~44 GB disk, ~1 GB RAM. SSH works:
  `ssh -i "web/.oracle/ssh-key-2026-07-23.key" ubuntu@82.70.217.50` (from repo
  root). The host-key/fingerprint prompt on first connect was normal, not an error.
- **Free-tier status: UNCONFIRMED but almost certainly Always Free.** x86 + ~1 GB
  RAM matches `VM.Standard.E2.1.Micro` (Always Free). Awaiting the user to run the
  metadata `curl` (see Next Step) to confirm the exact `shape`.
- **This is x86, NOT the ARM A1.Flex** the Frankfurt grabber hunts. That grabber
  (`deploy/oracle/grab-arm-frankfurt.sh`, logs `~/grab.log`) is STILL RUNNING in
  the background — user has not yet said whether to stop it now that an x86 box exists.
- **Instance is bare Ubuntu** — no uv/Python/pipeline/cron installed yet.

## Active Files
- `.gitignore` — user changed the Oracle-key ignore from `web/,oracle/` (old stray
  comma dir) to `web/.oracle/` (the real key dir). Uncommitted, 1-line change.
- `web/.oracle/ssh-key-2026-07-23.key` (+ `.pub`) — Oracle instance keypair,
  gitignored, present on disk. Private key sits inside `web/` (outside
  `web/public/`, so `npm run deploy` won't bundle it); flagged to user to consider
  moving to `~/.ssh/`.

## Changes Made This Session
1. Staged `web/src` + `web/public/splash.jpg`, committed the UI overhaul
   (`6294ed1`) and handoff (`574a17a`), pushed to main. Chose direct-to-main
   (repo's established flow; deploys are CLI-only from main).
2. Diagnosed the user's SSH "error" screenshot → it was actually a SUCCESSFUL
   login (normal first-connect fingerprint prompt).
3. Answered the free-tier question: 1 GB x86 ⇒ likely E2.1.Micro / Always Free;
   gave the metadata check command.

## Failed Attempts
None this session. (Prior session's sharp-flop splash bug already resolved.)

## Next Step
1. Confirm free tier — have user run over SSH:
   `curl -s -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/ | grep -iE '"shape"|region|availabilityDomain'`
   Free if shape = `VM.Standard.E2.1.Micro` (or `A1.Flex` ≤4 OCPU/≤24 GB).
2. Decide whether to stop the Frankfurt A1.Flex grabber (background process +
   `~/grab.log`) now that an x86 instance exists.
3. Provision the box for the pipeline: install `uv` + Python 3.11+, copy
   `pipeline/` + `data/spots/` onto it (scp or git clone), run
   `uv run --project pipeline rosa-pipeline run --all`, then a cron 4×/day that
   publishes JSON to Vercel (needs `VERCEL_TOKEN`). Offered to write a provision
   script — user has not yet accepted.
4. Optionally move `web/.oracle/` key out of the web project to `~/.ssh/`.
5. Optional cleanup carried over: delete unused `Spark` in
   `web/src/components/parts.tsx`; strip dead `.coast-cell/.coast-bars/.rank-card
   .side/.rank-n` CSS; consider kph/short wind format on the new SpotCard.
