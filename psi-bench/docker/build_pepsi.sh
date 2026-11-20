#!/usr/bin/env bash
# Build the psi-pepsi image from the local pepsi checkout (src/ and e2e/ only).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEPSI="$(cd "$HERE/../../pepsi" && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
tar -C "$PEPSI" -cf - src e2e | tar -C "$STAGE" -xf -
docker build -t psi-pepsi -f "$HERE/Dockerfile.pepsi" "$STAGE"
