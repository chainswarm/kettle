# TEE Subnet Architecture

> **Audience:** Architects and senior developers who want to understand the full design before
> forking the template.  
> **After reading this:** You will understand the node topology, the epoch flow end-to-end,
> how each security layer fits together, and how to navigate the source code.  
> **Code-level detail:** See [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the full module map,
> exact function signatures, and line-level call paths.

---

## Contents

1. [Why these five layers](#1-why-these-five-layers)
2. [Node topology](#2-node-topology)
3. [Epoch flow — the full sequence](#3-epoch-flow)
4. [Security layers](#4-security-layers)
5. [RA-TLS — the encrypted channel](#5-ra-tls)
6. [Sealed storage](#6-sealed-storage)
7. [The testing pyramid](#7-the-testing-pyramid)
8. [How to navigate the source](#8-how-to-navigate-the-source)

---

## 1. Why these five layers

The architecture was built as five independent layers, each validated before the next was added.
This sequencing was not an accident — it reflects the order of risk: the hardest-to-fake property
(hardware attestation) had to work before the rest could be meaningful.

```
L1 — Attestation       "This hardware ran this code"
  ↓
L2 — Confidential Compute  "This data never left the enclave unencrypted"
  ↓
L3 — In-memory test harness  "Every path is exercisable without hardware"
  ↓
L4 — Docker network          "Multiple nodes work together end-to-end"
  ↓
L5 — Chain integration       "Scores and slashes land on the actual chain"
```

Each layer has its own test class (see §7). Failures at L1 mean the attestation is broken. Failures
at L4 mean Docker networking or libp2p is broken. A failure at L5 does not mean L1 is broken.
This separation matters when debugging production issues.

### What you inherit by forking

When you fork this template, you get all five layers working. You replace exactly three files:

```
subnet/node/protocol.py  ← what miners do each epoch + how validators call them
subnet/node/scoring.py   ← how validators score peers (returns 0.0–1.0)
subnet/node/config.py    ← your subnet's parameters
```

Everything else — DHT, libp2p mesh, TEE attestation, RA-TLS, chain integration, overwatch — is
template boilerplate that requires no modification for most subnets.

---

## 2. Node topology

A running TEE subnet consists of four node types. All four run the same binary (`subnet.cli.run_node`);
the role is determined by registered class on-chain and environment variables.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Hypertensor Chain                                  │
│   (SubnetModule pallet: peer registry, score submissions, slash extrinsics)  │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │  WebSocket RPC (CHAIN_ENDPOINT)
      ┌────────────┼────────────────────────────────────────┐
      │            │                                        │
 ┌────▼──────┐ ┌───▼────────────────────┐ ┌────────────────▼─────────────────┐
 │ Bootnode  │ │       Validator         │ │        Miner-N                    │
 │           │ │                         │ │                                   │
 │ libp2p    │ │ Validator loop:         │ │ Miner loop:                       │
 │ routing   │ │  - score peers          │ │  - do the work (your code)        │
 │ entry     │ │  - propose_attestation  │ │  - generate TEE quote             │
 │ point     │ │  - attest               │ │  - publish to DHT                 │
 │ only      │ │                         │ │  - respond to validator calls     │
 │           │ │ Overwatch loop:         │ │                                   │
 │           │ │  - audit miner outputs  │ │ TAMPER_RATE=1.0:                  │
 │           │ │  - commit+reveal slash  │ │  deliberate fault injection       │
 └───────────┘ └─────────────────────────┘ └───────────────────────────────────┘
      │              │                                │
      └──────────────┴────────────────────────────────┘
                 libp2p GossipSub mesh
     (topics: heartbeat · mock_work · tee_quotes · ratls_certs)
```

**Bootnode:** Provides a stable multiaddr that all other nodes dial on startup. Does not participate
in scoring, staking, or chain extrinsics. One per subnet is the minimum; more add routing redundancy.

**Validator:** The workhorse node. Runs three background loops in parallel:
1. Validator loop — scores peers, submits `propose_attestation()` or `attest()`
2. Overwatch loop — independently audits miner outputs, submits slash extrinsics on mismatch
3. Chain loop — periodic health checks, epoch tracking

**Miner:** Does the actual subnet task each epoch. Publishes results to the DHT, responds to
validator scoring calls over RA-TLS. The overwatch loop also runs inside each non-bootstrap node —
but only the node registered as `Overwatch` class on-chain will actually submit slash extrinsics
(guarded by `OVERWATCH_NODE_ID` env var).

**Overwatch node:** A dedicated node registered as the `Overwatch` class on-chain. Runs only the
overwatch loop — no miner work, no validator scoring. Signs slash extrinsics with its own keypair
(`OVERWATCH_PHRASE`), separate from the validator's signing key.

---

## 3. Epoch flow

One epoch is 120 seconds (20 blocks × 6 seconds/block). Within each epoch, four parallel timelines
run. Here is the full sequence:

```
Epoch N begins (block N * 20)
│
├─────────────────────────────────────────────────────────────────────────
│ MINER TIMELINE (immediate on epoch start)
│
│  1. generate_quote(peer_id, epoch=N)
│     → sha256(peer_id:N) → report_data (64 bytes)
│     → IOCTL /dev/tdx_guest (or mock HMAC) → TeeQuote{measurement, nonce=N}
│
│  2. DHT publish: nmap_put(TEE_QUOTE_TOPIC, "N:peer_id", quote_bytes)
│
│  3. generate RA-TLS cert: ephemeral X.509 with DCAP quote in extension
│     → ephemeral key pair → cert with extension OID containing the quote
│     → session_key = HKDF-SHA256(cert_pubkey, "peer_id:N")
│
│  4. DHT publish: nmap_put(RATLS_CERT_TOPIC, "N:peer_id", cert_pem)
│
│  5. do_work(epoch=N) — your miner logic runs here
│     → work result encrypted with session_key (WorkEnvelope AES-256-GCM)
│     → output signed with session_key (OutputEnvelope HMAC-SHA256)
│
│  6. DHT publish: nmap_put(mock_work, "N:peer_id", output_envelope_bytes)
│
├─────────────────────────────────────────────────────────────────────────
│ VALIDATOR TIMELINE (scores epoch N-1, 30s offset from epoch start)
│
│  1. Chain: get_min_class_subnet_nodes_formatted(subnet_id, epoch=N-1)
│     → registered peer list from chain
│
│  2. For each peer (parallel):
│
│     a. validator_call(peer_id, epoch=N-1)
│        → fetch OutputEnvelope: nmap_get(mock_work, "(N-1):peer_id")
│
│     b. Verify RA-TLS cert: DcapVerifier.verify(peer_id, epoch=N-1)
│        Step 1: fetch quote from DHT — missing → score=0.0
│        Step 2: debug_mode=True → score=0.0 (always rejected)
│        Step 3: nonce != N-1 → score=0.0 (replay protection)
│        Step 4: sha256(peer_id:N-1) != report_data → score=0.0 (Sybil block)
│        Step 5: cert chain: HMAC (mock) or x509 DCAP (real HW) → 0.0 if invalid
│        Step 6: measurement != EXPECTED_MEASUREMENT → 0.0 if set
│        Step 7: TCB policy → tee_score ∈ {0.0, 0.5, 1.0}
│
│     c. Verify OutputEnvelope signature (HMAC-SHA256 with session key)
│
│     d. Your scoring logic: score_peer(result) → correctness_score ∈ [0.0, 1.0]
│
│     e. final_score = tee_score × correctness_score
│
│  3. ChainScoreSubmitter.submit(scores)
│     → propose_attestation(subnet_id, [{subnet_node_id, int(score × 1e18)}])
│     (if elected) or attest() (if non-elected validator)
│
├─────────────────────────────────────────────────────────────────────────
│ OVERWATCH TIMELINE (audits epoch N-1, 35s offset)
│
│  1. For each peer:
│     MockOverwatchVerifier.verify(peer_id, epoch=N-1)
│     → fetch raw OutputEnvelope from DHT (no session key needed)
│     → re-check work independently of the validator's scoring
│     → returns OverwatchResult{ok, reason}
│
│  2. If reason == "parity_mismatch" AND OVERWATCH_NODE_ID is set:
│     ChainOverwatchReporter.slash(peer_id, epoch=N-1, details)
│     → salt = os.urandom(32)
│     → commit_hash = sha256(b"\x00" * 32 + salt)  [weight=0]
│     → commit_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, commit_hash}])
│     ← wait for overwatch epoch boundary
│     → reveal_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, weight=0, salt}])
│     ← chain: verifies hash(weight_bytes + salt) == stored commit → slashes miner
│
└─────────────────────────────────────────────────────────────────────────
  CHAIN FINALISATION (at epoch boundary)
  → compute proportional emissions from scores
  → distribute to nodes: reward_i = (score_i / Σ scores) × subnet_emission_budget
```

### What the overwatch epoch boundary means

The overwatch commit-reveal runs on a different cadence than the scoring epoch. The overwatch
epoch is `EPOCH_LENGTH × overwatch_multiplier` blocks long. The commit must land before the
overwatch epoch cutoff block; the reveal must land after it. The chain enforces this ordering —
early reveals or late commits are rejected.

---

## 4. Security layers

The architecture provides defence in depth. Each layer independently blocks a class of attack.
If one layer is bypassed, the others remain.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Hardware attestation (L1)                                          │
│                                                                             │
│ What it proves: "This node's code is unmodified; it runs in a genuine TEE" │
│ How: DcapVerifier 7-step pipeline; identity binding to (peer_id, epoch)    │
│ If bypassed: Miner can run arbitrary code and earn rewards as if attested   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 2: Encrypted channel (L2)                                             │
│                                                                             │
│ What it proves: "Work items and results were not readable by the operator"  │
│ How: RA-TLS — TLS cert IS the attestation; session key from cert public key │
│ If bypassed: Operator can read/modify work items in transit                 │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 3: Output integrity (L2)                                              │
│                                                                             │
│ What it proves: "The result was produced by this specific miner's enclave"  │
│ How: OutputEnvelope HMAC-SHA256 with session key derived from cert pubkey   │
│ If bypassed: Results can be forged or replayed from another peer            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 4: Independent audit (L4/L5)                                          │
│                                                                             │
│ What it proves: "A miner cannot bribe a single validator to accept fraud"   │
│ How: Overwatch runs independently; 66% attestation required; slash costs    │
│      real stake (3.125% per epoch)                                         │
│ If bypassed: Miner needs majority-stake collusion to evade slash            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Layer 5: Sealed storage (L2)                                                │
│                                                                             │
│ What it proves: "Private data cannot be read by a modified binary version"  │
│ How: AES-256-GCM keyed by sha256(measurement); different binary = new key  │
│ If bypassed: Operator must run the exact correct binary to access secrets   │
└─────────────────────────────────────────────────────────────────────────────┘
```

These layers are composable. A subnet that only needs L1 (attestation) can turn off L2 (RA-TLS)
by not using `WorkEnvelope` and `OutputEnvelope`. A subnet that needs privacy but not hardware
attestation can use `MOCK_TEE=true` for the TEE layer while keeping RA-TLS for channel encryption.

---

## 5. RA-TLS — the encrypted channel

RA-TLS (Remote Attestation TLS) embeds the DCAP attestation quote *inside the TLS certificate*.
The TLS handshake is the attestation — no separate quote exchange step is needed.

### Standard TLS vs RA-TLS

```
Standard TLS:                          RA-TLS:
                                        
Client ──── ClientHello ────► Server   Client ──── ClientHello ────► Server
Client ◄── ServerHello ────── Server   Client ◄── ServerHello ────── Server
       ◄── Certificate(X.509) ──────   Client ◄── Certificate(X.509 +
            │                                        DCAP quote in extension)
            └─ signed by CA                         └─ self-signed + enclave key
Client: verify CA chain               Client: verify DCAP quote
Client: session key from cert pubkey  Client: session key from cert pubkey
                                       (HKDF-SHA256(cert_pubkey, peer_id:epoch))
```

The RA-TLS cert is *self-signed* — there is no CA. The cert's public key is generated fresh for
each epoch inside the enclave, and the DCAP quote is embedded in a custom X.509 extension. The
validator verifies the quote during the TLS handshake, then derives the session key from the cert's
public key. The session key is used for:

- `WorkEnvelope`: AES-256-GCM encryption of work items sent to the miner
- `OutputEnvelope`: HMAC-SHA256 signature of results returned by the miner

This means a validator that successfully completes an RA-TLS handshake has simultaneously verified:
1. The miner is running in a genuine TEE
2. The channel is encrypted with a key that only that enclave's epoch-specific keypair can derive
3. The results are signed with that same key — they cannot be forged by a third party

See `subnet/tee/ratls/` for the implementation:
- `cert.py` — `RaTlsCertBundle`: X.509 cert generation with quote extension
- `server.py` — `RaTlsServer`: cert generation + trio server
- `client.py` — `RaTlsClient`: TLS connect + inline attestation verification at handshake
- `session.py` — `RaTlsSession`: HKDF key derivation + AES-GCM encrypt/decrypt + HMAC sign/verify

---

## 6. Sealed storage

Sealed storage binds encrypted data to the enclave's measurement. Only the exact binary version
that encrypted the data can decrypt it — not a newer version, not a patched version, not a
different subnet's binary.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Enclave binary v1.0 (measurement = 0xabc...)                                 │
│                                                                              │
│  sealing_key = sha256("0xabc...")                                            │
│  ciphertext = AES-256-GCM.encrypt(sealing_key, plaintext)                   │
│  → stored on disk                                                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Same binary v1.0 (measurement = 0xabc...)    ← can decrypt                  │
│  sealing_key = sha256("0xabc...")                                            │
│  plaintext = AES-256-GCM.decrypt(sealing_key, ciphertext)  ✓               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Modified binary v1.1 (measurement = 0xdef...)   ← cannot decrypt            │
│  sealing_key = sha256("0xdef...")                                            │
│  plaintext = AES-256-GCM.decrypt(sealing_key, ciphertext)  ✗ FAIL          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Primary use case in the template:** Persisting the overwatch slash salt between commit and reveal.
If the node crashes after committing but before revealing, the salt must survive the restart. Writing
the salt to `SealedStore` before the commit extrinsic ensures it survives a crash and is readable
only by the same binary version.

See `subnet/tee/sealed/store.py` for the implementation.

---

## 7. The testing pyramid

The template ships with a three-tier testing strategy, matching the five architectural layers:

```
                                ┌──────────────────────┐
                                │  Layer 3: Live chain  │
                                │  (continue-on-error)  │
                                │  smoke_test_chain.py  │
                                └──────────────────────┘
                        ┌───────────────────────────────────┐
                        │  Layer 2: Docker network          │
                        │  docker-compose.tee-dev.yml       │
                        │  multi-container epoch loop        │
                        │  live tamper detection             │
                        └───────────────────────────────────┘
     ┌──────────────────────────────────────────────────────────────┐
     │  Layer 1: In-memory (pytest tests/ -x -q)                    │
     │  260+ tests                                                    │
     │  sub-second per test, no hardware, no Docker, no network     │
     └──────────────────────────────────────────────────────────────┘
```

**Layer 1 (in-memory):** All tests run locally with `pytest tests/ -x -q`. No Docker, no chain,
no hardware. Uses `MockBackend` for TEE quotes and in-memory data structures. Tests cover:
attestation pipeline, RA-TLS handshake, sealed storage, overwatch commit-reveal, validator/miner
epoch loops, and chain extrinsic wrappers.

**Layer 2 (Docker):** `docker compose -f docker-compose.tee-dev.yml up --build`. Four containers
(bootnode, validator, miner-1, miner-2 + optional overwatch). Live GossipSub transport, multi-epoch
scoring, health endpoints. Set `TAMPER_RATE=1.0` on miner-1 to trigger live overwatch detection.

**Layer 3 (chain):** Requires testnet connection. `smoke_test_chain.py` checks peer registration,
score submission, and slash events against the live chain. Documented in `CHAIN.md`. In CI, this
step runs with `continue-on-error: true` — no testnet is available in CI runners.

**Test file map:**

| Test file | What it covers | Layer |
|---|---|---|
| `tests/tee/test_verifier.py` | 7-step DcapVerifier pipeline | L1 |
| `tests/tee/test_ratls.py` | RA-TLS cert generation, handshake, session | L1 |
| `tests/tee/test_sealed.py` | SealedStore encrypt/decrypt, measurement binding | L1 |
| `tests/test_mock_node.py` | MockNodeProtocol miner/validator epoch loops | L1 |
| `tests/test_overwatch_integration.py` | Overwatch commit-reveal, detect-slash pipeline | L1 |
| `tests/consensus/test_chain_submitter.py` | ChainScoreSubmitter unit tests | L1 |
| `tests/consensus/test_chain_overwatch_reporter.py` | ChainOverwatchReporter unit tests | L1 |

---

## 8. How to navigate the source

```
subnet/
├── tee/                     ← All TEE logic
│   ├── backends/
│   │   ├── mock.py          HMAC-based mock backend (MOCK_TEE=true, development only)
│   │   ├── tdx.py           Intel TDX DCAP quote generation
│   │   ├── sev_snp.py       AMD SEV-SNP attestation (dev/testing — see §10a in anti-cheat)
│   │   └── sev_snp_azure.py Azure CVM via vTPM (dev/testing — see §10a in anti-cheat)
│   ├── quote.py             TeeQuote schema + DHT key helpers
│   ├── publisher.py         TeePublisher — one-shot per epoch: generate → DHT
│   ├── verifier.py          DcapVerifier — 7-step pipeline → VerificationResult
│   ├── config.py            TeeConfig (MOCK_TEE, MIN_TEE_SCORE, EXPECTED_MEASUREMENT, etc.)
│   ├── ratls/
│   │   ├── cert.py          RaTlsCertBundle — X.509 with DCAP quote in extension
│   │   ├── server.py        RaTlsServer — cert gen + trio server
│   │   ├── client.py        RaTlsClient — TLS connect + inline quote verification
│   │   ├── session.py       RaTlsSession — HKDF + AES-GCM + HMAC
│   │   └── envelope.py      WorkEnvelope (encrypted input) + OutputEnvelope (signed output)
│   └── sealed/
│       └── store.py         SealedStore — AES-GCM keyed by sha256(measurement)
│
├── consensus/
│   ├── consensus.py         Consensus loop — get_scores(), propose/attest lifecycle
│   ├── chain_submitter.py         ChainScoreSubmitter — wraps propose_attestation
│   └── chain_overwatch_reporter.py  ChainOverwatchReporter — commit-reveal slash
│
├── node/                    ← YOUR CODE GOES HERE
│   ├── protocol.py          MockNodeProtocol — replace with your subnet's miner + validator logic
│   ├── scoring.py           MockNodeScoring — replace with your scoring function
│   └── config.py            NodeConfig — your subnet's parameters
│
├── server/
│   ├── server.py            Server — composition layer, wires all services together
│   ├── host.py              create_host() — libp2p host + POS secure transport setup
│   ├── loops.py             Epoch loops: tee_publish, miner, validator_scoring, overwatch
│   └── health.py            health_server() — HTTP liveness endpoint
│
├── hypertensor/
│   ├── chain_functions.py   Hypertensor class — all chain extrinsics and queries
│   └── config.py            BLOCK_SECS, EPOCH_LENGTH, SECONDS_PER_EPOCH constants
│
└── utils/
    └── dht.py               nmap_put / nmap_get — DHT key-value storage helpers
```

**Entry points:**
- `subnet/cli/run_node.py` — main process entrypoint; reads env vars, starts libp2p host + server
- `docker-compose.tee-dev.yml` — local dev (no chain, MOCK_TEE=true)
- `docker-compose.chain.yml` — testnet (chain-connected, MOCK_TEE=true by default)
- **Production:** Gramine/SGX only — see [`GRAMINE.md`](../GRAMINE.md). CVM-only deployments are vulnerable to runtime tampering (see [`anti-cheat §10a`](04-anti-cheat.md#10a-runtime-code-tampering-inside-a-cvm)).

**Where your code hooks in:**
- `subnet/node/protocol.py` — `miner_loop(epoch)` and `validator_call(peer_id, epoch)`
- `subnet/node/scoring.py` — `score_peer(result, epoch) → PeerScore`
- `subnet/node/config.py` — `NodeConfig` dataclass

**For full code-level detail** on each module, function signature, and call path, see
[`ARCHITECTURE.md`](../ARCHITECTURE.md).

---

*Previous: [What Is a TEE?](./02-what-is-tee.md)*  
*Next: [Anti-Cheat: Attack Taxonomy and Defences](./04-anti-cheat.md)*
