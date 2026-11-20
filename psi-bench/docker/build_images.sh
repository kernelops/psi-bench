#!/usr/bin/env bash
# Build the three Docker images used by psibench from the sibling protocol checkouts:
#   psi-volepsi  <- ../volepsi        (Ubuntu 24.04, GCC 13)
#   psi-bzs      <- ../BZS-MPSI       (Ubuntu 22.04, GCC 11)
#   psi-pepsi    <- ../pepsi/src+e2e  (Ubuntu 24.04, GCC 13)
# Usage: docker/build_images.sh [volepsi|bzs|pepsi ...]   (default: all three)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$HERE/../.." && pwd)"
LOGS="$HERE/../logs"
mkdir -p "$LOGS"

need_dir() {
  if [ ! -d "$WS/$1" ]; then
    echo "missing folder: $WS/$1" >&2
    echo "clone the protocol repositories next to psi-bench (see README.md, section 'Setup')" >&2
    exit 1
  fi
}

build_volepsi() { need_dir volepsi;    docker build -t psi-volepsi -f "$HERE/Dockerfile.volepsi" "$WS/volepsi"; }
build_bzs()     { need_dir BZS-MPSI;   docker build -t psi-bzs     -f "$HERE/Dockerfile.bzs"     "$WS/BZS-MPSI"; }
build_pepsi()   { need_dir pepsi;      "$HERE/build_pepsi.sh"; }

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(volepsi bzs pepsi)
for t in "${targets[@]}"; do
  echo "=== building $t (log: logs/build-$t.log)"
  case "$t" in
    volepsi) build_volepsi ;;
    bzs)     build_bzs ;;
    pepsi)   build_pepsi ;;
    *) echo "unknown target $t (use volepsi, bzs, pepsi)" >&2; exit 2 ;;
  esac 2>&1 | tee "$LOGS/build-$t.log" | tail -n 3
done
echo "done. images:"; docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E 'psi-(volepsi|bzs|pepsi)'
