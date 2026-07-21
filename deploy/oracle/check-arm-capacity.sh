#!/usr/bin/env bash
#
# check-arm-capacity.sh — poll Oracle Cloud for VM.Standard.A1.Flex (Ampere ARM)
# capacity in Jerusalem (il-jerusalem-1), Availability Domain 1.
#
# The Always-Free ARM shape is chronically "out of capacity" in Jerusalem. This
# script asks OCI's Compute Capacity Report API whether the shape is launchable
# RIGHT NOW — without creating anything — and can loop until it frees up.
# Optionally (--launch) it fires a real LaunchInstance the moment capacity opens.
#
# ── Prerequisites ────────────────────────────────────────────────────────────
#   1. OCI CLI installed + configured:  https://docs.oracle.com/en-us/iaas/tools/oci-cli
#        bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
#        oci setup config      # points at your Jerusalem tenancy
#   2. jq installed  (sudo apt install jq)
#   3. Fill in the CONFIG block below (or export the same names as env vars).
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   ./check-arm-capacity.sh                 # one-shot check, prints status, exits
#   ./check-arm-capacity.sh --watch         # poll every INTERVAL until AVAILABLE
#   ./check-arm-capacity.sh --watch --launch  # ...and launch the instance on hit
#   INTERVAL=120 ./check-arm-capacity.sh --watch
#   OCPUS=2 MEM_GB=12 ./check-arm-capacity.sh   # check the 2/12 ceiling instead
#
# Exit codes:  0 = capacity AVAILABLE  ·  1 = out of capacity  ·  2 = error/misconfig
#
set -euo pipefail

# ── CONFIG (env vars override these defaults) ────────────────────────────────
COMPARTMENT_ID="${COMPARTMENT_ID:-}"      # ocid1.compartment... (or tenancy OCID for the root)
REGION="${REGION:-il-jerusalem-1}"
AD_NUMBER="${AD_NUMBER:-1}"               # Jerusalem has one AD; this is AD-1
SHAPE="${SHAPE:-VM.Standard.A1.Flex}"
OCPUS="${OCPUS:-1}"                       # 1/6 has better free-tier capacity odds than 2/12
MEM_GB="${MEM_GB:-6}"
INTERVAL="${INTERVAL:-90}"                # seconds between polls in --watch mode

# ── Optional: only needed if you pass --launch ───────────────────────────────
IMAGE_ID="${IMAGE_ID:-}"                  # ocid1.image... (an Ubuntu 24.04 aarch64 image in Jerusalem)
SUBNET_ID="${SUBNET_ID:-}"               # ocid1.subnet... (your rosa-vcn public-subnet)
SSH_PUBLIC_KEY_FILE="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}"
INSTANCE_NAME="${INSTANCE_NAME:-rosa-pipeline}"

# ── args ─────────────────────────────────────────────────────────────────────
WATCH=0; LAUNCH=0
for arg in "$@"; do
  case "$arg" in
    --watch)  WATCH=1 ;;
    --launch) LAUNCH=1 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 2; }
command -v oci >/dev/null || die "oci CLI not found — install & 'oci setup config' first"
command -v jq  >/dev/null || die "jq not found — 'sudo apt install jq'"
[[ -n "$COMPARTMENT_ID" ]] || die "COMPARTMENT_ID is empty — set it in the CONFIG block or export it"

# Resolve the AD-<N> full name (e.g. "xyzZ:IL-JERUSALEM-1-AD-1") from the tenancy.
AD_NAME="$(oci iam availability-domain list \
             --compartment-id "$COMPARTMENT_ID" --region "$REGION" \
             --query "data[$((AD_NUMBER-1))].name" --raw-output 2>/dev/null || true)"
[[ -n "$AD_NAME" ]] || die "could not resolve AD-$AD_NUMBER in $REGION (check COMPARTMENT_ID/auth)"

check_capacity() {
  # Returns the availability-status string, e.g. AVAILABLE or OUT_OF_HOST_CAPACITY.
  local report
  report="$(oci compute compute-capacity-report create \
      --compartment-id "$COMPARTMENT_ID" \
      --region "$REGION" \
      --availability-domain "$AD_NAME" \
      --shape-availabilities "[{\"instanceShape\":\"$SHAPE\",\"instanceShapeConfig\":{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEM_GB}}]" \
      2>/dev/null)" || { echo "API_ERROR"; return; }
  echo "$report" | jq -r '.data."shape-availabilities"[0]."availability-status" // "UNKNOWN"'
}

launch_instance() {
  [[ -n "$IMAGE_ID"  ]] || die "--launch needs IMAGE_ID"
  [[ -n "$SUBNET_ID" ]] || die "--launch needs SUBNET_ID"
  [[ -f "$SSH_PUBLIC_KEY_FILE" ]] || die "--launch needs SSH_PUBLIC_KEY_FILE ($SSH_PUBLIC_KEY_FILE missing)"
  echo ">>> capacity open — launching $INSTANCE_NAME ($SHAPE $OCPUS/$MEM_GB) ..."
  oci compute instance launch \
    --compartment-id "$COMPARTMENT_ID" \
    --region "$REGION" \
    --availability-domain "$AD_NAME" \
    --shape "$SHAPE" \
    --shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEM_GB}" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --assign-public-ip true \
    --display-name "$INSTANCE_NAME" \
    --ssh-authorized-keys-file "$SSH_PUBLIC_KEY_FILE" \
    --wait-for-state RUNNING
}

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
echo "target: $SHAPE ${OCPUS}OCPU/${MEM_GB}GB  in  $AD_NAME  ($REGION)"

while :; do
  status="$(check_capacity)"
  echo "$(ts)  $status"
  case "$status" in
    AVAILABLE)
      if (( LAUNCH )); then launch_instance; fi
      exit 0 ;;
    API_ERROR|UNKNOWN)
      # transient/permission/region hiccup — keep polling in --watch, else bail
      (( WATCH )) || exit 2 ;;
  esac
  (( WATCH )) || exit 1
  sleep "$INTERVAL"
done
