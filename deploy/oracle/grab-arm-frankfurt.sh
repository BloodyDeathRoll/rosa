#!/usr/bin/env bash
#
# grab-arm-frankfurt.sh - background auto-grabber for an Always-Free VM.Standard.A1.Flex
# (Ampere ARM) instance in Frankfurt (eu-frankfurt-1). Frankfurt has THREE availability
# domains; this loops all of them, firing a real LaunchInstance in each and retrying on
# "Out of host capacity" / 429, until one succeeds. The moment it lands, it prints the SSH
# line and exits.
#
# Why direct-launch (not the capacity-report checker): the report lags reality - a launch can
# succeed when the report says "unavailable" and vice-versa. Hammering LaunchInstance across
# the 3 ADs is what actually grabs the box. (check-arm-capacity.sh remains the cheap "is there
# capacity right now?" spot-check.)
#
# ── Prerequisites ────────────────────────────────────────────────────────────
#   1. OCI CLI installed + configured for the FRANKFURT tenancy:
#        oci setup config          # home region eu-frankfurt-1
#   2. jq installed.
#   3. A built VCN + public subnet in Frankfurt (see README §1), and an Ubuntu 24.04
#      aarch64 image OCID for eu-frankfurt-1.
#   4. Fill the CONFIG block (or export the same names as env vars).
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   ./grab-arm-frankfurt.sh                      # run in foreground
#   nohup ./grab-arm-frankfurt.sh >~/grab.log 2>&1 &   # background, survives logout
#   tail -f ~/grab.log                           # watch it hunt
#   INTERVAL=45 OCPUS=2 MEM_GB=12 ./grab-arm-frankfurt.sh   # chase the 2/12 ceiling instead
#
set -uo pipefail

# ── CONFIG (env vars override) ───────────────────────────────────────────────
COMPARTMENT_ID="${COMPARTMENT_ID:-}"     # ocid1.tenancy... (root) or a compartment OCID
REGION="${REGION:-eu-frankfurt-1}"
SHAPE="${SHAPE:-VM.Standard.A1.Flex}"
OCPUS="${OCPUS:-1}"                       # 1/6 clears capacity faster than the 2/12 ceiling
MEM_GB="${MEM_GB:-6}"
IMAGE_ID="${IMAGE_ID:-}"                  # ocid1.image... Ubuntu 24.04 aarch64 in eu-frankfurt-1
SUBNET_ID="${SUBNET_ID:-}"               # ocid1.subnet... your Frankfurt public subnet
SSH_PUBLIC_KEY_FILE="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/oracle_rosa.pub}"
INSTANCE_NAME="${INSTANCE_NAME:-rosa-pipeline}"
INTERVAL="${INTERVAL:-60}"                # seconds between full 3-AD sweeps
BOOT_GB="${BOOT_GB:-50}"                  # boot volume size (free tier allows up to 200 GB total)

ts()  { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
log() { echo "[$(ts)] $*"; }
die() { echo "error: $*" >&2; exit 2; }

command -v oci >/dev/null || die "oci CLI not found - install & 'oci setup config' first"
command -v jq  >/dev/null || die "jq not found - 'sudo apt install jq'"
for v in COMPARTMENT_ID IMAGE_ID SUBNET_ID; do
  [[ -n "${!v}" ]] || die "$v is empty - fill the CONFIG block or export it"
done
[[ -f "$SSH_PUBLIC_KEY_FILE" ]] || die "SSH public key not found at $SSH_PUBLIC_KEY_FILE"

# Resolve every availability domain in the region (Frankfurt returns 3).
mapfile -t ADS < <(oci iam availability-domain list \
    --compartment-id "$COMPARTMENT_ID" --region "$REGION" \
    --query 'data[].name' --raw-output 2>/dev/null | jq -r '.[]' 2>/dev/null)
[[ "${#ADS[@]}" -gt 0 ]] || die "could not list availability domains (check auth/COMPARTMENT_ID/region)"
log "target: $SHAPE ${OCPUS}OCPU/${MEM_GB}GB in $REGION across ${#ADS[@]} AD(s): ${ADS[*]}"

launch_in() {  # $1 = AD name; echoes CLI output, returns oci's exit code
  oci compute instance launch \
    --compartment-id "$COMPARTMENT_ID" --region "$REGION" \
    --availability-domain "$1" \
    --shape "$SHAPE" --shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEM_GB}" \
    --image-id "$IMAGE_ID" --subnet-id "$SUBNET_ID" \
    --boot-volume-size-in-gbs "$BOOT_GB" \
    --assign-public-ip true --display-name "$INSTANCE_NAME" \
    --ssh-authorized-keys-file "$SSH_PUBLIC_KEY_FILE" \
    2>&1
}

on_success() {  # $1 = instance OCID
  local ocid="$1" ip
  log "🎉 launched - instance $ocid; waiting for RUNNING + public IP ..."
  oci compute instance get --instance-id "$ocid" --region "$REGION" \
      --wait-for-state RUNNING >/dev/null 2>&1 || true
  ip="$(oci compute instance list-vnics --instance-id "$ocid" --region "$REGION" \
        --query 'data[0]."public-ip"' --raw-output 2>/dev/null)"
  log "================ GOT IT ================"
  log "  ssh -i ${SSH_PUBLIC_KEY_FILE%.pub} ubuntu@${ip}"
  log "  next: deploy/oracle/README.md §2 (deploy key) → git clone → setup.sh"
  log "======================================="
  [[ -x "$(dirname "$0")/beep-reminder.sh" ]] && "$(dirname "$0")/beep-reminder.sh" >/dev/null 2>&1 &
}

backoff="$INTERVAL"
while :; do
  for ad in "${ADS[@]}"; do
    out="$(launch_in "$ad")"; rc=$?
    if (( rc == 0 )); then
      ocid="$(echo "$out" | jq -r '.data.id' 2>/dev/null)"
      if [[ -n "$ocid" && "$ocid" != null ]]; then
        on_success "$ocid"
        exit 0
      fi
    fi
    short="${ad##*:}"
    case "$out" in
      *"Out of host capacity"*|*"OutOfHostCapacity"*)
        log "  $short: out of capacity" ;;
      *"TooManyRequests"*|*"429"*)
        log "  $short: rate-limited - backing off ${backoff}s"
        sleep "$backoff"; backoff=$(( backoff*2 > 600 ? 600 : backoff*2 )); continue ;;
      *"LimitExceeded"*|*"QuotaExceeded"*)
        die "$short: quota/limit exceeded - you may already hold the free A1 allowance ($out)" ;;
      *)
        log "  $short: unexpected response - $(echo "$out" | head -1)" ;;
    esac
    backoff="$INTERVAL"
  done
  sleep "$INTERVAL"
done
