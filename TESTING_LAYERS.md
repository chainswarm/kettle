# TEE Subnet Testing Layers

> **State of the art.** Most blockchain/AI subnets ship with no test strategy — you register a node and pray. This template provides a structured, four-layer testing architecture where every layer is independently runnable and each one gives you stronger guarantees than the last.

---

## The Core Insight

Every miner/validator/overwatch interaction goes through one seam:

```python
db.nmap_set(topic, key, value)
db.nmap_get(topic, key)
```

Swap the DHT implementation and you change the environment. That single abstraction is what makes the four layers possible.

```
Layer 1  DHT in-memory    │ pytest         │ milliseconds   │ unit tests
Layer 2  docker-compose   │ real P2P       │ seconds        │ integration
Layer 3  Hypertensor      │ real chain     │ minutes/epoch  │ staging
Layer 4  mainnet          │ real TEE HW    │ live           │ production
```

---

## Layer 1 — In-Memory (Unit Tests)

**What it is:** The entire subnet logic runs in-process. `RocksDB(tmp_path)` acts as the DHT. No network, no docker, no chain.

**How to run:**
```bash
pytest tests/
```

**What it proves:**
- Miner protocol produces valid work records
- Validator detects tampered parity (wrong odd/even claim)
- Overwatch independently re-derives and cross-checks results
- TEE quote hash binding is correct
- Scoring formula is accurate (`tee_score × parity_correct`)
- Fault injection (`TAMPER_RATE`) fires at the right rate

**Why it works:**
The `MockNodeProtocol` and `MockOverwatchVerifier` use the same `db` instance as the tests. No mocking frameworks, no fakes — just the real code running with a tmp directory for storage.

**Speed:** `pytest tests/test_mock_node.py` runs in ~1.4 s (24 tests). The full in-scope suite (`pytest tests/`) runs in ~5 s (181 tests, 1 skipped) due to RocksDB `tmp_path` setup overhead. `tests/hypertensor/` requires a live Substrate node and is excluded from the default run.

**When to run:** On every commit. CI gate.

**Key files:**
```
tests/test_mock_node.py         ← miner / validator / scorer / overwatch
tests/tee/test_verifier.py      ← DCAP 7-step verification
tests/tee/test_consensus_integration.py
subnet/node/mock.py             ← TAMPER_RATE, MockOverwatchVerifier
```

---

## Layer 2 — Docker Network (Integration Tests)

**What it is:** Real libp2p P2P network between docker containers. Nodes actually gossip over the wire. DHT records travel across the network. `MOCK_TEE=true` so no hardware needed.

**How to run:**
```bash
docker compose -f docker-compose.tee-dev.yml up --build
```

**What it proves:**
- DHT gossip works across containers (miner publishes → validator reads)
- Epoch loop timing is correct
- Tampered records are caught in a live multi-node environment
- TEE quote binding survives wire serialization
- Node startup/restart behaviour is stable

**The demo setup:**
```
bootnode   ← P2P entry point, no rewards
miner-1    ← TAMPER_RATE=1.0 (every epoch tampered — demo mode; production: 0.001)
miner-2    ← TAMPER_RATE=0.001 (honest reference)
validator  ← verifies both, scores each epoch
overwatch  ← audits all miners independently
```

With `TAMPER_RATE=1.0`, from epoch 3 onward, miner-1 is flagged every epoch by both validator and overwatch. This is visible in `docker compose logs validator`.

### Expected log output (TAMPER_RATE=1.0)

```bash
# Validator detects tamper on miner-1, scores miner-2 cleanly:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
# [Validator] peer=<miner-1-prefix> epoch=N score=0.00 correct=False
# [Validator] peer=<miner-2-prefix> epoch=N score=0.50 correct=True

# Overwatch independently confirms parity_mismatch on miner-1:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
# [Overwatch] TAMPER peer=<miner-1-prefix> epoch=N reason=parity_mismatch
# [Overwatch] PASS peer=<miner-2-prefix> epoch=N
```

**Key variables:**
```
MOCK_TEE=true            # mock TEE backend (default)
TAMPER_RATE=1.0  # demo mode; production: 0.001
EPOCH_DURATION_SECS=12   # speed up for dev
```

**Speed:** Seconds per epoch.

**When to run:** Before opening a PR. Before testnet deployment.

**Key files:**
```
docker-compose.tee-dev.yml
subnet/server/server.py       ← epoch loop, _tee_publish_loop
subnet/node/mock.py           ← TAMPER_RATE controls fault injection
```

---

## Layer 3 — Hypertensor Testnet (Staging)

**What it is:** A real Hypertensor testnet node. Subnet and nodes are registered on-chain. Validator submits scores as extrinsics. Overwatch can slash. `MOCK_TEE=true` is built-in — no AMD EPYC hardware required for testnet staging.

**Required environment variables:**
```
CHAIN_ENDPOINT   — Hypertensor testnet WebSocket URL
SUBNET_ID        — Subnet friendly ID (e.g. 1)
PHRASE           — Coldkey mnemonic (required for signing extrinsics)
```

**Step 0 — Verify chain connectivity first:**
```bash
# Check that the chain endpoint is reachable and your subnet has peers:
python scripts/check_peers.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1
# → [OK] Connected to wss://rpc.hypertensor.app:443
# → peer_id | hotkey | stake | classification
# → N nodes registered
# Exits 0 even if 0 nodes — connectivity is confirmed either way.
# Exits 1 with "ERROR: Cannot connect to ..." if the endpoint is unreachable.
```

**How to run:**
```bash
# Full testnet stack (1 bootnode + 1 validator + 2 miners):
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=1 \
PHRASE="word word word word word word word word word word word word" \
docker compose -f docker-compose.chain.yml up --build
```

If `CHAIN_ENDPOINT` or `SUBNET_ID` are unset, Docker Compose aborts before starting any container:
```
variable CHAIN_ENDPOINT is not set. CHAIN_ENDPOINT is required for chain mode
```
This prevents silent misconfiguration where nodes start but talk to nothing.

**What it proves:**
- `SubnetInfoTracker` reads the real peer list from chain (not config file)
- Validator extrinsic submission works (`submit_score`)
- Token emissions are proportional to scores
- Overwatch slash reports land on-chain
- Node registration + staking flow is correct

**Expected validator log output (real chain):**
```bash
docker compose -f docker-compose.chain.yml logs validator | grep "Synced\|\[Validator\]"
# [Validator] Synced: epoch=N, pct=0.87  ← real chain epoch numbers
# [Validator] peer=<peer_id_prefix> epoch=N score=0.50 correct=True
```

**Validate the compose file without running it:**
```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config > /dev/null && echo "OK"
```

**Inspect failure state:**
```bash
# Missing CHAIN_ENDPOINT → clear error before any container starts:
docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "CHAIN_ENDPOINT"

# Wrong endpoint → node container exits with WebSocket error in logs:
docker compose -f docker-compose.chain.yml logs bootnode 2>&1 | grep "ERROR:\|Cannot connect"
```

**Key differences vs Layer 2:**
```
docker-compose.tee-dev.yml   ← --no_blockchain_rpc, mock chain DB, no env vars needed
docker-compose.chain.yml     ← real chain, DEV_RPC=CHAIN_ENDPOINT, PHRASE required for signing
```

**Speed:** Minutes per epoch (real chain cadence).

**When to run:** Before mainnet. After any chain-facing code change.

```bash
# After each epoch — verify scores submitted to chain:
python scripts/check_scores.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --epoch N
# → [OK] Scores found for epoch N: X entries
# → [WARN] No scores found for epoch N  ← normal for first 2-3 epochs

# Verify slash events (set TAMPER_RATE=1.0 to force a slash):
python scripts/check_slash.py \
  --chain wss://rpc.hypertensor.app:443 \
  --overwatch_node_id 1 \
  --epoch N
# → [OK] 1 commit(s) found  / [OK] 1 reveal(s) found

# Combined Layer 3 smoke test (delegates to all three check scripts):
python scripts/smoke_test_chain.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1 \
  --epoch N \
  --overwatch_node_id 1
# → [PASS] check_peers.py
# → [PASS] check_scores.py
# → [PASS] check_slash.py
# Exits 0 only when all three pass.
```

**See also:** `CHAIN.md` for full registration walkthrough and `[WARN]` vs `[OK]` semantics; `scripts/check_peers.py --help`, `scripts/check_scores.py --help`, `scripts/check_slash.py --help`, `scripts/smoke_test_chain.py --help` for full usage.

---

## Layer 4 — Mainnet + Real TEE

**What it is:** Production. Real Hypertensor mainnet. Real TEE hardware via **Gramine/SGX**. Real DCAP verification. Real token emissions.

**Additional requirements vs Layer 3:**
```
# Production requires Gramine/SGX (see GRAMINE.md)
MOCK_TEE=false
EXPECTED_MEASUREMENT=<MRENCLAVE from gramine-sgx-sign>
MIN_TEE_SCORE=1.0
# Mount SGX devices: /dev/sgx_enclave, /dev/sgx_provision
```

**Note:** CVM-only deployments (SEV-SNP, TDX without Gramine) are not production-safe — the operator can modify code at runtime while attestation reports still show the original measurement.

**What changes:**
- `TeeBackend.TDX` or `TeeBackend.SEV_SNP` instead of `MOCK`
- `tee_score = 1.0` for real hardware (vs `0.5` for mock)
- DCAP full certificate chain verification (not skipped)
- Identity binding: `report_data = sha256(peer_id + ":" + epoch)`

**Speed:** Real epoch cadence (chain-defined).

---

## Why DHT Is the Secret

In a traditional subnet, the workflow is:
```
write code → deploy to chain → wait for epoch → observe → debug → repeat
```
Iteration cycle: **hours**.

With this architecture:
```
write code → pytest → docker → testnet → mainnet
             10ms    10s      minutes    hours
```

You catch 95% of bugs in Layer 1 before anything touches a network.

The DHT abstraction (`db.nmap_get/set`) is not incidental — it is the design. Every subnet primitive (quote publication, work results, overwatch records) goes through it. Swap the implementation, change the environment.

---

## Testing Matrix

| Scenario | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| Miner publishes valid work | ✅ | ✅ | ✅ | ✅ |
| Validator detects tampered parity | ✅ | ✅ | ✅ | ✅ |
| Overwatch independent audit | ✅ | ✅ | ✅ | ✅ |
| TEE quote binding correct | ✅ | ✅ | ✅ | ✅ |
| DHT gossip over real P2P | ❌ | ✅ | ✅ | ✅ |
| Score submitted to chain | ❌ | ❌ | ✅ | ✅ |
| Slash report lands on-chain | ❌ | ❌ | ✅ | ✅ |
| Real token emissions | ❌ | ❌ | ✅ | ✅ |
| Real DCAP hardware attestation | ❌ | ❌ | ❌ | ✅ |

---

## For Subnet Forks

When you fork this template and replace `subnet/node/` with your own logic:

1. **Layer 1 first.** Write tests for your `NodeProtocol` and `NodeScoring` before touching docker or chain. The `RocksDB(tmp_path)` pattern gives you instant feedback.

2. **Keep `TAMPER_RATE`.** Fault injection is not just for demos — it's how you verify your validator and overwatch actually catch failures before you're on mainnet.

3. **Never skip a layer.** The layers exist because each one finds different bugs. A test that passes in Layer 1 but fails in Layer 2 means your code has a timing or serialization assumption. A test that passes in Layer 2 but fails in Layer 3 means your chain integration is wrong.

4. **Add overwatch tests before chain.** Overwatch is your last line of defence. If it doesn't work in Layer 1, it won't work on mainnet.
