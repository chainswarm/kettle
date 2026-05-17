# High-Level Architecture — Hypertensor TEE Subnet Template

> Covers **M001 through M005**. Reflects the codebase as of 2026-03-17 (194 tests, 1 skipped).

---

## 1. What This Is

A drop-in template for building a **TEE-native Hypertensor subnet**. Operators start from this
repo, adapt the mock job (odd/even parity), and get all the hard plumbing for free:

- Hardware identity and code-integrity proofs (DCAP attestation) wired into consensus scoring
- Encrypted miner channels and signed outputs (RA-TLS, no external CA)
- On-chain peer discovery, epoch-cadence score submission, and overwatch slash reporting
- Full `MOCK_TEE=true` mode — every path exercisable on any machine, no AMD EPYC required

The architecture is layered. Each layer was validated independently before the next was built:

| Layer | Milestone | Description |
|---|---|---|
| L1 — Attestation | M001 | TEE quotes, identity binding, DCAP verification, `tee_score` in consensus |
| L2 — Confidential Compute | M002 | RA-TLS, encrypted work items, signed outputs, sealed storage, Gramine |
| L3 — In-memory test harness | M003 | `MockNodeProtocol`, overwatch, `TAMPER_RATE` fault injection |
| L4 — Docker network | M004 | Multi-container epoch loop, live tamper detection, restart recovery, observability |
| L5 — Chain integration | M005 | Chain peer discovery, score extrinsic, slash commit+reveal, developer toolchain |

---

## 2. Node Roles

Every container runs the same binary (`subnet.cli.run_node`). Role is determined by CLI flags and env vars:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hypertensor Testnet                          │
│   (peer registration, score extrinsics, slash extrinsics)        │
└──────────────────────┬──────────────────────────────────────────┘
                       │  WebSocket RPC (DEV_RPC / CHAIN_ENDPOINT)
         ┌─────────────┼─────────────────────────────┐
         │             │                             │
    ┌────▼────┐  ┌─────▼──────┐  ┌──────────────────▼──────────┐
    │ Bootnode│  │  Validator  │  │    Miner-1 / Miner-2        │
    │         │  │             │  │                             │
    │ libp2p  │  │ scores peers│  │ generates TEE quote         │
    │ routing │  │ submits     │  │ publishes to DHT            │
    │ only    │  │ propose_    │  │ responds to validator calls │
    │         │  │ attestation │  │ TAMPER_RATE fault injection │
    │         │  │ slashes via │  │                             │
    │         │  │ commit+     │  │                             │
    │         │  │ reveal      │  │                             │
    └─────────┘  └─────────────┘  └─────────────────────────────┘
         │             │                             │
         └─────────────┴─────────────────────────────┘
                   libp2p / GossipSub mesh
               (heartbeat, mock_work, TEE quotes, RA-TLS certs)
```

---

## 3. Request / Epoch Flow

One epoch cycle — everything that happens between consecutive epoch transitions:

```
Epoch N begins
     │
     ├─ MINER (each miner independently)
     │   ├─ 1. Generate TEE quote: MockBackend.generate_quote(peer_id, epoch)
     │   │      → TeeQuote{nonce=N, report_data=sha256(peer_id:N), measurement, ...}
     │   ├─ 2. Publish quote to DHT: nmap_set(TEE_QUOTE_TOPIC, f"{N}:{peer_id}", quote)
     │   ├─ 3. Generate RA-TLS cert: RaTlsServer(peer_id, epoch, backend)
     │   │      → ephemeral self-signed cert with DCAP quote in X.509 extension
     │   ├─ 4. Publish cert_pem to DHT: nmap_set(RATLS_CERT_TOPIC, f"{N}:{peer_id}", cert_pem)
     │   ├─ 5. Do the job (parity check): pick random n, report "even"|"odd"
     │   │      → tamper with probability TAMPER_RATE (fault injection)
     │   ├─ 6. Encrypt work item with session key (AES-256-GCM via WorkEnvelope)
     │   │      session_key = HKDF-SHA256(sha256(cert_pubkey), f"{peer_id}:{N}")
     │   ├─ 7. Sign output with session key (HMAC-SHA256 via OutputEnvelope)
     │   └─ 8. Publish OutputEnvelope to DHT: nmap_set(mock_work, f"{N}:{peer_id}", envelope)
     │
     ├─ VALIDATOR (scoring epoch N-1, reading prior epoch's DHT records)
     │   ├─ 1. Query chain for registered peers:
     │   │      hypertensor.get_min_class_subnet_nodes_formatted(subnet_id, epoch-1, Validator)
     │   ├─ 2. For each non-self peer:
     │   │   ├─ a. validator_call(peer_id, epoch-1) → fetch OutputEnvelope from DHT
     │   │   ├─ b. Verify RA-TLS cert (DCAP quote embedded in cert extension)
     │   │   ├─ c. DcapVerifier.verify(peer_id, epoch-1) → VerificationResult{score: 0.0|0.5|1.0}
     │   │   │      - debug_mode=True → 0.0
     │   │   │      - nonce mismatch → 0.0 (stale/replayed)
     │   │   │      - identity binding: sha256(peer_id:epoch) != report_data → 0.0
     │   │   │      - chain verify: HMAC (mock) or x509 DCAP (real HW)
     │   │   │      - measurement mismatch → 0.0
     │   │   │      - TCB policy → 0.5 or 1.0
     │   │   ├─ d. Verify OutputEnvelope signature (HMAC-SHA256 with session key)
     │   │   ├─ e. Re-check parity: n % 2 → expected == reported?
     │   │   └─ f. score_peer() → PeerScore{score: tee_score * correctness_score}
     │   └─ 3. ChainScoreSubmitter.submit(scores)
     │          → propose_attestation(subnet_id, data=[{subnet_node_id, score}, ...])
     │          → int(float_score * 1e18) planck-scale conversion
     │
     ├─ OVERWATCH (auditing epoch N-1, runs in validator process, 35s offset)
     │   ├─ 1. For each non-self peer:
     │   │   ├─ a. MockOverwatchVerifier.verify(peer_id, epoch-1)
     │   │   │      → fetch raw OutputEnvelope from DHT (no session key needed)
     │   │   │      → re-check n % 2 == parity? independently of validator
     │   │   │      → returns OverwatchResult{ok, reason, details}
     │   │   └─ b. if reason == "parity_mismatch" AND OVERWATCH_NODE_ID is set:
     │   │          ChainOverwatchReporter.slash(peer_id, epoch-1, details)
     │   │          → salt = os.urandom(32)
     │   │          → commit_hash = sha256(0x00_bytes + salt)   [_PUNISH_WEIGHT=0]
     │   │          → commit_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, commit_hash}])
     │   │          → reveal_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, weight=0, salt}])
     │   └─ 2. Log [Overwatch] PASS / TAMPER per peer per epoch
     │
     └─ CHAIN (Hypertensor SubnetModule pallet)
         ├─ Receives propose_attestation → stores in SubnetConsensusSubmission
         ├─ Receives commit_overwatch_subnet_weights → stores commit
         ├─ Receives reveal_overwatch_subnet_weights → processes slash, reduces stake
         └─ At epoch finalisation: computes proportional token emissions from scores
```

---

## 4. Module Map

### 4.1 TEE Layer (`subnet/tee/`)

The attestation core, built in M001–M002.

```
subnet/tee/
├── backends/
│   ├── base.py          TeeBackendBase — interface: generate_quote(peer_id, epoch) → TeeQuote
│   ├── mock.py          MockBackend — HMAC-based quote, key=_MOCK_KEY; returns score=0.5
│   ├── tdx.py           TdxBackend — /dev/tdx_guest IOCTL; real TDX DCAP quote
│   └── sev_snp.py       SevSnpBackend — /dev/sev-guest IOCTL; AMD SEV-SNP report
├── quote.py             TeeQuote schema + DHT key helpers (TEE_QUOTE_TOPIC)
├── publisher.py         TeePublisher — one-shot per epoch: backend.generate_quote() → DHT
├── verifier.py          DcapVerifier — 7-step pipeline → VerificationResult{score: 0.0|0.5|1.0}
├── config.py            TeeConfig — backend, mock_key, expected_measurement, min_tee_score, tcb_strict
├── ratls/
│   ├── cert.py          RaTlsCertBundle — ephemeral X.509 cert with DCAP quote in extension
│   ├── server.py        RaTlsServer — cert generation; trio serve() for real TLS
│   ├── client.py        RaTlsClient — TLS connect; inline DCAP quote verification at handshake
│   ├── session.py       RaTlsSession — session_key = HKDF-SHA256(cert_pubkey, peer_id:epoch)
│   │                                   encrypt()/decrypt() via AES-256-GCM; sign()/verify() via HMAC
│   └── envelope.py      WorkEnvelope (AES-GCM encrypted work item)
│                        OutputEnvelope (HMAC-SHA256 signed result)
└── sealed/
    └── store.py         SealedStore — AES-256-GCM keyed by sha256(measurement)
                                       only same enclave binary can unseal
```

**DcapVerifier pipeline** (step-by-step, first failure short-circuits to 0.0):

```python
1. DHT fetch:       nmap_get(TEE_QUOTE_TOPIC, f"{epoch}:{peer_id}") → TeeQuote | None
2. Debug check:     quote.debug_mode → reject (0.0)
3. Freshness:       quote.nonce != current_epoch → reject (stale/replayed)
4. Identity bind:   sha256(f"{peer_id}:{epoch}") != quote.report_data → reject (Sybil)
5. Chain verify:    mock → HMAC(MOCK_KEY, payload); real → x509 DCAP chain (PCK → CA → Root)
6. Measurement:     EXPECTED_MEASUREMENT set AND != quote.measurement → reject
7. TCB policy:      UpToDate → 1.0; SWHardeningNeeded (permissive) → 0.5; strict → 0.0
```

**Score semantics:**

| `tee_score` | Condition |
|---|---|
| `1.0` | Real hardware, full DCAP chain, UpToDate TCB, debug=False, correct measurement |
| `0.5` | Mock backend (MOCK_TEE=true) or degraded TCB (permissive policy) |
| `0.0` | Any verification failure |

Final score = `tee_score * correctness_score`. Nodes below `MIN_TEE_SCORE` earn 0 emissions.

---

### 4.2 Node Layer (`subnet/node/`)

The mock job — the part operators replace with their actual task.

```
subnet/node/
├── protocol.py          BaseNodeProtocol — abstract; miner_loop(epoch), validator_call(peer_id, epoch)
├── scoring.py           BaseNodeScoring — abstract; score_peer(result, epoch) → PeerScore
└── mock.py              Concrete implementations for odd/even parity job:
```

**`MockNodeProtocol`** (`subnet/node/mock.py`)

Miner path per epoch:
1. `TeePublisher.publish(epoch)` → DCAP quote to DHT
2. `RaTlsServer(peer_id, epoch, backend)` → ephemeral cert; publish cert_pem to DHT
3. Pick random `n`, compute `n % 2`, apply `TAMPER_RATE` fault injection
4. Encrypt via `WorkEnvelope` (AES-GCM); sign via `OutputEnvelope` (HMAC); publish to DHT

Validator path per epoch:
1. Fetch `OutputEnvelope` from DHT
2. Verify RA-TLS cert (quote in extension)
3. Verify `OutputEnvelope.signature` (session key from cert)
4. Re-check parity: `n % 2 == reported`?

**`MockOverwatchVerifier`** — independent audit path (no session key):
- Fetches raw DHT record
- Re-checks parity without using the RA-TLS session
- Returns `OverwatchResult{ok, reason, details}`
  - `reason="no_work_record"` — cold start (first 1-2 epochs), logged at DEBUG
  - `reason="parity_mismatch"` → triggers `ChainOverwatchReporter.slash()`

**`TAMPER_RATE`** — env var `TAMPER_RATE` (float, default `0.001`). Set to `1.0` to force every
epoch to produce a tampered result, confirming the full detection → slash pipeline.

**`MockNodeScoring`** — wraps `DcapVerifier` in the scoring path. Produces `PeerScore{score}` where
score is `tee_score * (1.0 if correct else 0.0)`.

---

### 4.3 Consensus Layer (`subnet/consensus/`)

The chain submission layer, built in M005.

```
subnet/consensus/
├── chain_submitter.py       ChainScoreSubmitter
├── chain_overwatch_reporter.py  ChainOverwatchReporter
├── consensus.py             Consensus — coordinates get_scores() and chain epoch management
└── utils.py
```

**`ChainScoreSubmitter`**

```python
class ChainScoreSubmitter:
    def __init__(self, hypertensor, subnet_id: int)
    def submit(self, scores: List[SubnetNodeConsensusData]) -> ExtrinsicReceipt | None
```

- `asdict(s)` serialises each `SubnetNodeConsensusData` → `{"subnet_node_id": N, "score": M}`
- Delegates to `hypertensor.propose_attestation(subnet_id, data=...)` — no retry duplication
- Returns `receipt` on both success and failure (check `receipt.is_success`)
- Returns `None` on exception; logs `⚠️ Score submission failed:` / `Score submission exception:`
- Empty list passes through unchanged (no short-circuit — chain accepts empty submissions)
- **Call site:** `server.py:618` — once per epoch after the per-node scoring loop

**`ChainOverwatchReporter`**

```python
class ChainOverwatchReporter:
    def __init__(self, hypertensor, overwatch_node_id: int, subnet_id: int)
    def slash(self, peer_id: str, epoch: int, evidence=None) -> ExtrinsicReceipt | None
```

Commit+reveal protocol:
```
salt = os.urandom(32)                          # fresh per slash, not persisted
commit_hash = sha256(0x00_bytes_16 + salt)     # _PUNISH_WEIGHT = 0
commit_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, weight=commit_hash}])
reveal_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, weight=0, salt=salt}])
```

- Early return on commit failure (reveal not called); returns commit receipt
- Returns reveal receipt on full success
- Returns `None` on exception; logs `⚠️ Overwatch commit/reveal failed:`
- **Guard:** instantiated only when `OVERWATCH_NODE_ID` is set; `reporter=None` otherwise
  — MOCK_TEE mode is structurally unaffected when the env var is absent
- **Call site:** `server.py:700` — inside `parity_mismatch` branch of `_overwatch_epoch_loop`

---

### 4.4 Server (`subnet/server/server.py`)

The process runtime. All epoch loops run as concurrent `trio` tasks in one nursery.

```
Server.run()
  └─ trio nursery
      ├─ _miner_epoch_loop        — publishes quote + work each epoch
      ├─ _validator_scoring_loop  — scores peers; calls ChainScoreSubmitter.submit()
      ├─ _overwatch_epoch_loop    — audits peers; calls ChainOverwatchReporter.slash()
      ├─ _health_server(8080)     — HTTP GET → {"status":"ok"} (trio-based, no framework)
      ├─ publish_heartbeat_loop   — GossipSub heartbeat topic
      └─ consensus._main_loop     — Consensus epoch management (if enable_consensus)
```

**Loop startup offsets** (mesh formation delay):
- Validator scoring: `await trio.sleep(30)` — waits for GossipSub mesh + miner gossip
- Overwatch: `await trio.sleep(35)` — 5s more than validator, ensuring work records exist

**Score accumulation pattern** in `_validator_scoring_loop`:
```python
scores = []                           # reset at top of each epoch
for node in nodes:
    try:
        result = await protocol.validator_call(peer_id, score_epoch)
        peer_score = await scoring.score_peer(result, score_epoch)
        scores.append(SubnetNodeConsensusData(
            subnet_node_id=node.subnet_node_id,
            score=int(peer_score.score * 1e18),   # planck-scale integer
        ))
    except Exception:
        pass   # silently omit failed peers; consistent with existing error handling
if scores:
    submitter.submit(scores)          # single batch extrinsic per epoch
```

---

### 4.5 Hypertensor Layer (`subnet/hypertensor/`)

Python bindings to the Hypertensor Substrate chain.

```
subnet/hypertensor/
├── chain_functions.py   Hypertensor class — all on-chain calls
├── chain_data.py        Data classes: SubnetNodeInfo, SubnetNodeConsensusData,
│                        OverwatchCommit, OverwatchReveals, PeerInfo, ...
├── config.py            BLOCK_SECS, EPOCH_LENGTH, SECONDS_PER_EPOCH
│                        (NOT LOCAL_RPC or DEV_RPC — those are env var names only)
├── helpers.py
└── mock/
    ├── local_chain_functions.py  LocalHypertensor for MOCK_TEE mode
    └── mock_db.py                MockChainDB — in-memory chain state
```

**`Hypertensor(url, phrase)`** — constructed once at server startup.  
`phrase` must be a valid mnemonic (even for read-only queries — keypair is created eagerly).

Key methods used by the subnet:

| Method | Used by |
|---|---|
| `get_subnet_nodes_info_formatted(subnet_id)` | `check_peers.py`, `_validator_scoring_loop` |
| `get_min_class_subnet_nodes_formatted(subnet_id, epoch, class)` | `_validator_scoring_loop`, `_overwatch_epoch_loop` |
| `get_subnet_id_from_friendly_id(friendly_id)` | All scripts — friendly-ID resolution |
| `get_subnet_slot(subnet_id)` | Both epoch loops — slot/epoch state |
| `get_subnet_epoch_data(slot)` | Both epoch loops — current epoch number |
| `propose_attestation(subnet_id, data=[...])` | `ChainScoreSubmitter.submit()` |
| `commit_overwatch_subnet_weights(node_id, weights)` | `ChainOverwatchReporter.slash()` |
| `reveal_overwatch_subnet_weights(node_id, reveals)` | `ChainOverwatchReporter.slash()` |
| `get_rewards_submission(subnet_id, epoch)` | `check_scores.py` |
| `get_overwatch_commits(epoch, node_id)` | `check_slash.py` |
| `get_overwatch_reveals(epoch, node_id)` | `check_slash.py` |
| `register_subnet(...)` | `register_subnet.py` |
| `register_subnet_node(...)` | `register_node.py` |

**Friendly-ID resolution** — any ID `< 128000` is a friendly ID, not the real chain ID:
```python
if subnet_id < 128000:
    real_id = int(str(hypertensor.get_subnet_id_from_friendly_id(subnet_id)))
else:
    real_id = subnet_id
```
All four check scripts, both registration scripts, and both epoch loops apply this pattern.

**RPC endpoint resolution** — matches `run_node.py` convention:
```
Priority: --local_rpc > --chain > $DEV_RPC > wss://rpc.hypertensor.app:443
```
`LOCAL_RPC` and `DEV_RPC` are **env var names** resolved via `os.environ.get()` — there are no
module constants for them in `config.py`.

---

### 4.6 Utilities

**`subnet/utils/logging.py` — `JsonFormatter`** (M004)

Structured JSON log formatter activated via `LOG_JSON=true`:
```json
{"timestamp": "2026-03-17T12:34:56.123Z", "level": "INFO",
 "logger": "validator_scoring_loop", "message": "[Validator] peer=12D3Koo...",
 "epoch": 5, "peer": "12D3KooW", "score": 0.5}
```
Extra fields passed via `extra={"key": value}` merge at top level → queryable with `jq`.

```bash
docker compose logs --no-log-prefix validator | grep '"score"' | jq '.score'
```

**`subnet/utils/connections/bootstrap.py` — DNS multiaddr resolution** (M004)

py-libp2p's `TCPTransport.dial()` only handles `/ip4/` and `/ip6/` — not `/dns4/`. Bootstrap
addresses using Docker service names (`/dns4/bootnode/tcp/38960/...`) are pre-resolved to IP at
the application layer before being handed to libp2p.

**`subnet/utils/dht.py` — DHT operations**

`nmap_put(topic, key, value)` / `nmap_get(topic, key)` — the substrate for all cross-node data
exchange: TEE quotes, RA-TLS certs, work outputs. Backed by RocksDB in production,
`MockChainDB` in mock mode.

---

## 5. Chain Diagnostics Toolchain (`scripts/`)

Four scripts with identical structure — the canonical pattern for any future chain diagnostic:

```
scripts/
├── check_peers.py       → enumerate registered nodes (connectivity smoke-test)
├── check_scores.py      → query SubnetConsensusSubmission for an epoch
├── check_slash.py       → query overwatch commits + reveals for an epoch
├── smoke_test_chain.py  → delegates to all three; [PASS]/[FAIL] per check
├── register_subnet.py   → on-chain subnet registration
└── register_node.py     → on-chain node registration (with friendly-ID resolution)
```

**Shared pattern** across all six scripts:

```python
# 1. URL precedence
url = (local_rpc_constant if --local_rpc
       else args.chain if --chain
       else os.environ.get("DEV_RPC", _DEFAULT_DEV_RPC))

# 2. Credentials — read from env, never printed
phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""

# 3. Construction — exit 1 on any failure
try:
    hypertensor = Hypertensor(url, phrase)
except Exception as exc:
    print(f"ERROR: Cannot connect to {url}: {exc}", file=sys.stderr)
    sys.exit(1)

# 4. Friendly-ID resolution (check_peers, check_scores, register_node)
if subnet_id < 128000:
    real_id = int(str(hypertensor.get_subnet_id_from_friendly_id(subnet_id)))
```

**Output semantics** (consistent across all scripts):

| Prefix | Exit | Meaning |
|---|---|---|
| `[OK] ...` | 0 | Query succeeded, data found |
| `[WARN] No ... found` | 0 | Query succeeded, no data yet — normal for first 2-3 epochs |
| `ERROR: Cannot connect` | 1 | WebSocket connection or keypair failure |
| `ERROR: ...` (other) | 1 | Registration or query rejection |

**`smoke_test_chain.py`** — delegation pattern:
```python
for script_name, extra_args in sub_checks:
    result = subprocess.run([sys.executable, script_path] + extra_args, check=False)
    print("[PASS]" if result.returncode == 0 else f"[FAIL] {script_name} (exit {result.returncode})")
```
Never crashes on connection failure. Exits 0 only when all three sub-scripts pass.

---

## 6. Docker Compose Stacks

### `docker-compose.tee-dev.yml` — Local development (no chain)

All four nodes with `--no_blockchain_rpc` — chain calls are handled by `LocalHypertensor`
backed by `MockChainDB`. Full TEE flow exercisable on any machine. Used for M001–M004 validation.

### `docker-compose.chain.yml` — Testnet staging

Identical topology but chain-connected. Key differences:

```yaml
x-chain-env: &chain-env
  MOCK_TEE: "true"            # still no EPYC hardware required
  DEV_RPC: ${CHAIN_ENDPOINT:?...}   # CHAIN_ENDPOINT (user-facing) → DEV_RPC (run_node.py)
  PHRASE: ""                  # anchor = empty (bootnode is read-only)

# validator service overrides:
PHRASE: ${VALIDATOR_PHRASE:?...}    # :? = required; fails fast if unset
OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}
OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}  # :- = optional; omit to disable slash

# miner-1 / miner-2:
PHRASE: ${MINER1_PHRASE:?...}
PHRASE: ${MINER2_PHRASE:?...}
```

**Guard semantics:**
- `:?` — Docker Compose aborts before starting any container, with a descriptive error message
- `:-` — optional; feature is disabled (not an error) when unset
- Anchor `PHRASE: ""` — bootnode never accidentally inherits a signing credential

**No `--no_blockchain_rpc`** — the flag's absence is the switch: `run_node.py` detects the
presence of a `DEV_RPC` env var and connects to the real chain instead of `LocalHypertensor`.

---

## 7. CI (`./github/workflows/ci.yml`)

Three-layer CI on every push/PR to `main`:

```yaml
- name: Layer 1 — pytest
  run: pytest tests/ -x -q                   # blocking; 194 tests must pass

- name: Layer 2 — Docker Compose config
  run: docker compose -f docker-compose.tee-dev.yml config > /dev/null   # blocking

- name: Layer 3 — Chain smoke test
  continue-on-error: true                    # informational; no testnet in CI
  run: |
    python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1
    || echo "Chain smoke test: no testnet in CI (expected)"
```

Layer 3 is always `[FAIL]` in CI (no testnet available). This is deliberate (D011). Removing
`continue-on-error: true` requires a reliably reachable testnet endpoint via a CI secret.

---

## 8. Test Coverage

```
tests/
├── test_mock_node.py              24 tests — MockNodeProtocol end-to-end
│                                  runs in ~1.4–2.1s, no Docker required
├── tee/
│   ├── test_verifier.py           DcapVerifier — all 7 pipeline steps
│   ├── test_quote.py              TeeQuote schema + identity binding
│   ├── test_ratls.py              RaTlsServer / RaTlsClient / RaTlsSession
│   ├── test_sealed.py             SealedStore — seal/unseal, measurement binding
│   └── test_backends.py           Mock, TDX stub, SEV-SNP stub
├── consensus/
│   ├── test_chain_submitter.py    6 tests — ChainScoreSubmitter contract + wiring regression
│   └── test_chain_overwatch_reporter.py  5 tests — ChainOverwatchReporter all paths
└── conftest.py                    Excludes live-chain tests from default run
```

**`test_chain_submitter.py`** — verifies the complete submission contract:

| Test | What it covers |
|---|---|
| `test_submit_calls_propose_attestation_with_correct_params` | `subnet_id` forwarded; `asdict` serialisation; field names `subnet_node_id` + `score` |
| `test_submit_returns_receipt_on_success` | Receipt returned (not consumed) |
| `test_submit_empty_list_calls_through` | `data=[]` passes through — no short-circuit |
| `test_submit_logs_error_on_failed_receipt` | Failed receipt returned (not None); `BadProof` in error log |
| `test_submit_exception_returns_none` | `Exception` swallowed; returns `None` |
| `test_wiring_pattern_two_nodes` | 2-node score accumulation; `int(score * 1e18)` conversion; single `submit()` call |

**`test_chain_overwatch_reporter.py`**:

| Test | What it covers |
|---|---|
| `test_slash_calls_commit_and_reveal` | Both chain calls fire |
| `test_slash_returns_reveal_receipt_on_success` | Reveal receipt returned |
| `test_slash_returns_commit_receipt_when_commit_fails` | Reveal not called; commit receipt returned early |
| `test_slash_logs_error_on_failed_reveal` | `BadReveal` in error log |
| `test_slash_exception_returns_none` | Exception swallowed; returns `None` |

---

## 9. Observability Surfaces

**Structured logs** (pipe to `jq` when `LOG_JSON=true`):

```bash
# Score submissions per epoch:
docker compose logs --no-log-prefix validator | jq 'select(.message | contains("Submitted scores"))'

# Tamper detections:
docker compose logs --no-log-prefix validator | jq 'select(.message | contains("TAMPER"))'

# Slash commits:
docker compose logs --no-log-prefix validator | jq 'select(.message | contains("[Overwatch] Submitting"))'

# Score submission failures:
docker compose logs --no-log-prefix validator | grep "⚠️ Score submission failed"
```

**Health endpoint** (all non-bootnode containers):

```bash
curl http://localhost:8080/health
# → HTTP 200  {"status":"ok"}
```

When this responds, the trio event loop is alive and all nursery tasks are running.

**Chain state diagnostic commands**:

```bash
# Is the chain reachable?
python scripts/check_peers.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID

# Did this epoch's scores land on-chain?
python scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch N

# Did the slash commit land?
python scripts/check_slash.py --chain $CHAIN_ENDPOINT --overwatch_node_id $OW_ID --epoch N

# All three in one shot:
python scripts/smoke_test_chain.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID \
  --epoch N --overwatch_node_id $OW_ID
```

**Error taxonomy**:

| Signal | Location | Meaning |
|---|---|---|
| `[OK] Connected to wss://...` | check_*.py stdout | Chain reachable |
| `[WARN] No scores found for epoch N` | check_scores.py | Normal for first 2-3 epochs |
| `ERROR: Cannot connect to ...: [Errno 111]` | check_*.py stderr, exit=1 | No node at that URL |
| `[ValidatorLoop] Submitted scores epoch=N count=M` | validator logs | Submission fired |
| `⚠️ Score submission failed: BadProof` | validator logs | Chain rejected extrinsic |
| `[Overwatch] Submitting slash commit peer=...` | validator logs | Slash commit firing |
| `⚠️ Overwatch commit failed: ...` | validator logs | Chain rejected commit |
| `VALIDATOR_PHRASE is required` | compose stderr | Credential not set before `compose up` |

---

## 10. Known Limitations and Sharp Edges

**Salt not persisted (overwatch slash)**  
`os.urandom(32)` is generated inside `slash()` and not written to sealed storage. If the
validator process crashes between `commit_overwatch_subnet_weights` and `reveal_overwatch_subnet_weights`,
the reveal is permanently lost — the commit cannot be reconstructed. For production, write the salt to
`SealedStore` before broadcasting the commit.

**Slash is subnet-level, not peer-level**  
`commit_overwatch_subnet_weights` accepts subnet-level weights, not per-peer slash targets. The
`peer_id` and `epoch` args in `slash()` are logged only. If per-peer slashing is needed, the
Hypertensor `SubnetModule` pallet must expose a per-peer interface.

**`Hypertensor.__init__` creates keypair eagerly**  
Even for read-only queries, `Hypertensor(url, phrase)` creates a keypair immediately. An empty
`phrase` produces an error before the WebSocket even connects. Scripts that don't sign extrinsics
must still supply any valid mnemonic (or `TENSOR_PRIVATE_KEY`).

**GossipSub cold-start miss (first 1-2 epochs)**  
At cold start, miners publish gossip before the validator is in the mesh. `score=0.0` for the
first 1-2 epochs is expected behaviour — not a bug. Scores stabilise from epoch 3+ once the
GossipSub mesh is established.

**`MOCK_TEE=true` in chain stack**  
`docker-compose.chain.yml` has `MOCK_TEE=true` in all services. CVM backends (`TEE_BACKEND=tdx`
or `TEE_BACKEND=sev-snp`) are available for testing on real hardware but are **not production-safe**
— they don't protect against runtime code tampering. Production requires Gramine/SGX with
`MIN_TEE_SCORE=1.0` and `EXPECTED_MEASUREMENT` set to the MRENCLAVE hash. See `GRAMINE.md`.

**DNS multiaddr in py-libp2p**  
`TCPTransport.dial()` cannot resolve `/dns4/` multiaddrs. Bootstrap addresses using service names
must be pre-resolved to IP. See `subnet/utils/connections/bootstrap.py::_resolve_dns_multiaddr()`.

**Real x509 DCAP chain verification is a stub**  
`DcapVerifier` step 5 for TDX/SEV-SNP returns `True` without performing the full x509 chain
walk. Full DCAP verification (`sgx-dcap-quoteverify`) is the M006/mainnet integration point.
Mock backend HMAC verification is fully exercised in CI.

---

## 11. Running the Stack

### Local development (no chain, no hardware)

```bash
docker compose -f docker-compose.tee-dev.yml up --build
# All four containers start; validator produces score=0.50 for both miners from epoch 3+

# Structured logs:
docker compose -f docker-compose.tee-dev.yml logs --no-log-prefix validator | \
  grep '"score"' | jq '{epoch, peer, score}'

# Forced tamper detection:
docker compose -f docker-compose.tee-dev.yml up --build \
  -e MINER1_TAMPER_RATE=1.0   # validator + overwatch both flag every epoch
```

### Testnet staging (MOCK_TEE=true, real chain)

```bash
# 1. Verify connectivity:
python scripts/check_peers.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1

# 2. Register subnet (once):
PHRASE="..." python scripts/register_subnet.py --name "my-subnet" --chain wss://...

# 3. Register nodes:
PHRASE="..." python scripts/register_node.py --subnet_id 1 --hotkey 5Grw... --peer_id 12D3Koo...

# 4. Start stack:
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=1 \
VALIDATOR_PHRASE="..." MINER1_PHRASE="..." MINER2_PHRASE="..." \
OVERWATCH_PHRASE="..." OVERWATCH_NODE_ID=1 \
docker compose -f docker-compose.chain.yml up --build

# 5. Monitor (after a few epochs):
python scripts/check_scores.py --chain wss://... --subnet_id 1 --epoch 5
# → [OK] Scores found for epoch 5: 2 entries

# 6. Confirm slash (set TAMPER_RATE: "1.0" in miner service, restart):
python scripts/check_slash.py --chain wss://... --overwatch_node_id 1 --epoch 6
# → [OK] 1 commit(s) found for epoch 6
```

See `CHAIN.md` in the repo root for the full walkthrough including faucet, key generation,
and troubleshooting table.
