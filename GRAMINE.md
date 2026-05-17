# Running the Subnet Miner in Gramine (TDX/SGX)

This document explains how to run the Hypertensor subnet miner inside a TEE using Gramine.

## Prerequisites

- Intel SGX-capable hardware (Gramine SGX path) **or** any Linux host (Gramine Direct — dev/CI)
- Gramine 1.6+: https://gramine.readthedocs.io/en/stable/installation.html
- Intel SGX driver + AESM service running (SGX path only)

## Development mode (Gramine Direct — no hardware)

```bash
# Install Gramine
# sudo apt install gramine  (Ubuntu 22.04+)

# Generate manifest
gramine-manifest \
  -Dlog_level=warning \
  -Darch_libdir=/lib/x86_64-linux-gnu \
  gramine.manifest.template > gramine.manifest

# Run (no SGX attestation — for local dev only)
MOCK_TEE=true gramine-direct python3 -m subnet.cli.run_node \
  --private_key_path alith.key \
  --port 38961 \
  --subnet_id 1 \
  --subnet_node_id 1 \
  --no_blockchain_rpc \
  --base_path /data
```

## Production mode (Gramine SGX — real TDX attestation)

```bash
# 1. Generate and sign the manifest
gramine-manifest \
  -Dlog_level=warning \
  -Darch_libdir=/lib/x86_64-linux-gnu \
  gramine.manifest.template > gramine.manifest

gramine-sgx-sign \
  --manifest gramine.manifest \
  --output gramine.manifest.sgx

# 2. Extract MRENCLAVE (the measurement hash)
gramine-sgx-get-token --output gramine.token --sig gramine.manifest.sgx

# 3. Set EXPECTED_MEASUREMENT on validators
export EXPECTED_MEASUREMENT=$(gramine-sgx-sigstruct-view --output-format=json gramine.manifest.sgx | jq -r '.enclave_hash')

# 4. Run (attestation is live — validators verify MRENCLAVE)
TEE_BACKEND=tdx \
EXPECTED_MEASUREMENT=$EXPECTED_MEASUREMENT \
MIN_TEE_SCORE=1.0 \
TCB_POLICY=strict \
gramine-sgx python3 -m subnet.cli.run_node \
  --private_key_path miner.key \
  --port 38961 \
  --subnet_id 1 \
  --subnet_node_id 2 \
  --base_path /data
```

## Sealed storage

Sealed state is managed by `SealedStore` (`subnet/tee/sealed/store.py`). Two modes:

| `is_mock` | Mode | Key derivation |
|---|---|---|
| `True` | Development | HMAC-based dev key (no hardware required) |
| `False` | **Production** | Direct SHA-256 from enclave measurement (MRENCLAVE/SNP) |

In production (`is_mock=False`), the sealing key is derived directly from the
hardware measurement — only the exact signed binary (same MRENCLAVE) can decrypt
sealed entries.

Sealed blobs are stored as entries in the shared RocksDB at `--base_path`
(default: `/data`) under the `"sealed"` nmap column family. There is no separate
file or directory for sealed storage.

**No host-side setup is required** — the RocksDB at `/data` (mapped to
`/var/lib/hypertensor/db` on the host) already covers sealed blobs. Do **not**
create `/var/lib/hypertensor/sealed/` — sealed data lives in the RocksDB
`"sealed"` nmap column, not in a filesystem directory.

When you update the miner binary, MRENCLAVE changes → sealed state is inaccessible.
The miner will start fresh. This is intentional: it proves the new binary is clean.

## Measurement enforcement

Set `EXPECTED_MEASUREMENT` on all validators to the known-good MRENCLAVE.
Validators with `DcapVerifier` will reject any quote with a different measurement.

```bash
# On each validator
export EXPECTED_MEASUREMENT="$(cat mrenclave.hex)"
export MIN_TEE_SCORE=1.0  # require real hardware
```

## PCCS / collateral

For air-gapped deployments, set `PCCS_URL` to your local PCCS server:

```bash
export PCCS_URL="https://pccs.yourdomain.com/sgx/certification/v4"
```

Without `PCCS_URL`, the verifier fetches collateral from Intel's PCS directly.

## Azure Confidential VM (SEV-SNP) — testing only

Azure DCasv5/DCadsv5 VMs with SEV-SNP can be used for **testing** real TEE attestation.
The `SevSnpAzureBackend` reads the SNP attestation report from the vTPM (NV index 0x01400001).

```bash
TEE_BACKEND=sev-snp docker compose -f docker-compose.tee-real.yml up --build
```

**WARNING:** CVM-only deployments are **not production-safe**. The SEV-SNP launch measurement
is frozen at boot — an operator can modify code at runtime while attestation reports still
show the original measurement. See [anti-cheat §10a](docs/04-anti-cheat.md#10a-runtime-code-tampering-inside-a-cvm)
for the full threat analysis. Use Gramine/SGX for production.

## Docker + Gramine (production)

See `docker-compose.tee-dev.yml` for the mock development stack.
For production, replace `MOCK_TEE=true` with `TEE_BACKEND=tdx` and mount
`/dev/sgx_enclave` and `/dev/sgx_provision` into the container.

```yaml
devices:
  - /dev/sgx_enclave:/dev/sgx_enclave
  - /dev/sgx_provision:/dev/sgx_provision
volumes:
  - /var/lib/hypertensor/db:/data
```

> Do **not** mount `/var/lib/hypertensor/sealed/` — sealed data lives in the
> RocksDB `"sealed"` nmap column inside the database volume above.
