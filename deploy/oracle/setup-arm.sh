#!/usr/bin/env bash
#
# setup-arm.sh - provision `rosa-arm` (Ampere A1, aarch64) as the Stage-4 box.
#
# Stage 4 runs a nested nearshore spectral model (SWAN) forced at the boundary by
# Stage-3 spectra - see docs/rosa-accuracy-roadmap.md. This installs the toolchain
# and builds SWAN; it does NOT set up a modelled region (that needs bathymetry
# grids + boundary forcing, and Stage 3 acceptance first).
#
# Usage, from a machine holding the SSH key:
#   scp deploy/oracle/setup-arm.sh ubuntu@<arm-ip>:~ && ssh ubuntu@<arm-ip> 'bash ~/setup-arm.sh'
# Idempotent - safe to re-run; skips what is already in place.
#
# Provenance: rosa-arm was launched 2026-07-26 on the Israeli tenancy after it moved
# to Pay As You Go. 2,834 consecutive free-tier attempts had failed with
# OUT_OF_HOST_CAPACITY over 3 days; the paid account got it on the first try, so the
# shortage was free-tier deprioritisation, not absent hardware. The tenancy carries a
# `rosa-free-tier-cap` quota policy pinning A1 to 4 OCPU / 24 GB, which is exactly
# what this box uses - so it cannot be resized up or joined by a second A1 without
# lifting that quota first, and it cannot bill.
set -euo pipefail

SWAN_VER=4151
SWAN_URL="https://swanmodel.sourceforge.io/download/zip/swan${SWAN_VER}.tar.gz"
SRC="$HOME/src"
BIN="$HOME/bin"

echo "=== 1/4 system packages ==="
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
# gfortran+make build SWAN; netCDF for gridded I/O; OpenMPI is installed because
# SWAN's build system expects mpifort to exist, NOT because we run distributed
# (see the MPI note at the end).
sudo apt-get install -y -qq \
  build-essential gfortran cmake make perl \
  libopenmpi-dev openmpi-bin \
  libnetcdf-dev libnetcdff-dev netcdf-bin \
  git curl unzip pkg-config

echo "=== 2/4 uv (python toolchain) ==="
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "=== 3/4 SWAN ${SWAN_VER} ==="
mkdir -p "$SRC" "$BIN"
if [ ! -d "$SRC/swan${SWAN_VER}/swan${SWAN_VER}" ]; then
  cd "$SRC"
  curl -fLsS -o "swan${SWAN_VER}.tar.gz" "$SWAN_URL"
  mkdir -p "swan${SWAN_VER}"
  tar xzf "swan${SWAN_VER}.tar.gz" -C "swan${SWAN_VER}"
fi
cd "$SRC/swan${SWAN_VER}/swan${SWAN_VER}"

# OpenMP, not MPI: this is one shared-memory box, so threads beat processes and
# there is no interconnect to exploit. `make clean` also wipes macros.inc, so
# platform.pl + config must be re-run before every target or the build silently
# falls back to serial with no warning.
make clean >/dev/null 2>&1 || true
perl platform.pl >/dev/null
make config >/dev/null
nice make omp
cp swan.exe "$BIN/swan-omp.exe"

echo "=== 4/4 verify SWAN computes, not merely links ==="
# A binary that starts proves nothing. Force 1.5 m @ 9 s on the west boundary of a
# flat 20 m basin and check the boundary node reproduces it.
T=$(mktemp -d)
printf "20. 20.\n20. 20.\n" > "$T/bot.dat"
cat > "$T/INPUT" <<'EOF'
PROJ 'smoke' '01'
SET NAUTICAL
MODE STATIONARY TWODIMENSIONAL
CGRID REGULAR 0. 0. 0. 2000. 2000. 20 20 CIRCLE 36 0.04 0.5 25
INPGRID BOTTOM REGULAR 0. 0. 0. 1 1 2000. 2000.
READINP BOTTOM 1. 'bot.dat' 1 0 FREE
BOUND SHAPESPEC JONSWAP 3.3 PEAK DSPR DEGREES
BOUNDSPEC SIDE W CONSTANT PAR 1.5 9.0 270. 20.
WIND 10. 270.
GEN3
BREAKING
FRICTION JONSWAP
NUM ACCUR 0.02 0.02 0.02 98. STAT 15
TABLE 'COMPGRID' HEAD 'out.tab' XP YP DEP HSIGN TPS DIR
COMPUTE
STOP
EOF
( cd "$T" && OMP_NUM_THREADS="$(nproc)" "$BIN/swan-omp.exe" >run.log 2>&1 )
if [ -s "$T/Errfile" ]; then echo "SWAN reported errors:"; head -5 "$T/Errfile"; exit 1; fi
HS=$(awk 'NR==8{print $4}' "$T/out.tab")
echo "  boundary node Hsig = ${HS} m (forced 1.5 m)"
awk -v h="$HS" 'BEGIN{ if (h<1.4 || h>1.6) { print "  UNEXPECTED - smoke test failed"; exit 1 } print "  smoke test OK" }'
rm -rf "$T"

cat <<'NOTE'

=== done ===
  ~/bin/swan-omp.exe   SWAN 41.51, OpenMP (run with OMP_NUM_THREADS=$(nproc))
  ~/src/swan4151/      source, rebuildable

MPI is deliberately NOT built. `make mpi` compiles with mpifort but switch.pl does
not enable the MPI code paths, so it emits a binary byte-identical to the serial
one with zero MPI libraries linked - a file named "mpi" that quietly runs on one
core. Nothing is lost: MPI distributes across machines, and this is a single box
where OpenMP already uses every core.
NOTE
