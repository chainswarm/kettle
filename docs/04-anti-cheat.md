# Anti-Cheat: Attack Taxonomy and Defences

> **Audience:** Subnet owners and developers who want to understand exactly which attacks the TEE
> subnet prevents, how each defence is implemented, and what the economic stakes are.  
> **After reading this:** You will be able to explain every attack vector to a security reviewer,
> cite the exact source file that enforces each defence, and articulate the economic consequence
> of each undefended attack.

---

## Contents

1. [The attack surface](#1-the-attack-surface)
2. [Attack taxonomy](#2-attack-taxonomy)
3. [Attack 1: Identity theft (Sybil attack)](#3-attack-1-identity-theft)
4. [Attack 2: Quote replay](#4-attack-2-quote-replay)
5. [Attack 3: Debug mode bypass](#5-attack-3-debug-mode-bypass)
6. [Attack 4: Measurement swap (wrong binary)](#6-attack-4-measurement-swap)
7. [Attack 5: Output forgery](#7-attack-5-output-forgery)
8. [Attack 6: Validator collusion](#8-attack-6-validator-collusion)
9. [Attack 7: Overwatch evasion](#9-attack-7-overwatch-evasion)
10. [Defence summary table](#10-defence-summary-table)
11. [What TEE does not protect against](#11-what-tee-does-not-protect-against)
12. [Economic summary](#12-economic-summary)

---

## 1. The attack surface

In any compute subnet without TEE, the validator's only tool for detecting fraud is to re-run
the miner's work itself. This creates a fundamental asymmetry: re-running is expensive (same
cost as doing the work), sampling is sparse (a miner can cheat on unsampled epochs), and there
is no way to distinguish a miner running the correct code from a miner running a cheaper imposter.

The TEE subnet's defence strategy is to eliminate the need for re-running by making cheating
*cryptographically impossible* rather than *statistically detectable*. Each attack below has a
cryptographic or economic defence that does not depend on the validator re-running the work.

---

## 2. Attack taxonomy

| # | Attack | Without TEE | With TEE subnet |
|---|--------|-------------|----------------|
| 1 | Identity theft | Miner A submits results under peer ID of Miner B | Blocked — quote binds to `sha256(peer_id:epoch)` |
| 2 | Quote replay | Miner reuses last epoch's valid quote | Blocked — nonce must match current epoch |
| 3 | Debug mode | Miner runs code in debug enclave (operator can see/modify memory) | Blocked — debug bit → always score=0.0 |
| 4 | Measurement swap | Miner runs different binary than published | Blocked — measurement mismatch → score=0.0 |
| 5 | Output forgery | Miner fabricates results without doing the work | Blocked — RA-TLS session key proves output came from the attested enclave |
| 6 | Validator collusion | Miner bribes validator to accept fraudulent scores | Reduced — requires 66% of stake-weighted validators; collusion is slashable |
| 7 | Overwatch evasion | Miner submits wrong results but evades overwatch detection | Partially blocked — overwatch audits independently; slash requires OVERWATCH_NODE_ID |

---

## 3. Attack 1: Identity theft (Sybil attack)

### The attack

Miner A has real TEE hardware and generates a valid DCAP quote. Miner B has no TEE hardware.
Miner B steals Miner A's quote and submits it to claim Miner A's score for the epoch. Or: a
single operator runs two nodes, submitting the same hardware proof for both.

### Why it matters without TEE

Without identity binding, a single valid TEE quote could be reused across unlimited nodes. One
operator with one TEE machine could register 100 miners and claim 100× the emissions.

### The defence

Before generating the quote, the miner computes a binding value that includes both its peer ID
and the current epoch number:

```python
# subnet/tee/quote.py — TeeQuote.make_report_data()
report_data = sha256(f"{peer_id}:{epoch}".encode()).digest()  # 32 bytes
report_data = report_data + b"\x00" * 32                      # zero-padded to 64 bytes
```

This 64-byte value is written into the hardware's `report_data` / `user_data` field before the
CPU generates the quote. The CPU signs this value into the attestation — it cannot be changed
post-hoc.

The validator checks identity binding in step 4 of the DcapVerifier pipeline:

```python
# subnet/tee/verifier.py — DcapVerifier.verify()
if not quote.verify_identity(peer_id, epoch):
    return VerificationResult.fail("identity_binding_failed")
```

```python
# subnet/tee/quote.py — TeeQuote.verify_identity()
expected = sha256(f"{peer_id}:{epoch}".encode()).hexdigest()
expected_padded = expected.ljust(128, "0")  # hex of 64 zero-padded bytes
return self.report_data == expected_padded
```

**What this blocks:**
- Miner B cannot submit Miner A's quote: `report_data` binds to Miner A's `peer_id`, not B's
- A single operator cannot reuse one quote for multiple miners: each peer ID produces a different `report_data`

**Evidence:** `subnet/tee/quote.py` lines `make_report_data()` and `verify_identity()` +
`subnet/tee/verifier.py` step 4

---

## 4. Attack 2: Quote replay

### The attack

A miner generates a valid DCAP quote in epoch 5. In epoch 6, the miner doesn't run the enclave
(saves compute cost) and instead submits the epoch-5 quote again, hoping the validator accepts it.

### Why it matters without TEE

Without freshness checking, one valid quote could serve forever. Miners could run the real code
once, generate a quote, then run a cheaper imposter for all subsequent epochs.

### The defence

The quote's `nonce` field is set to the current epoch number when the quote is generated:

```python
# subnet/tee/backends/mock.py (and similarly in tdx.py, sev_snp.py)
return TeeQuote(
    ...
    nonce=epoch,   # bound to the epoch at generation time
    ...
)
```

The validator checks freshness in step 3 of the pipeline:

```python
# subnet/tee/verifier.py — DcapVerifier.verify()
if quote.nonce != epoch:
    logger.warning(
        "[DcapVerifier] REJECT %s — nonce mismatch (got %d expected %d)",
        tag, quote.nonce, epoch,
    )
    return VerificationResult.fail(f"nonce_mismatch:got={quote.nonce},expected={epoch}", quote)
```

Combined with identity binding (attack 1), a quote for `(peer_id=A, epoch=5)` will fail both
the nonce check and the identity check when submitted for `(peer_id=A, epoch=6)`.

**What this blocks:**
- Replaying last epoch's quote: `quote.nonce != current_epoch` → rejected
- Replaying another node's quote: identity binding fails first

**Evidence:** `subnet/tee/verifier.py` step 3 + `subnet/tee/backends/tdx.py`
`generate_quote(peer_id, epoch)` — `nonce=epoch` is set at generation time

---

## 5. Attack 3: Debug mode bypass

### The attack

Debug mode is a hardware feature that allows the host OS to inspect and modify the enclave's
memory. An operator running in debug mode can:
- Read any secret inside the enclave (model weights, private keys, sealed data)
- Observe every operation the enclave performs
- Potentially modify enclave state mid-execution

The attack: an operator deliberately runs in debug mode, enabling full memory inspection, then
submits the resulting quote hoping the validator doesn't check the debug bit.

### Why it matters without TEE

Without a debug mode check, the TEE guarantee is vacuous — an operator can run in debug mode
and read all "confidential" data. The attestation looks valid from the certificate chain, but
the enclave's isolation has been explicitly disabled.

### The defence

Debug mode check is step 2 in the DcapVerifier pipeline — **before** any other check:

```python
# subnet/tee/verifier.py — DcapVerifier.verify()
if quote.debug_mode:
    logger.warning("[DcapVerifier] REJECT %s — debug_mode=True", tag)
    return VerificationResult.fail("debug_mode", quote)
```

The `debug_mode` flag is extracted from the hardware-signed attestation:

```python
# subnet/tee/backends/tdx.py — TdxBackend._is_debug_mode()
# TD_ATTRIBUTES is at offset 48+272 (8 bytes); bit 0 is the debug flag
td_attr_offset = 48 + 272
td_attributes = int.from_bytes(raw_quote[td_attr_offset: td_attr_offset + 8], "little")
return bool(td_attributes & 0x1)
```

```python
# subnet/tee/backends/sev_snp.py — SevSnpBackend._is_debug_mode()
# POLICY field at offset 0x08; bit 19 = debug_swap
policy = int.from_bytes(raw_report[0x08: 0x08 + 8], "little")
return bool(policy & (1 << 19))
```

This check cannot be bypassed: the debug bit is inside the hardware-signed portion of the quote.
An operator cannot generate a debug-mode quote and forge the bit to appear as non-debug — the
signature would not verify.

**What this blocks:**
- Running in debug mode to spy on the enclave: score=0.0, no emissions
- Generating a debug-mode quote and claiming it is production: signature verification catches it

**Evidence:** `subnet/tee/verifier.py` step 2 + `subnet/tee/backends/tdx.py`
`_is_debug_mode()` + `subnet/tee/backends/sev_snp.py` `_is_debug_mode()`

---

## 6. Attack 4: Measurement swap (wrong binary)

### The attack

The subnet owner publishes a reference binary with measurement hash `0xabc...`. A miner wants
to run a cheaper, faster imposter binary (lower precision model, no actual computation, random
output generator) and claim the same score as honest miners.

The imposter binary has a different measurement hash — `0xdef...` — because any modification to
the binary changes the SHA-384 hash of the initial memory image.

### Why it matters without TEE

Without measurement checking, there is no way to verify that a miner is running the correct code.
A miner can claim to run GPT-4 and actually run a random number generator. The outputs might
pass casual sampling (especially if the miner copies other miners' outputs).

### The defence

Step 6 of the DcapVerifier pipeline checks the measurement against `EXPECTED_MEASUREMENT`:

```python
# subnet/tee/verifier.py — DcapVerifier.verify()
if self._config.expected_measurement:
    if not self._check_measurement(quote):
        return VerificationResult.fail(
            f"measurement_mismatch:got={quote.measurement[:16]},expected={self._config.expected_measurement[:16]}",
            quote,
        )
```

```python
def _check_measurement(self, quote: TeeQuote) -> bool:
    return quote.measurement.lower() == self._config.expected_measurement.lower()
```

The measurement is extracted from the hardware-signed quote:

```python
# subnet/tee/backends/tdx.py — TdxBackend._extract_measurement()
# MRTD is at TD Report offset 512, 48 bytes (SHA-384)
mrtd_offset = 48 + 512
mrtd = raw_quote[mrtd_offset: mrtd_offset + 48]
return mrtd.hex()
```

```python
# subnet/tee/backends/sev_snp.py — SevSnpBackend._extract_measurement()
# MEASUREMENT at report offset 0x90, 48 bytes (SHA-384)
meas = raw_report[0x90: 0x90 + 48]
return meas.hex()
```

**Configuration:** `EXPECTED_MEASUREMENT` env var. If unset, measurement is not checked — useful
during development when the binary changes frequently. For production subnets with locked releases,
always set `EXPECTED_MEASUREMENT`.

**What this blocks:**
- Running a different binary version: different measurement → score=0.0
- Running a patched binary: any change to the code or data in the initial memory image → different measurement
- "Model stuffing" attacks (running lighter models while claiming to run expensive ones): lighter model → different measurement

**Evidence:** `subnet/tee/verifier.py` step 6 + `subnet/tee/backends/tdx.py`
`_extract_measurement()` + `subnet/tee/config.py` `TeeConfig.expected_measurement`

---

## 7. Attack 5: Output forgery

### The attack

A miner receives a work item from a validator. Instead of running the computation, the miner
fabricates a plausible-looking output and submits it. Or: the miner copies another miner's output
from the DHT and resubmits it under its own peer ID.

Without TEE: the validator has no way to prove which process produced the output.

With TEE: the output is signed by a session key that is derived from the miner's epoch-specific
RA-TLS certificate. The certificate's keypair is generated inside the enclave at epoch start —
only the enclave code can produce the private key.

### The defence

The RA-TLS session key is derived from the certificate's public key:

```python
# subnet/tee/ratls/session.py — RaTlsSession
def __init__(self, cert_pubkey_der: bytes, peer_id: str, epoch: int):
    # Session key from HKDF-SHA256 of cert public key + peer binding
    info = f"{peer_id}:{epoch}".encode()
    self.key = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=cert_pubkey_der,
        info=info,
    ).derive(b"session")
```

The `OutputEnvelope` is HMAC-SHA256 signed with this session key:

```python
# subnet/tee/ratls/envelope.py — OutputEnvelope
def sign(self, session: RaTlsSession) -> "OutputEnvelope":
    sig = hmac.new(session.key, self.payload, sha256).digest()
    return dataclasses.replace(self, signature=sig)
```

The validator verifies the signature during scoring:

```python
# The validator fetches the cert from DHT and constructs the session key
# If the signature doesn't verify → the output was not produced by this enclave
```

Since the RA-TLS cert's private key is generated inside the enclave and never leaves it, only
the enclave running in the attested TEE can produce a valid `OutputEnvelope` signature.

**What this blocks:**
- Output fabrication: the miner cannot sign a fabricated output without running inside the attested enclave
- Output copying: peer_id and epoch are in the session key derivation — Miner B cannot reuse Miner A's signed output for its own epoch

**Evidence:** `subnet/tee/ratls/session.py` `RaTlsSession.__init__()` +
`subnet/tee/ratls/envelope.py` `OutputEnvelope.sign()` / `verify()`

---

## 8. Attack 6: Validator collusion

### The attack

A miner bribes a validator to accept fraudulent scores. The validator calls `propose_attestation()`
with inflated scores for the miner and the other validators do not detect it.

### Why it matters without TEE

On Bittensor, each validator submits an independent weight vector. A single colluding validator
can systematically inflate a miner's score in proportion to its stake. No economic penalty.

### The defence

Hypertensor's consensus requires 66% of stake-weighted validators to independently attest to the
same scores. A miner needs to compromise the majority of stake to benefit from collusion.

Additionally, collusion carries an economic cost:

1. **Non-elected validator refusing to attest:** If an honest validator computes different scores,
   it will not call `attest()`. If the attesting validators fall below 66%, the elected validator
   is slashed (3.125% of stake, capped at 1 TENSOR).

2. **Elected validator proposing fraudulent scores:** Other validators independently compute scores
   and check whether the proposal matches. If not, they refuse to attest. Elected validator gets
   slashed if < 66% attest.

3. **Overwatch cross-check:** The overwatch loop independently re-verifies miner outputs. If it
   detects a parity mismatch that the validator missed (or ignored), it submits a slash extrinsic
   directly against the miner — bypassing the validator's scoring entirely.

```python
# subnet/consensus/chain_overwatch_reporter.py — ChainOverwatchReporter.slash()
# Overwatch can slash regardless of what the validator scored
```

**Residual risk:** True majority-stake collusion (>66%) cannot be blocked cryptographically —
it would require trusting a minority stake to override a majority. This is a fundamental property
of Byzantine consensus. The economic mitigation is that collusion requires real stake at risk —
if overwatch or external observers detect the collusion pattern, the colluding validators face
reputation damage and potential governance actions.

**Evidence:** Consensus model: `HYPERTENSOR_ANALYSIS.md` §1 + `subnet/hypertensor/chain_functions.py`
`propose_attestation()` / `attest()` + `subnet/consensus/chain_overwatch_reporter.py`

---

## 9. Attack 7: Overwatch evasion

### The attack

A miner knows it will be audited by the overwatch loop. It wants to submit fraudulent results
to the validator while passing the overwatch check. Or: the miner wants to detect when it is
being audited and behave differently.

### The defence

The overwatch audit runs independently of the validator scoring loop:

```python
# subnet/server/loops.py — overwatch_epoch_loop
# Overwatch runs 35 seconds after the validator loop starts
# It fetches raw OutputEnvelopes from DHT directly — no dependency on validator path
result = await overwatch_verifier.verify(peer_id, epoch - 1)
```

The overwatch verifier (`MockOverwatchVerifier`) fetches the raw `OutputEnvelope` from the DHT
and re-checks the work independently. The miner cannot tell whether a given check request comes
from the validator loop or the overwatch loop — both read from the same DHT keys.

**Limitations:**
- Overwatch slash only fires when `OVERWATCH_NODE_ID` is set. If the overwatch node is not
  registered on-chain, fraudulent results are *detected* and logged but not slashed on-chain.
- The current `MockOverwatchVerifier` implements a simple parity check. In production, the
  overwatch verifier should implement the same verification logic as the validator — possibly
  with a time delay to prevent timing-based detection.
- Salt persistence: if the overwatch node crashes between commit and reveal, the salt is lost
  and the slash cannot be completed. Production fix: persist salt to `SealedStore` before commit.

**Evidence:** `subnet/server/loops.py` `overwatch_epoch_loop` + `subnet/consensus/chain_overwatch_reporter.py`
+ `subnet/tee/sealed/store.py` (for salt persistence fix)

---

## 10. Defence summary table

| Attack | Blocked by | Source file | How it works |
|--------|-----------|-------------|--------------|
| Identity theft (Sybil) | Identity binding | `subnet/tee/quote.py` `make_report_data()` | `report_data = sha256(peer_id:epoch)` in hardware-signed quote |
| Quote replay | Nonce check | `subnet/tee/verifier.py` step 3 | `quote.nonce != epoch → 0.0` |
| Debug mode | Debug bit check | `subnet/tee/verifier.py` step 2 | `quote.debug_mode → always 0.0` |
| Measurement swap | Measurement check | `subnet/tee/verifier.py` step 6 | `quote.measurement != EXPECTED_MEASUREMENT → 0.0` |
| Output forgery | RA-TLS session key | `subnet/tee/ratls/session.py` | Session key from enclave cert pubkey; only enclave can sign |
| Validator collusion | 66% attestation + slash | `subnet/hypertensor/chain_functions.py` | Requires majority stake; elected validator slashed if < 66% attest |
| Overwatch evasion | Independent audit + DHT | `subnet/server/loops.py` `overwatch_epoch_loop` | Overwatch reads same DHT keys as validator; miner cannot detect which caller |
| Runtime code tampering (CVM) | **PARTIAL** — see section 10a | dm-verity, IMA, Gramine/SGX | CVM launch measurement is frozen at boot; runtime changes undetected without additional layers |
| Shared external resources | **Subnet-level** — see section 10b | Subnet scoring logic | Challenge uniqueness, timing fingerprinting, output correlation analysis |
| GPU sharing (1 GPU → N nodes) | **Subnet-level** — see section 10c | GPU attestation + scoring | H100 device identity (unforgeable), NVML audit, GPU fingerprinting |

---

## 10a. Runtime code tampering inside a CVM

### The attack

A malicious operator boots the genuine container image inside an Azure SEV-SNP CVM (correct
measurement), then SSHs into the VM and modifies the running code:

```
1. Boot genuine image → MEASUREMENT = sha384(official_binary) ✓
2. ssh tee@<cvm-ip>
3. docker exec -it miner bash
4. vi /app/subnet/node/mock.py   ← inject MitM / swap model / skip work
5. Next epoch: modified code generates a new TEE quote via /dev/sev-guest
6. Quote still contains the ORIGINAL boot-time MEASUREMENT
7. Validator checks measurement → matches EXPECTED_MEASUREMENT → score=1.0
   → ATTACK SUCCEEDS
```

### Why this works on SEV-SNP CVMs

The `MEASUREMENT` field in the SEV-SNP attestation report is the **launch digest** — a SHA-384
hash computed by the AMD Secure Processor (PSP) during the `SNP_LAUNCH_UPDATE` / `SNP_LAUNCH_FINISH`
sequence at VM boot. It covers the initial OVMF firmware pages and vCPU register state.
**It does not cover the guest OS, kernel, userspace, Docker images, or anything loaded after
firmware handoff.**

After boot, the MEASUREMENT is immutable. Any process inside the VM can call `SNP_GET_REPORT`
via `/dev/sev-guest` and receive a fully valid, PSP-signed attestation report with the original
"clean" measurement — regardless of what code is actually running.

SEV-SNP's threat model: it protects the guest from the **hypervisor/cloud provider** (Azure
cannot read guest memory). It does **not** protect the guest from the **operator** who has root
inside the VM.

### Why Gramine/SGX is stronger

With Intel SGX (via Gramine), the CPU hardware-seals the enclave memory:

- **MRENCLAVE** is computed from the entire application binary at load time
- The host OS cannot inspect or modify enclave memory pages — any attempt crashes the enclave
- `docker exec` / `ptrace` / `/proc/pid/mem` are all blocked by hardware
- The operator, even with root, is locked out of the enclave's address space

This is why **SGX/Gramine is the recommended path for production subnets** where the threat
model includes malicious operators.

### Defence layers for CVM deployments

If SGX is not available (e.g., GPU workloads on AMD-only hardware), CVM deployments can add
runtime integrity layers:

| Layer | What it does | Limitation |
|-------|-------------|------------|
| **dm-verity** | Merkle hash tree over read-only root partition; kernel verifies every block read against the tree. Root hash extended into vTPM PCR at boot. | Only covers read-only filesystems. Writable partitions (`/var`, `/tmp`, Docker overlay) are not protected. |
| **IMA (Integrity Measurement Architecture)** | Linux kernel hashes executables, shared libraries, and kernel modules before loading. Hashes extend into TPM PCR 10. In `appraise+enforce` mode, blocks execution of modified binaries. | Only hooks `execve` / `mmap` / module load. Interpreted scripts (Python), config files, and dynamically loaded data are invisible to IMA unless custom policy is set. Root can disable IMA if not locked down. |
| **Confidential Containers (Kata + CoCo)** | Container image layers mounted as dm-verity-protected read-only block devices. OPA/Rego policy on every API call — can **deny `docker exec` entirely**. Policy hash stored in attestation report's `HOSTDATA` field. | Requires Kata runtime infrastructure. Not available on vanilla Docker. |
| **Kernel lockdown mode** | Prevents root from modifying kernel memory, loading unsigned modules, or accessing `/dev/mem`. | Does not prevent modifying userspace files on writable mounts. |

**Recommendation:** For CVM subnets without SGX, the minimum defence is dm-verity on the root
filesystem + IMA in `appraise+enforce` mode + blocking `exec` into containers via runtime policy.
For maximum security, use Gramine/SGX.

---

## 10b. Shared external resources (e.g., ClickHouse database)

### The attack

One operator runs multiple miner nodes that all connect to the same external database (e.g.,
ClickHouse, PostgreSQL, Redis). Each node passes TEE attestation independently — the code is
genuine, the measurement matches — but they share the underlying resource, multiplying earnings
without multiplying infrastructure cost:

```
                    ┌─────────────┐
                    │  ClickHouse  │ ← single database instance
                    └──────┬──────┘
                   ┌───────┼───────┐
                   │       │       │
              ┌────▼──┐ ┌──▼───┐ ┌─▼─────┐
              │Miner A│ │Miner B│ │Miner C│  ← 3 nodes, 3 TEE attestations
              └───────┘ └──────┘ └───────┘     all valid, all score=1.0
                                               but only 1× the actual resources
```

### Why TEE alone does not detect this

TEE proves the **code** is genuine. It says nothing about **external resources** the code
connects to. The database connection string, the data inside the database, and the number of
nodes sharing it are all outside the TEE boundary.

### Detection strategies (subnet-level)

These are implemented in the subnet's scoring logic (`NodeScoring.score_peer()`), not in the
TEE layer:

**1. Challenge uniqueness**
Send each miner a unique challenge/query that requires its own computation. If miner A and
miner B receive different challenges but return results that show the same underlying data
patterns (e.g., identical cache hit ratios, same query plans, same row counts), they likely
share a database.

**2. Timing fingerprinting**
A shared database shows correlated latency. When miner A is under load, miner B's response
times degrade (shared I/O, shared connection pool). Monitor response time distributions across
epochs — honest independent miners show uncorrelated latency.

**3. Output correlation analysis**
Across many epochs, compare outputs between all miner pairs. Identical or near-identical results
with statistical significance beyond chance indicate shared resources. Compute pairwise
similarity scores and flag outlier pairs.

**4. TEE-sealed database credentials**
The subnet code (running inside TEE) can generate database credentials sealed to the specific
enclave instance via `SealedStore`. Each enclave would create its own isolated database
namespace. A new enclave instance gets new credentials and a fresh namespace — sharing becomes
impossible because the credentials are hardware-bound.

**5. Canary data injection**
The validator injects unique "canary" rows into each miner's expected dataset (delivered via
encrypted RA-TLS channel). When querying results, the validator checks that each miner's output
includes its specific canary. Two miners sharing a database would either both have all canaries
(detectable) or miss each other's (detectable).

**Recommendation:** Combine challenge uniqueness (easiest to implement) with output correlation
analysis (catches sophisticated sharing). TEE-sealed credentials provide the strongest guarantee
but require the subnet to control database provisioning.

---

## 10c. GPU sharing — enforcing 1 node = 1 GPU

### The attack

An operator with one high-end GPU registers multiple miner nodes, each claiming to have its own
GPU. The GPU is time-sliced or MIG-partitioned between the nodes. Each node passes TEE
attestation (the CPU-side code is genuine), but they share GPU compute:

```
              Physical GPU (A100 80GB)
        ┌──────────┬──────────┬──────────┐
        │ MIG 1    │ MIG 2    │ MIG 3    │  ← 3 slices
        │ 26GB     │ 26GB     │ 26GB     │
        └────┬─────┘────┬─────┘────┬─────┘
             │          │          │
        ┌────▼──┐  ┌────▼──┐  ┌───▼───┐
        │Node A │  │Node B │  │Node C │  ← 3 nodes earn 3× emissions
        └───────┘  └──────┘   └───────┘    but only 1× GPU hardware
```

### Defence layers (strongest to most practical)

**Layer 1: GPU TEE attestation (H100/Blackwell only)**

NVIDIA H100 and Blackwell GPUs have a **hardware-fused ECC-384 private key** burned into
silicon during manufacturing. This key is unextractable — it cannot be read, cloned, or
modified. Each GPU gets a **Device Identity Certificate** signed by NVIDIA's Root CA.

When confidential computing is enabled, the GPU produces an attestation report containing:
- 64 measurement records (firmware, VBIOS, driver hashes)
- The device's unique identity certificate
- Signature from the silicon-fused attestation key

Verification: use NVIDIA's `nv-attestation-sdk` (Python) or the C++ attestation SDK to verify
the report against NVIDIA's Remote Attestation Service (NRAS).

**This is unforgeable.** Two nodes claiming different GPUs will have different device identity
certificates. Two nodes sharing one GPU will present the same certificate — detectable.

Composite attestation (Intel Trust Authority) can verify CPU TEE + GPU in a single workflow,
producing a JWT with both `intel_tee` and `nvidia_gpu` claims.

**Limitation:** Only available on datacenter GPUs (H100, H200, B100, B200). Consumer GPUs
(RTX 4090, etc.) have no hardware root of trust.

**Layer 2: GPU fingerprinting (all GPUs)**

Individual GPUs have microscopic manufacturing variations in their execution units. By running
a standardized compute shader benchmark and measuring timing differences between execution
units, a unique hardware fingerprint emerges (DrawnApart technique).

This can distinguish two GPUs **of the same model and vendor**. If two nodes produce identical
GPU fingerprints, they are the same physical GPU.

Implementation: run a standardised CUDA kernel at attestation time, collect timing vectors,
compare across the network for collisions.

**Layer 3: NVML runtime audit (from inside TEE)**

The subnet code running inside the TEE can query NVML APIs to detect sharing:

| Check | API | What it reveals |
|-------|-----|----------------|
| Process count | `nvmlDeviceGetComputeRunningProcesses_v3()` | More processes than expected → sharing |
| Memory capacity | `nvmlDeviceGetMemoryInfo()` | Less memory than GPU spec → MIG partition |
| GPU UUID format | `nvmlDeviceGetUUID()` | MIG UUID format `MIG-GPU-<parent>/<gi>/<ci>` → partitioned |
| MIG mode | `nvmlDeviceGetMigMode()` | MIG enabled → partitioned |
| Utilisation at idle | `nvmlDeviceGetUtilizationRates()` | Non-zero when node is idle → another workload sharing |

**Limitation:** On non-TEE hardware, GPU UUIDs and serials are spoofable via kernel-mode memory
patching (`nvlddmkm.sys`). NVML checks are only trustworthy when running inside a TEE.

**Layer 4: Performance benchmarking**

Run a standardised compute benchmark (e.g., matrix multiplication of known size) and measure:
- Throughput (TFLOPS) — should match the GPU model's spec
- Latency variance — time-sliced GPUs show high variance due to context switching
- Memory bandwidth — `nvbandwidth` tool measures actual PCIe throughput

A GPU shared between 3 nodes will show ~33% throughput and abnormal latency distributions
compared to exclusive access. The subnet scoring function can reject nodes whose benchmark
results fall below the expected floor for their claimed GPU model.

**Recommended approach:**

For subnets requiring GPU compute:
1. **Require H100/Blackwell** and use GPU TEE attestation (strongest, unforgeable)
2. If consumer GPUs are allowed, combine **GPU fingerprinting** + **NVML audit** + **performance
   benchmarking** in the scoring function
3. Track GPU device IDs across the network — flag any collisions (same GPU UUID on multiple nodes)

---

## 11. What TEE does not protect against

Being clear about the limits is as important as describing the defences.

**Incorrect code:** TEE proves the code is *unmodified from the published binary* — it does not
prove the code is *correct*. A subnet owner who publishes a buggy binary will have all miners
faithfully running the same bug. The measurement hash proves identity, not correctness.

**Malicious subnet owner:** The subnet owner controls `EXPECTED_MEASUREMENT` and the reference
binary. A malicious owner could publish a binary that exfiltrates miner secrets or intentionally
scores certain miners higher. TEE protects miners from each other — it does not protect miners
from the subnet owner.

**Input manipulation:** Work items sent to the miner are encrypted with RA-TLS (attack 5
mitigation), but the validator *chooses* which inputs to send. A malicious validator could send
inputs crafted to produce predictable outputs. TEE does not prevent this.

**Side-channel attacks:** Advanced adversaries with physical access to the hardware can attempt
side-channel attacks (power analysis, cache timing, etc.) against TDX/SEV-SNP enclaves. These
attacks are extremely expensive and hardware-version-specific. They are outside the threat model
for subnet economics but relevant for high-value secrets like model weights.

**Economic collusion (>66% stake):** As noted in attack 6, a true supermajority-stake collusion
cannot be cryptographically blocked. It is prevented economically (stake at risk) and socially
(reputation damage, governance actions).

**Flash loan / delegation attacks:** If stake can be temporarily borrowed to cross the 66%
attestation threshold, collusion becomes cheaper. This is a chain-level economic design question,
not a TEE question.

---

## 12. Economic summary

For each attack, here is the economic consequence if the defence were removed:

| Attack | Economic impact without TEE defence |
|--------|--------------------------------------|
| Identity theft | One TEE machine earns emissions for N nodes; costs scale with node count, earnings scale N× |
| Quote replay | Miners pay TEE hardware amortised over unlimited epochs; honest miners are undercut on cost |
| Debug mode | All "confidential" enclave data is readable; model weights, sealed secrets, input data exposed |
| Measurement swap | Miners with cheap imposter code undercut miners running expensive real code; race to the bottom on quality |
| Output forgery | Miners can earn full emissions by submitting random outputs; no incentive to do actual work |
| Validator collusion | A large validator stake holder can consistently boost preferred miners; systematic extraction |
| Overwatch gap | Without slash, parity mismatches are detected but not punished; detection without deterrence |
| Runtime tampering (CVM) | Operator modifies code post-boot; earns emissions with cheaper/different logic while passing attestation |
| Shared resources | One database serves N nodes; operator earns N× emissions with 1× infrastructure cost |
| GPU sharing | One GPU serves N nodes; operator earns N× emissions with 1× GPU hardware cost |

The TEE subnet's economic argument is that each of these attacks, if possible, creates a
*dominant strategy* that destroys the subnet's quality floor. Miners who invest in honest compute
are undercut by those who don't. The TEE defences exist to maintain the property that *honest
compute is the economically rational strategy*.

For a fuller treatment of why this matters for building businesses on top of subnet outputs, see
[`docs/06-business-case.md`](./06-business-case.md).

---

*Previous: [TEE Subnet Architecture](./03-tee-subnet-architecture.md)*  
*Next: [Bittensor Comparison](./05-bittensor-comparison.md)*
