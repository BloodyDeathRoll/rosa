# Deploying the Rosa pipeline on Oracle Cloud (Always Free)

The lasting scheduling home (roadmap §6). A small always-on VM runs the pipeline 4×/day; its
**persistent disk holds the forecast archive**, so Stage-0 skill accumulates and bias-correction
gets unblocked — no fresh-checkout wipe, no R2 round-trip needed to accumulate.

**What the cron does:** `archive` (append the model's forecast at every buoy — the essential
lead-time clock) + `run --all` (refresh per-spot forecasts). **No secrets required** — Open-Meteo
and NDBC are keyless.
**What it does *not* do (yet):** publish forecasts to users. That stays a CLI deploy from your
machine for now; publishing from the VM (R2/Vercel) is a later follow-up.

Split of work: **§1–2 are Oracle-console + auth steps only you can do; §3 is one command.**

---

## 0. Prerequisites
- An Oracle Cloud account (the Always Free tier — no card charge on Always-Free shapes).
- An SSH keypair (`ssh-keygen -t ed25519` if you don't have one).

## 1. Create the Always Free VM  *(Oracle Console — you)*
1. **Compute → Instances → Create instance.**
2. **Image:** Canonical **Ubuntu 24.04** (or 22.04).
3. **Shape:** **Ampere (Arm) — VM.Standard.A1.Flex**, the Always-Free ARM shape. Set **2 OCPU /
   12 GB** (the current Always-Free ceiling — Oracle halved it from 4/24 in June 2026). If the
   console says "out of capacity," try another Availability Domain or region, or retry later —
   Always-Free ARM capacity is often scarce.
4. **SSH keys:** paste your **public** key.
5. Create, then note the **public IP**. Connect: `ssh ubuntu@<public-ip>`.

## 2. Give the VM read access to the private repo  *(you)*
The repo is private, so the VM needs read access. Easiest: a **read-only deploy key**.
```bash
# on the VM:
ssh-keygen -t ed25519 -f ~/.ssh/rosa_deploy -N ""
cat ~/.ssh/rosa_deploy.pub
```
Add that public key on GitHub → repo **Settings → Deploy keys → Add** (read-only). Then:
```bash
# on the VM:
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/rosa_deploy
  IdentitiesOnly yes
EOF
git clone git@github.com:BloodyDeathRoll/rosa.git ~/rosa
```
*(Alternatives: `gh auth login`, or an HTTPS clone with a fine-grained read-only PAT.)*

## 3. Bootstrap  *(one command)*
```bash
~/rosa/deploy/oracle/setup.sh
```
Installs `uv` (which manages its own Python 3.11+), syncs deps, and enables the
`systemctl --user` timer with **linger on** so it runs without you being logged in.

## 4. Verify it's running
```bash
systemctl --user list-timers rosa-cycle.timer     # next scheduled fires
systemctl --user start rosa-cycle.service          # force a cycle right now
journalctl --user -u rosa-cycle -f                 # watch it (Ctrl-C to stop)
ls -la ~/rosa/data/verify/archive/                 # rows accumulating, one file per buoy
```

## 5. Check forecast skill (later, once forecasts mature)
The archive needs days to accrue lead-time data. After a week:
```bash
cd ~/rosa
uv run --project pipeline rosa-pipeline verify --buoy 46042 --archive   # lead-time skill
uv run --project pipeline rosa-pipeline verify --buoy 46042             # nowcast skill
```

## Notes
- **Persistence:** the archive lives on the VM's block volume — survives reboots, grows over
  time, self-prunes to scored rollups later. Back it up by copying `data/verify/` off-box.
- **Auto-deploy:** each cycle does `git pull --ff-only origin main`, so pushing code updates the
  VM on the next run. `data/` is gitignored, so pulls never touch the archive.
- **ISRAMAR (optional):** to also archive/verify at Hadera/Ashdod, copy your local
  `data/verify/isramar/` to the VM (`scp -r data/verify/isramar ubuntu@<ip>:~/rosa/data/verify/`).
  It's all-rights-reserved and gitignored, so it never travels via git — manual copy only.
- **Schedule:** 4×/day at 05/11/17/23 UTC (just after NOAA runs publish). Edit
  `rosa-cycle.timer` and re-run `setup.sh` to change.
- **Throttling:** a cycle is a handful of requests (well under Open-Meteo's limits).
