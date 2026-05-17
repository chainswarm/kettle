#!/usr/bin/env bash
# build-gramine.sh — Reproducible Gramine manifest build for Hypertensor TEE miner
#
# Usage:
#   bash scripts/build-gramine.sh
#
# Environment variables (with defaults):
#   ARCH_LIBDIR  — architecture library dir (default: /lib/x86_64-linux-gnu)
#   LOG_LEVEL    — Gramine log level (default: warning)
#
# Output:
#   gramine.manifest      — generated manifest
#   gramine.manifest.sgx  — signed manifest (contains MRENCLAVE)
#   gramine.token         — SGX token
#   MRENCLAVE printed to stdout at the end
#
# Requires: gramine-manifest, gramine-sgx-sign, gramine-sgx-get-token,
#           gramine-sgx-sigstruct-view, python3
#
# After running, set EXPECTED_MEASUREMENT on validators:
#   export EXPECTED_MEASUREMENT=<printed MRENCLAVE>

set -euo pipefail

ARCH_LIBDIR="${ARCH_LIBDIR:-/lib/x86_64-linux-gnu}"
LOG_LEVEL="${LOG_LEVEL:-warning}"

echo "[gramine-build] Step 1/4: Generating manifest from template..."
gramine-manifest \
  -Dlog_level="$LOG_LEVEL" \
  -Darch_libdir="$ARCH_LIBDIR" \
  gramine.manifest.template > gramine.manifest
echo "[gramine-build] gramine.manifest generated."

echo "[gramine-build] Step 2/4: Signing manifest (requires SGX signing key)..."
gramine-sgx-sign \
  --manifest gramine.manifest \
  --output gramine.manifest.sgx
echo "[gramine-build] gramine.manifest.sgx signed."

echo "[gramine-build] Step 3/4: Generating SGX token..."
gramine-sgx-get-token \
  --output gramine.token \
  --sig gramine.manifest.sgx
echo "[gramine-build] gramine.token generated."

echo "[gramine-build] Step 4/4: Extracting MRENCLAVE..."
MRENCLAVE=$(gramine-sgx-sigstruct-view --output-format=json gramine.manifest.sgx \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('enclave_hash', d.get('mr_enclave', 'not_found')))")

echo ""
echo "[gramine-build] ============================================"
echo "[gramine-build] MRENCLAVE: $MRENCLAVE"
echo "[gramine-build] Done. Set EXPECTED_MEASUREMENT=$MRENCLAVE on validators."
echo "[gramine-build] ============================================"
