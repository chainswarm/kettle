# Chain Integration — Developer Walkthrough

End-to-end guide for registering a subnet, staking nodes, running the full stack, and monitoring
submissions on the Hypertensor testnet. No AMD EPYC hardware required — `MOCK_TEE=true` is the
default for testnet.

---

## Prerequisites

- **Python 3.11+**, **Docker** (with Compose v2), and the subnet repo cloned
- **Testnet HTSR tokens** — join the Discord at <https://discord.gg/hypertensor> and request tokens
  in the `#testnet-faucet` channel
- **A keypair mnemonic** — generate one with `subkey`:
  ```bash
  subkey generate
  # Secret phrase: word word word word word word word word word word word word
  # Public key (SS58): 5GrwvaEF...
  ```
  Any Polkadot-compatible wallet (e.g. Polkadot.js extension) works too.

**Required environment variables:**

| Variable | Description | Example |
|---|---|---|
| `CHAIN_ENDPOINT` | Hypertensor testnet WebSocket URL | `wss://rpc.hypertensor.app:443` |
| `SUBNET_ID` | Subnet friendly ID (integer) | `1` |
| `PHRASE` | Coldkey mnemonic for signing extrinsics | `word word word ...` |
| `TENSOR_PRIVATE_KEY` | Alternative to `PHRASE` (hex seed) | `0xabc123...` |

> Credentials are **read from env only** — never passed as CLI arguments or printed.

---

## Step 1 — Verify chain connectivity

Before registering anything, confirm your endpoint is reachable:

```bash
# Against the public testnet:
python scripts/check_peers.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1
# → [OK] Connected to wss://rpc.hypertensor.app:443
# → N nodes registered  (0 is fine before registration)

# Against a local Substrate node:
python scripts/check_peers.py --local_rpc --subnet_id 1
```

**Exit codes:** `0` = connectivity confirmed (even with 0 peers). `1` = `ERROR: Cannot connect to ...`

`[OK]` means the chain is reachable. `ERROR:` means a connection failure — check `CHAIN_ENDPOINT`
or try `--local_rpc` to confirm a local node is running.

---

## Step 2 — Register your subnet

```bash
PHRASE="word word word ..." \
python scripts/register_subnet.py \
  --chain wss://rpc.hypertensor.app:443 \
  --name "my-subnet" \
  --repo "https://github.com/yourorg/my-subnet" \
  --description "My TEE subnet" \
  --min_stake 1000000000000000000 \
  --max_stake 100000000000000000000
```

**Arguments:**

| Argument | Description | Default |
|---|---|---|
| `--name` | Human-readable subnet name | required |
| `--repo` | Source repository URL | `""` |
| `--description` | Short description | `""` |
| `--min_stake` | Minimum node stake (in HTSR base units, 18 decimals) | `1000000000000000000` |
| `--max_stake` | Maximum node stake (in HTSR base units) | `100000000000000000000` |
| `--max_cost` | Max cost in HTSR base units | `100000000000000000000` |
| `--chain` | RPC URL (defaults to `$DEV_RPC` or the public testnet) | |
| `--local_rpc` | Use `ws://127.0.0.1:9944` | |

**Expected output:**
```
[OK] Subnet registered: 0xabcdef1234567890...
```

> **Record the subnet ID** from the extrinsic receipt — you'll need it for node registration.
> The ID is typically assigned sequentially (1, 2, 3, …) by the chain.

---

## Step 3 — Register and stake your node(s)

Register each node separately. At least 2 nodes are recommended (1 validator + 1 miner).

```bash
# Register validator node:
PHRASE="word word word ..." \
python scripts/register_node.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --hotkey 5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY \
  --peer_id 12D3KooWEyoppNCUx8Yx66oV9fJnriXwCZXwDqqsMoNMBm9FXQYP \
  --stake 2000000000000000000

# Register a second node (miner) with a different PHRASE:
PHRASE="other mnemonic ..." \
python scripts/register_node.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --hotkey 5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty \
  --peer_id 12D3KooWSbGbx9x6JqMcPDmv3Y9xQJJr4Wb9D5NKXM5pjDFiAy2 \
  --stake 2000000000000000000
```

**Arguments:**

| Argument | Description |
|---|---|
| `--subnet_id` | Subnet ID obtained from Step 2 |
| `--hotkey` | SS58 public key of the node's hotkey account |
| `--peer_id` | libp2p peer ID (format: `12D3Koo...`) |
| `--stake` | Stake to add in HTSR base units (18 decimals) |

**Expected output:**
```
[OK] Node registered: 0x1234abcd...
```

Repeat for each node in your subnet.

---

## Step 3b — Register the overwatch node

The overwatch node audits validators and submits slash extrinsics when parity mismatches are
detected. It is a distinct node class — registered separately from miners and validators.

```bash
PHRASE="overwatch mnemonic ..." \
python scripts/register_overwatch_node.py \
  --chain wss://rpc.hypertensor.app:443 \
  --hotkey 5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy \
  --stake 1000000000000000000
```

**Expected output:**
```
[OK] Overwatch node registered: 0xabcd1234...

Next steps:
  1. Note the overwatch_node_id from the on-chain event (query via Polkadot.js or check_slash.py)
  2. Set in docker-compose.chain.yml (or env):
       OVERWATCH_NODE_ID=<id>
       OVERWATCH_PHRASE="<your mnemonic>"
```

The `overwatch_node_id` is assigned sequentially on-chain. You can also query it after
registration via [Polkadot.js Apps](https://polkadot.js.org/apps) under
`Network > Storage > Network > OverwatchNodeInfo`.

**Arguments:**

| Argument | Description |
|---|---|
| `--hotkey` | SS58 public key of the overwatch node's hotkey account |
| `--stake` | Stake in HTSR base units (default: 1 HTSR) |

---

## Step 4 — Run the full stack

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=1 \
VALIDATOR_PHRASE="validator mnemonic ..." \
OVERWATCH_PHRASE="overwatch mnemonic ..." \
OVERWATCH_NODE_ID=1 \
MINER1_PHRASE="miner1 mnemonic ..." \
MINER2_PHRASE="miner2 mnemonic ..." \
docker compose -f docker-compose.chain.yml up --build
```

For testing on real TEE hardware (e.g. Azure DCasv5/DCadsv5 with SEV-SNP), use
`docker-compose.tee-real.yml`. **Note:** CVM-only deployments are for testing, not
production — they are vulnerable to runtime code tampering. See [`GRAMINE.md`](GRAMINE.md)
for production deployment.

```bash
TEE_BACKEND=sev-snp \
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=1 \
VALIDATOR_PHRASE="validator mnemonic ..." \
OVERWATCH_PHRASE="overwatch mnemonic ..." \
OVERWATCH_NODE_ID=1 \
docker compose -f docker-compose.tee-real.yml up --build
```

**Notes:**
- `MOCK_TEE=true` is built-in for `docker-compose.chain.yml` — no AMD EPYC hardware required for testnet staging
- `docker-compose.tee-real.yml` targets real TEE hardware for testing; set `TEE_BACKEND=sev-snp` for Azure CVMs
- **Production requires Gramine/SGX** — CVM backends do not protect against runtime tampering by the operator
- `CHAIN_ENDPOINT`, `SUBNET_ID`, `OVERWATCH_PHRASE`, and `OVERWATCH_NODE_ID` are required; compose aborts before starting containers if unset
- Each node (validator, overwatch, miners) signs extrinsics with its own `PHRASE` env var
- The validator will not submit scores until at least 2 registered nodes have completed an epoch
- The overwatch node runs as a dedicated container (`chain-overwatch`) on port 38964 with its own key file (`dorothy.key`)
- The overwatch node begins auditing validators after 35s on first startup (mesh formation delay)

---

## Step 5 — Monitor with check scripts

After the stack is running, use these scripts to observe on-chain state epoch-by-epoch:

```bash
# Verify registered nodes (run any time):
python scripts/check_peers.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1

# After each epoch — verify scores submitted to chain:
python scripts/check_scores.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --epoch N

# Verify slash events (use TAMPER_RATE=1.0 in docker-compose.chain.yml to force a slash):
python scripts/check_slash.py \
  --chain wss://rpc.hypertensor.app:443 \
  --overwatch_node_id 1 \
  --epoch N
```

**`[WARN]` vs `[OK]` semantics:**

| Output | Meaning |
|---|---|
| `[OK] Scores found for epoch N: X entries` | Score data is present on-chain |
| `[WARN] No scores found for epoch N` | Epoch not yet finalised or no submission landed — **this is normal for the first 2-3 epochs** |
| `ERROR: Cannot connect to ...` | Connection failure — check `CHAIN_ENDPOINT` |

**Expected time-to-first-submission:** Typically 2-3 epochs after validator start (1 epoch for
libp2p mesh formation + 1 epoch scoring delay). If scores are not visible after 5 epochs:

```bash
docker compose -f docker-compose.chain.yml logs validator | grep "Score\|ERROR\|\[ValidatorLoop\]"
```

---

## Step 6 — Combined smoke test

Run all three check scripts in one shot:

```bash
python scripts/smoke_test_chain.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --epoch 5 \
  --overwatch_node_id 1
```

**Output:**
```
[PASS] check_peers.py
[PASS] check_scores.py
[PASS] check_slash.py
```

Exit code `0` = all three pass. Exit code `1` = one or more failed. The script never crashes on
connection failures — each sub-check prints `[FAIL] <script> (exit 1)` and the runner continues.

---

## Production configuration

For real-hardware deployments set these additional environment variables on your validators:

| Variable | Description | Example |
|---|---|---|
| `EXPECTED_MEASUREMENT` | Known-good MRENCLAVE / SNP measurement hex | `$(cat mrenclave.hex)` |
| `MIN_TEE_SCORE` | Minimum acceptable TEE score (0.0–1.0) | `1.0` |
| `TEE_BACKEND` | Backend to use (`sev-snp`, `tdx`, or unset for mock) | — |

**Production requires Gramine/SGX.** Extract the MRENCLAVE via `scripts/build-gramine.sh`:

```bash
export EXPECTED_MEASUREMENT="$(gramine-sgx-sigstruct-view --output-format=json gramine.manifest.sgx | jq -r '.enclave_hash')"
export MIN_TEE_SCORE=1.0
```

Validators with `DcapVerifier` will reject any quote whose measurement does not
match `EXPECTED_MEASUREMENT`. `MIN_TEE_SCORE=1.0` requires real hardware — no
mock quotes are accepted. See [`GRAMINE.md`](GRAMINE.md) for the full production
deployment guide.

### Overwatch salt persistence

`ChainOverwatchReporter` accepts an optional `sealed_store` argument. When
provided, the random salt used to fingerprint validator score submissions is
persisted across restarts via `SealedStore`, preventing an adversary from
replaying old salts after a crash. In production, pass a `SealedStore` instance
(`is_mock=False`) so the salt is derived from the enclave measurement rather than
an HMAC dev key.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: Cannot connect to wss://...` | Check `CHAIN_ENDPOINT`; try `check_peers.py --local_rpc` to confirm a local node is running |
| Compose aborts with `CHAIN_ENDPOINT is required` | Export `CHAIN_ENDPOINT` and `SUBNET_ID` before `docker compose up` |
| `[WARN] No scores found for epoch N` | Wait 3+ more epochs; this is normal early on — see Step 5 semantics above |
| Scores not appearing after 5+ epochs | `docker compose logs validator \| grep "[ValidatorLoop] Submitted"` — if absent, check `Score submission failed` lines |
| `[FAIL] check_peers.py (exit 1)` in smoke test | Run `check_peers.py` directly to see the raw `ERROR:` line |
| `register_subnet.py` exits 1 immediately | Check that `PHRASE` or `TENSOR_PRIVATE_KEY` is set in env |

> **`[WARN] No scores found` ≠ error.** See Step 5 for the full semantics.
