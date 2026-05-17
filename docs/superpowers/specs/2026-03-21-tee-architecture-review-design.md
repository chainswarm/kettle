# TEE Subnet Template — Architecture Review

> **Date:** 2026-03-21
> **Scope:** Security audit, production readiness assessment, architectural critique
> **Target:** Foundational subnet template supporting Intel TDX + AMD SEV-SNP, cloud + bare metal
> **Threat model:** All participants potentially adversarial — operators, miners, validators, network
> **Codebase state:** M001-M006 complete, 194 tests passing, mock TEE only

---

## Contents

1. [Executive summary](#1-executive-summary)
2. [P0 — Blocks production deployment](#2-p0--blocks-production-deployment)
3. [P1 — Seriously degrades security posture](#3-p1--seriously-degrades-security-posture)
4. [P2 — Architectural debt](#4-p2--architectural-debt)
5. [P3 — Operational gaps](#5-p3--operational-gaps)
6. [Design strengths to preserve](#6-design-strengths-to-preserve)
7. [Recommended implementation order](#7-recommended-implementation-order)

---

## 1. Executive summary

The TEE subnet template has a sound high-level design: 5 independent layers, pluggable
backends, clean fork-3-files developer experience, and a well-documented security model
covering 7 attack vectors. The identity binding scheme (`sha256(peer_id:epoch)` in
`report_data`) and the RA-TLS design (TLS cert IS the attestation) are cryptographically
solid foundations.

However, several critical security mechanisms are stubbed or incomplete. The most
important: **DCAP chain verification for both TDX and SEV-SNP returns `True` after a
format check**, and the **RA-TLS cert public key is not bound into the TEE quote's
report_data**. Together, these mean the template cannot currently prove that an output
was produced inside a specific enclave on real hardware — the core value proposition.

This review catalogues 21 findings across 4 priority tiers. Nothing here is unfixable.
The architecture is well-structured for these improvements.

**Finding counts by tier:**

| Tier | Count | Summary |
|------|-------|---------|
| P0 — Blocks production | 3 | DCAP stubs, cert binding, DHT auth |
| P1 — Degrades security | 6 | Hardware sealing, salt persistence, overwatch sig gap, temp RocksDB, consensus comparison, wire versioning |
| P2 — Architectural debt | 9 | TEE in base classes, scoring wiring, overwatch abstraction, server size, OID, key-on-disk, measurement rotation, unreachable TCB scoring, duplicate config init |
| P3 — Operational | 5 | Metrics, evidence, DHT GC, SQLite contention, division-by-zero guard |

---

## 2. P0 — Blocks production deployment

### F-01: DCAP chain verification stubs return True

**Files:** `subnet/tee/verifier.py:210-248`
**Severity:** Critical — completely undermines L1 attestation on real hardware

`_verify_dcap_chain_tdx()` checks that raw bytes start with `\x04\x00\x02\x00` (TDX v4
magic), then returns `True`. `_verify_dcap_chain_sev_snp()` checks that raw bytes are
>= 1184 bytes, then returns `True`. Both have `TODO(M002)` comments.

**Impact:** Any process that can produce bytes with the right prefix passes attestation.
The entire TEE security model depends on this step proving the quote was signed by real
hardware. Without it, an operator can fabricate a quote from scratch.

**What full DCAP verification requires:**

For TDX:
1. Extract PCK certificate from the quote's cert data
2. Verify PCK cert chain: PCK cert -> Intel Platform CA -> Intel Root CA
3. Check PCK cert against CRL (Certificate Revocation List)
4. Fetch and verify TCB Info collateral from PCCS/Intel PCS
5. Verify QE (Quoting Enclave) Identity
6. Verify the ECDSA-256 signature over the TD Report using the PCK public key
7. Extract and set `TcbStatus` from TCB Info comparison

For SEV-SNP:
1. Extract VCEK (Versioned Chip Endorsement Key) public key from attestation report
2. Fetch VCEK certificate from AMD KDS (Key Distribution Service)
3. Verify VCEK cert chain: VCEK -> AMD SEV CA -> AMD Root CA
4. Check certificate against CRL
5. Verify the ECDSA signature over the attestation report using VCEK
6. Validate the platform info and TCB version

**Recommendation:** This is the single highest priority item. Consider using
`intel-sgx-dcap-quote-verify-python` for TDX and `sev-snp-measure` / `sevsnplib` for
SEV-SNP, or implement from the raw specs (Intel DCAP API Spec, AMD SEV-SNP ABI 1.55).

---

### F-02: RA-TLS cert public key not bound in report_data

**Files:** `subnet/tee/ratls/cert.py:87`, `subnet/tee/quote.py:75-85`
**Severity:** Critical — breaks the cryptographic link between enclave and session key

Currently:
```
report_data = sha256(peer_id + ":" + epoch)   # 32 bytes, zero-padded to 64
```

The RA-TLS cert's ephemeral public key is **not** included in the report_data. The
cert.py docstring acknowledges this: *"The cert's public key hash is embedded in the
quote's report_data alongside peer_id:epoch (future M002 enhancement)"*.

**Attack scenario:**
1. Attacker runs a real TEE and generates a valid DCAP quote for (peer_id, epoch)
2. Attacker extracts the quote from the TEE
3. Attacker generates a **separate** ECDSA keypair **outside the enclave**
4. Attacker creates an RA-TLS cert using the external keypair + the valid quote
5. Validator verifies the quote (passes all 7 steps) and derives a session key from
   the external cert's public key
6. The attacker now holds the private key corresponding to the session key — they can
   sign arbitrary OutputEnvelopes outside the enclave

**Fix:** Include the cert public key hash in the report_data binding:
```
report_data = sha256(peer_id + ":" + epoch + ":" + sha256(cert_pubkey_der))
```

This requires generating the keypair first, computing report_data with the pubkey hash,
then requesting the TEE quote with that report_data. The validator then verifies that the
cert's pubkey hash matches what's in the quote's report_data.

**Ordering constraint:** The quote must be generated AFTER the cert keypair, which means
the flow in `RaTlsServer.generate_cert()` must change to: generate keypair -> compute
binding with pubkey -> request TEE quote -> build cert with quote.

---

### F-03: DHT writes have no authentication

**Files:** `subnet/utils/dht.py`, `subnet/utils/db/database.py`
**Severity:** High — enables DoS and potentially score manipulation

`nmap_set(topic, key, value)` has no authentication. Any node on the libp2p mesh can
write to any DHT key, including keys belonging to other peers (e.g.,
`"{epoch}:{other_peer_id}"`).

**Attack scenarios:**

1. **DoS via overwrite:** Attacker overwrites victim's valid TEE quote with garbage.
   Validator fetches garbage, deserialization fails, score=0.0. The victim did
   everything correctly but earns nothing.

2. **Quote injection:** With F-01 unfixed (stub DCAP verification), attacker writes a
   fabricated quote for the victim's key that passes the stub check. Validator reads the
   injected quote instead of the real one. If combined with F-02, attacker could
   potentially control the session key.

3. **Work record injection:** Attacker overwrites victim's OutputEnvelope. The signature
   check (HMAC with session key) will reject it, so the victim scores 0.0 — still a DoS.

**Recommendation:** DHT writes should be authenticated. Options:

- **Signed writes:** Each DHT value includes a signature from the writer's libp2p
  keypair. The DHT layer rejects writes where the signing peer_id doesn't match the
  key pattern (e.g., key `"5:12D3KooW..."` must be signed by `12D3KooW...`).

- **Namespace isolation:** Each peer can only write to keys containing its own peer_id.
  Enforced at the GossipSub validation layer.

- **Versioned writes with signature:** Include a monotonic counter + peer signature.
  DHT only accepts writes with a higher counter from the same signer.

---

### ~~F-04~~ (Withdrawn): Transport encryption is already present

**Note:** The original review incorrectly claimed the libp2p mesh uses plain TCP.
In fact, `server.py:168-175` configures `NoiseTransport` wrapped in `POSTransport`
when `enable_proof_of_stake=True` (the default). SECIO is also available as a
fallback transport (`server.py:177-183`).

When `enable_proof_of_stake=False`, `secure_transports_by_protocol` is set to `None`
and py-libp2p falls back to its built-in transport security, which also includes Noise.

**Residual concern (P3):** The `enable_proof_of_stake=False` fallback path should be
audited to confirm that py-libp2p's default transport security is adequate. This is
a minor operational concern, not a P0 blocker.

---

## 3. P1 — Seriously degrades security posture

### F-05: SealedStore uses mock key derivation on all code paths

**Files:** `subnet/tee/sealed/store.py:93-111`
**Severity:** High

`_derive_seal_key()` always uses `HMAC(mock_key, measurement)` as the IKM for HKDF,
regardless of whether the backend is mock, TDX, or SEV-SNP. The `mock_key` parameter
defaults to the well-known dev key.

On real TDX hardware, the sealing key should be derived from the TDX module's
`MRSIGNER`-based or `MRENCLAVE`-based key (via `TDG.MR.REPORT` + KDF). On SEV-SNP,
it should use the VCEK or a key derived from the platform's firmware measurement.

**Impact:** On real hardware, an operator who knows the mock key (which is the default
and public) can derive the same sealing key as the enclave and decrypt sealed data.
This violates the core sealed storage guarantee: "different binary = cannot decrypt."

**Recommendation:** Add a `derive_sealing_key(measurement)` method to `TeeBackendBase`.
Each backend implements it using its hardware's key derivation. `SealedStore` calls the
backend method instead of doing its own HMAC.

---

### F-06: Overwatch salt not persisted between commit and reveal

**Files:** `subnet/consensus/chain_overwatch_reporter.py`
**Severity:** High

`ChainOverwatchReporter.slash()` generates `salt = os.urandom(32)` in memory. The
commit extrinsic is submitted, then the reveal extrinsic is submitted in the same
function call. If the node crashes after commit but before reveal, the salt is lost.
The committed slash can never be revealed.

The architecture docs and anti-cheat docs both mention using `SealedStore` for salt
persistence, but it is not implemented.

**Impact:** Unreliable overwatch slashing. A determined attacker could crash the
overwatch node between commit and reveal to evade slashing.

**Recommendation:** `seal(f"overwatch_salt:{epoch}:{peer_id}", salt)` before calling
`commit_overwatch_subnet_weights()`. On reveal, `unseal()` the salt. On startup,
check for orphaned commits and attempt to reveal them.

---

### F-07: Overwatch does not verify OutputEnvelope signature

**Files:** `subnet/node/mock.py:247-306` (MockOverwatchVerifier)
**Severity:** Medium

`MockOverwatchVerifier.verify()` fetches the raw OutputEnvelope from DHT, parses the
output JSON, and performs three checks:
1. Re-checks the math (parity: `n % 2 == claimed`)
2. Verifies the TEE quote hash (`sha256(quote_raw) == tee_quote_hash` in output)
3. Optionally runs full `DcapVerifier.verify()` if a `config` is provided (lines 293-300)

However, it does NOT verify the OutputEnvelope's HMAC signature because it has no
session key (by design — overwatch has no RA-TLS session).

**Impact:** The overwatch catches incorrect results (parity mismatch) and missing/bad
TEE quotes (steps 2-3), but cannot verify that the output was signed by the attested
enclave's session key. An attacker who publishes a correct-math output with a valid
TEE quote hash but without running the actual code in the enclave would pass overwatch.

The existing optional TEE attestation check (step 3) partially mitigates this — it
confirms the peer has a valid quote — but doesn't prove the output was produced by
that enclave.

**Recommendation for subnets with high-value outputs:** Have the overwatch node also
fetch the RA-TLS cert from DHT, derive the session key, and verify the OutputEnvelope
signature. This requires access to the `RATLS_CERT_TOPIC`, which is already in the
shared DHT.

---

### F-08: RaTlsClient creates temporary RocksDB per verification

**Files:** `subnet/tee/ratls/client.py:173-201`
**Severity:** Medium — performance and resource leak risk

`_verify_quote_inline()` creates a temporary RocksDB instance, writes the quote, runs
`DcapVerifier.verify()`, then deletes the temp directory. This happens once per peer
per epoch during validator scoring.

**Impact:** For a subnet with 100 miners and 120-second epochs, this creates and
destroys 100 RocksDB instances per epoch. Each involves filesystem operations (create
directory, write WAL, sync, close, delete). This adds latency and creates disk I/O
pressure.

**Recommendation:** Refactor `DcapVerifier` to accept a `TeeQuote` directly (bypassing
DHT fetch) when called from the RA-TLS path. Add a `verify_quote(quote, peer_id, epoch)`
method that runs steps 2-7 without step 1 (DHT fetch). This eliminates the temporary
database entirely.

---

### F-09: Consensus data comparison has a logic bug

**Files:** `subnet/consensus/utils.py:13-28`
**Severity:** Medium

```python
validator_data_set = set(frozenset(validator_data))
my_data_set = set(frozenset(my_data))
```

`SubnetNodeConsensusData` is `@dataclass(frozen=True)` (confirmed in
`chain_data.py:1186`), so it IS hashable — no `TypeError` risk.

However, the set construction is logically wrong. `frozenset(validator_data)` creates
a single frozenset from the list items. `set(frozenset(...))` then creates a set
of the individual items (unpacking the frozenset). So the code is equivalent to
`set(validator_data)`, which works but is unnecessarily convoluted.

The deeper concern: `intersection / union` is a Jaccard similarity metric. It
compares by exact `(subnet_node_id, score)` equality. If two validators compute
scores that differ by even 1 (out of 1e18), the items won't match and the
attestation accuracy drops. This is fragile — any non-determinism in scoring
(timing of DHT reads, floating-point edge cases) causes attestation failure.

**Recommendation:** Use sorted-list comparison with an explicit tolerance, or
ensure the scoring path is fully deterministic (integer-only, no float
intermediates). The current set-based approach silently drops duplicate
subnet_node_ids, which may mask bugs.

---

### F-10: No wire protocol versioning in TeeQuote serialization

**Files:** `subnet/tee/quote.py:107-138`
**Severity:** Low-Medium

`TeeQuote.to_bytes()` serializes to JSON with no version field. `from_bytes()` uses
`.get(key, default)` for optional fields, providing some forward compatibility. But
there is no mechanism to:

- Reject quotes from an incompatible future version
- Handle schema migrations (e.g., renaming a field)
- Negotiate protocol version between nodes

**Recommendation:** Add a `"version": 1` field to the serialized JSON. `from_bytes()`
checks the version and rejects unknown versions. Future schema changes increment the
version.

---

## 4. P2 — Architectural debt

### F-11: TEE integration not lifted into base classes

**Files:** `subnet/node/protocol.py`, `subnet/node/mock.py:70-88`
**Severity:** Medium — every fork duplicates TEE wiring

`BaseNodeProtocol` has no TEE awareness. `MockNodeProtocol.register_handlers()` manually
instantiates `TeePublisher`, `DcapVerifier`, `RaTlsServer`, and `RaTlsClient`. Every
fork must repeat this boilerplate.

The template's promise is "fork 3 files and you're done." But actually, every fork must
also wire up TEE integration correctly, which is error-prone and not enforced by the
abstract interface.

**Recommendation:** Either:
- (A) Add TEE fields to `BaseNodeProtocol.__init__()` (publisher, verifier, config) and
  a `_publish_tee_quote(epoch)` helper method, or
- (B) Move TEE integration to the server layer entirely, so the protocol only sees
  `tee_score` as an input to scoring, not the TEE machinery.

Option (B) is cleaner: the server handles quote publish + verification, and passes
`tee_score` to `score_peer()`. The protocol never touches TEE directly.

---

### F-12: Consensus.get_scores() bypasses BaseNodeScoring

**Files:** `subnet/consensus/consensus.py:67-147`, `subnet/server/server.py:~290`
**Severity:** Medium — two parallel scoring paths that don't converge

`Consensus.get_scores()` does inline heartbeat + TEE scoring. It never calls
`BaseNodeScoring.score_peer()`. Meanwhile, `_validator_scoring_loop` in `server.py`
DOES call `scoring.score_peer()`. These are two separate scoring pipelines.

In the mock setup:
- `server.py` scoring loop calls `MockNodeScoring.score_peer()` which returns
  `tee_score * correctness`
- `Consensus.get_scores()` does `heartbeat_present * tee_score` with no correctness

The two paths produce different scores for the same peer. Which one actually submits
to chain depends on whether `enable_consensus` is True.

**Recommendation:** Unify the scoring path. `Consensus.get_scores()` should delegate
to the same `BaseNodeScoring.score_peer()` used by the server's scoring loop. The base
scoring should compose TEE score and correctness score.

---

### F-13: No BaseOverwatchVerifier abstract class

**Files:** `subnet/node/mock.py:247`
**Severity:** Low-Medium

`MockOverwatchVerifier` is a concrete class with no abstract base. Unlike
`BaseNodeProtocol` and `BaseNodeScoring`, there's no contract for what overwatch must
implement. Each fork must define their overwatch verifier ad hoc.

**Recommendation:** Add `BaseOverwatchVerifier` with `verify(peer_id, epoch) ->
OverwatchResult` as an abstract method. Move `OverwatchResult` to the base module.
This completes the trio of abstract interfaces (protocol, scoring, overwatch) that
define a subnet's behavior.

---

### F-14: server.py has too many responsibilities

**Files:** `subnet/server/server.py`
**Severity:** Low-Medium

The server handles: libp2p host management, DHT operations, GossipSub topic management,
health HTTP endpoint, miner epoch loop, validator scoring loop, overwatch epoch loop,
consensus coordination. This makes it difficult to test, modify, or understand any single
concern.

**Recommendation:** Extract into focused modules:
- `server/host.py` — libp2p host + transport setup
- `server/loops.py` — epoch loop orchestration (miner, validator, overwatch)
- `server/health.py` — HTTP health endpoint
- `server/server.py` — composition of the above

---

### F-15: Placeholder OID for TEE quote extension

**Files:** `subnet/tee/ratls/cert.py:64`
**Severity:** Low

`TEE_QUOTE_OID = "1.3.6.1.4.1.99999.1"` is in the enterprise OID arc but uses
`99999` which is not a registered PEN (Private Enterprise Number). In production,
another application could use the same OID, causing cert parsing confusion.

**Recommendation:** Register a PEN with IANA (free, takes ~1 week) or use the
Hypertensor org's existing PEN if one exists. Update the OID across all files.

---

### F-16: RaTlsServer writes private key to temporary file on disk

**Files:** `subnet/tee/ratls/server.py:108-124`
**Severity:** Medium in TEE context

`make_ssl_context()` writes `key_pem` to a temp file, loads it into `SSLContext`, then
deletes it. Even briefly, the ephemeral private key exists on the host filesystem.

In a Gramine SGX enclave, if the manifest allows writes to the temp directory, the
host OS could snapshot the file before deletion. This breaks the TEE confidentiality
guarantee for the session key.

**Recommendation:** In Gramine deployments, ensure the temp directory maps to an
encrypted filesystem (tmpfs inside the enclave, configured in the manifest). For
non-Gramine paths, consider using the `cryptography` library's memory-only TLS
context APIs to avoid writing keys to disk entirely.

---

### F-17: No graceful measurement rotation

**Files:** `subnet/tee/config.py:48`, `subnet/tee/verifier.py:152-162`
**Severity:** Low-Medium

When the subnet owner updates the binary and changes `EXPECTED_MEASUREMENT`, all miners
running the old binary immediately fail attestation (score=0.0). There is no transition
window.

For a large subnet, this means all miners must update simultaneously or lose emissions.
In practice, updates roll out over hours — during which honest miners with the old binary
are scored the same as attackers.

**Recommendation:** Support `EXPECTED_MEASUREMENT` as a comma-separated list of accepted
measurements. Validators accept any measurement in the list. The subnet owner publishes
the new measurement, waits for miners to update, then removes the old measurement.

---

### F-22: Unreachable code in `_score_from_tcb` — UNKNOWN TCB scored incorrectly

**Files:** `subnet/tee/verifier.py:254-283`
**Severity:** Medium — actual bug affecting UNKNOWN TCB status scoring

```python
if self._config.tcb_strict:
    return SCORE_FAIL
else:
    return SCORE_DEGRADED_TCB

# TcbStatus.UNKNOWN — be conservative
return SCORE_FAIL   # <-- UNREACHABLE
```

The `if/else` block always returns, making the final `return SCORE_FAIL` for
`TcbStatus.UNKNOWN` unreachable. This means `UNKNOWN` TCB with permissive policy
incorrectly scores `0.5` (degraded) instead of the intended `0.0` (fail). The comment
says "be conservative" but the code does the opposite.

**Impact:** On real hardware with unknown TCB status and permissive policy, a node that
should score 0.0 scores 0.5 instead. This is the wrong behavior — unknown TCB is worse
than degraded and should always be conservative.

**Fix:** Add an explicit check for `TcbStatus.UNKNOWN` before the degraded-status block:
```python
if status == TcbStatus.UNKNOWN:
    return SCORE_FAIL

# SWHardeningNeeded / ConfigNeeded / ConfigAndSWHardeningNeeded
if self._config.tcb_strict:
    return SCORE_FAIL
else:
    return SCORE_DEGRADED_TCB
```

---

### F-23: Duplicate config initialization in RaTlsClient

**Files:** `subnet/tee/ratls/client.py:92-96`
**Severity:** Low — code smell, no functional impact

```python
def __init__(self, config: TeeConfig | None = None) -> None:
    self._config = config or get_tee_config()
    # Create a lightweight verifier using an in-memory DB
    # The verifier's DHT path is bypassed — we inject the quote directly
    self._config = config or get_tee_config()
```

`self._config` is assigned twice with the same value. The second assignment is
redundant. This likely resulted from a copy-paste during refactoring.

**Fix:** Remove the duplicate line.

---

## 5. P3 — Operational gaps

### F-18: No Prometheus/metrics endpoint

**Severity:** Low

TEE verification results, scoring outcomes, overwatch detections, chain submission
success/failure — all are logged but not exposed as structured metrics. Operators
cannot build dashboards or set up alerting.

**Recommendation:** Add a `/metrics` endpoint (Prometheus text format) to the health
server. Key metrics: `tee_verifications_total{result=pass|fail,backend=mock|tdx|snp}`,
`scores_submitted_total`, `overwatch_detections_total`, `overwatch_slashes_total`.

---

### F-19: Evidence parameter ignored in ChainOverwatchReporter

**Files:** `subnet/consensus/chain_overwatch_reporter.py`
**Severity:** Low

`slash(peer_id, epoch, evidence=None)` accepts an `evidence` parameter but ignores it.
There is no on-chain evidence trail — the slash extrinsic only carries the commit hash
and weight.

**Recommendation:** Store evidence in DHT (or sealed storage) indexed by
`(epoch, peer_id)` so it can be retrieved for dispute resolution. Consider whether the
chain pallet should accept an evidence hash in the commit.

---

### F-20: No DHT garbage collection

**Severity:** Low

Old epoch quotes, RA-TLS certs, and work records accumulate in RocksDB indefinitely.
For a long-running subnet, this grows without bound.

**Recommendation:** Add a TTL-based cleanup that runs after each epoch. Delete entries
older than `max(3, OVERWATCH_EPOCH_MULTIPLIER + 1)` epochs. This preserves data needed
for scoring (epoch-1) and overwatch (epoch-1, possibly longer for commit-reveal).

---

### F-21: Mock chain SQLite shared via Docker volume

**Files:** `docker-compose.tee-dev.yml:189-194`
**Severity:** Low — dev only

The `mock-chain` volume is shared across all containers. `MockChainDB` (SQLite) handles
concurrent reads but concurrent writes from multiple containers can cause `SQLITE_BUSY`
errors.

**Recommendation:** Use WAL mode (`PRAGMA journal_mode=WAL`) in MockChainDB if not
already set. For dev, this is sufficient. For multi-writer scenarios, consider switching
to a proper shared database (e.g., a sidecar PostgreSQL).

---

### F-24: Division by zero in get_attestation_ratio

**Files:** `subnet/consensus/utils.py:31-32`
**Severity:** Low

```python
def get_attestation_ratio(consensus_data: ConsensusData):
    return len(consensus_data.attests) / len(consensus_data.subnet_nodes)
```

If `consensus_data.subnet_nodes` is empty, this raises `ZeroDivisionError`. This could
happen during subnet bootstrapping when no nodes are registered yet.

**Fix:** Return `0.0` if `subnet_nodes` is empty.

---

## 6. Design strengths to preserve

These are structural decisions that are correct and should NOT be changed during
remediation:

1. **5-layer architecture with independent validation** — Each layer has its own tests.
   Failures at L1 (attestation) are diagnosed independently of L4 (Docker networking).
   This is the right decomposition.

2. **Pluggable backends behind TeeBackendBase** — Mock, TDX, and SEV-SNP share one
   interface. Adding a new platform (e.g., ARM CCA) requires one new file. Keep this.

3. **"Fork 3 files" developer experience** — `protocol.py`, `scoring.py`, `config.py`
   is the right surface area for subnet customization. Remediation should reduce this
   surface, not expand it (see F-11).

4. **Identity binding: sha256(peer_id:epoch) in report_data** — Cryptographically sound.
   Blocks Sybil and replay. The fix for F-02 (adding cert pubkey) extends this scheme,
   not replaces it.

5. **RA-TLS: TLS handshake IS the attestation** — Eliminates a class of protocol bugs
   (quote exchange ordering, timing, etc.). This is the right design. Preserve it.

6. **MockBackend scores 0.5, not 1.0** — Clear operational distinction between mock and
   real hardware. Validators can set `MIN_TEE_SCORE=1.0` to require real hardware.
   This is a good production knob.

7. **TAMPER_RATE fault injection** — Allows end-to-end testing of the detection and
   slashing pipeline. Essential for CI and pre-deployment validation.

8. **Epoch-scoped ephemeral keys** — RA-TLS cert + session key rotate every epoch
   automatically. No manual key management. This is correct.

9. **Comprehensive test pyramid** — In-memory (260+ tests) -> Docker network -> chain
   smoke tests. Three tiers with clear scope. Add to it, don't restructure it.

10. **Detailed documentation** — 6 docs covering architecture, TEE primer, anti-cheat,
    Bittensor comparison, business case. Rare for a template project. Keep and update.

---

## 7. Recommended implementation order

### Phase 1: Security foundations (P0)

These must be complete before any production deployment.

| Order | Finding | Effort | Dependency |
|-------|---------|--------|------------|
| 1.1 | F-01: Complete DCAP verification (TDX) | Large | None |
| 1.2 | F-01: Complete DCAP verification (SEV-SNP) | Large | None |
| 1.3 | F-02: Bind cert pubkey in report_data | Medium | Changes quote schema + all backends |
| 1.4 | F-03: DHT write authentication | Medium | Requires libp2p keypair integration |

**Milestone gate:** After Phase 1, the template can prove: "this output was produced by
this specific binary, inside this specific enclave, for this specific peer and epoch,
and the DHT records are authenticated."

### Phase 2: Security hardening (P1)

These close remaining gaps that a sophisticated attacker could exploit.

| Order | Finding | Effort | Dependency |
|-------|---------|--------|------------|
| 2.1 | F-05: Hardware sealing key derivation | Medium | Requires TDX/SEV-SNP hardware testing |
| 2.2 | F-06: Persist overwatch salt to SealedStore | Small | F-05 (or use mock sealed store) |
| 2.3 | F-07: Overwatch RA-TLS signature verification | Small | None |
| 2.4 | F-08: Refactor DcapVerifier to accept inline quotes | Small | None |
| 2.5 | F-10: Add wire protocol version to TeeQuote | Small | None |
| 2.6 | F-09: Fix consensus data comparison semantics | Small | None |

### Phase 3: Architecture improvements (P2)

These improve the template's quality as a foundation that others fork.

| Order | Finding | Effort | Dependency |
|-------|---------|--------|------------|
| 3.1 | F-11: Lift TEE integration to server layer | Medium | Affects all forks |
| 3.2 | F-12: Unify scoring paths | Medium | F-11 |
| 3.3 | F-13: Add BaseOverwatchVerifier | Small | None |
| 3.4 | F-14: Extract server.py responsibilities | Medium | None |
| 3.5 | F-16: In-memory key loading for RA-TLS | Small | None |
| 3.6 | F-17: Multi-measurement support | Small | None |
| 3.7 | F-15: Register proper OID | Small | External process (IANA) |
| 3.8 | F-22: Fix unreachable TCB scoring code | Small | None (bug fix) |
| 3.9 | F-23: Remove duplicate config init in RaTlsClient | Trivial | None |

### Phase 4: Operational readiness (P3)

These make the template production-grade for operators.

| Order | Finding | Effort | Dependency |
|-------|---------|--------|------------|
| 4.1 | F-18: Prometheus metrics endpoint | Small | None |
| 4.2 | F-20: DHT garbage collection | Small | None |
| 4.3 | F-19: Evidence storage for slashes | Small | None |
| 4.4 | F-21: MockChainDB WAL mode | Trivial | None |
| 4.5 | F-24: Guard against division by zero in get_attestation_ratio | Trivial | None |

---

## Appendix: Files referenced

| File | Findings |
|------|----------|
| `subnet/tee/verifier.py` | F-01, F-02, F-22 |
| `subnet/tee/quote.py` | F-02, F-10 |
| `subnet/tee/ratls/cert.py` | F-02, F-15 |
| `subnet/tee/ratls/client.py` | F-08, F-23 |
| `subnet/tee/ratls/server.py` | F-16 |
| `subnet/tee/ratls/session.py` | — (sound design) |
| `subnet/tee/ratls/envelope.py` | — (sound design) |
| `subnet/tee/sealed/store.py` | F-05 |
| `subnet/tee/backends/base.py` | F-05 |
| `subnet/tee/backends/mock.py` | — (correct for its purpose) |
| `subnet/tee/backends/tdx.py` | F-01 |
| `subnet/tee/backends/sev_snp.py` | F-01 |
| `subnet/tee/config.py` | F-17 |
| `subnet/node/protocol.py` | F-11 |
| `subnet/node/scoring.py` | F-12 |
| `subnet/node/mock.py` | F-07, F-13 |
| `subnet/consensus/consensus.py` | F-12 |
| `subnet/consensus/utils.py` | F-09, F-24 |
| `subnet/consensus/chain_submitter.py` | — |
| `subnet/consensus/chain_overwatch_reporter.py` | F-06, F-19 |
| `subnet/server/server.py` | F-14 (F-04 withdrawn — Noise already enabled) |
| `subnet/utils/dht.py` | F-03 |
| `subnet/utils/db/database.py` | F-03 |
| `docker-compose.tee-dev.yml` | F-21 |
