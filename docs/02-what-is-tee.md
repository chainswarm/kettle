# What Is a Trusted Execution Environment?

> **Audience:** Developers and subnet architects who have not worked with hardware security features before.  
> **After reading this:** You will understand what a TEE is, what it proves, how DCAP attestation
> works end-to-end, how Intel TDX and AMD SEV-SNP differ mechanically, and what hardware you need
> to run a TEE subnet in production.

---

## Contents

1. [The threat TEE solves](#1-the-threat-tee-solves)
2. [What a TEE is](#2-what-a-tee-is)
3. [What attestation proves](#3-what-attestation-proves)
4. [Intel TDX](#4-intel-tdx)
5. [AMD SEV-SNP](#5-amd-sev-snp)
6. [The DCAP attestation lifecycle](#6-the-dcap-attestation-lifecycle)
7. [Identity binding — how a quote is tied to a specific node and epoch](#7-identity-binding)
8. [TCB status — what happens when firmware is outdated](#8-tcb-status)
9. [The debug mode trap](#9-the-debug-mode-trap)
10. [Sealed storage](#10-sealed-storage)
11. [ARM TrustZone — a note](#11-arm-trustzone)
12. [Cloud TEE options](#12-cloud-tee-options)
13. [Hardware requirements](#13-hardware-requirements)
14. [MOCK_TEE — development without hardware](#14-mock_tee)

---

## 1. The threat TEE solves

In a decentralised compute subnet, you pay nodes to do work — run inference, score data, verify
computations. The problem is you cannot trust the node operator. A rational miner will:

- Claim to run the correct model version while actually running a cheaper one
- Submit fake outputs without doing any work at all
- Copy another miner's output and re-submit it as their own
- Run the correct model but on tampered inputs that produce the scores they want

On a subnet without TEE, validators can try to catch cheating by sampling and re-running the work
themselves — but this only works if the cheating rate is above the sampling rate, and it costs
validators the same compute they are trying to verify. The fundamental problem is that a validator
cannot tell whether a miner's output was produced by the correct code on unmodified hardware.

A Trusted Execution Environment solves this by making the claim *hardware-verifiable*: the miner
generates a cryptographic proof that its code ran inside a genuine, unmodified hardware enclave.
A validator can verify this proof in milliseconds, without re-running the work.

---

## 2. What a TEE is

A Trusted Execution Environment is a hardware-isolated region of a processor where code runs with
the following guarantees:

- **Confidentiality:** The host operating system, hypervisor, and other processes cannot read the
  enclave's memory — not even the root user on the machine
- **Integrity:** Any modification to the enclave's code or data is detected; the enclave refuses
  to run
- **Attestation:** The hardware can produce a cryptographically signed proof of what code is
  running inside the enclave — down to the exact binary hash

The key word is *hardware*. These guarantees are enforced by CPU microcode and the processor's
firmware — not by software that an attacker could modify. The cloud provider, the node operator,
and the OS are all in the untrusted zone. The enclave is not.

```
┌────────────────────────────────────────────────────────────┐
│ Host (untrusted zone)                                       │
│                                                            │
│   OS kernel / hypervisor / other processes                 │
│   Root user — can read any non-enclave memory              │
│                                                            │
│   ┌─────────────────────────────────────────────────────┐  │
│   │ TEE Enclave (trusted zone)                          │  │
│   │                                                     │  │
│   │   Your subnet miner code                           │  │
│   │   Model weights (optional — can be sealed)         │  │
│   │   Inputs and outputs                               │  │
│   │                                                     │  │
│   │   Memory is encrypted at the hardware level        │  │
│   │   OS cannot read or modify this region             │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

The enclave can *attest* to the outside world: "I am a genuine Intel TDX / AMD SEV-SNP enclave,
and the code currently running inside me has measurement hash `0xabc123...`."

---

## 3. What attestation proves

An attestation quote is a hardware-signed binary blob that proves four things:

| Claim | What proves it |
|---|---|
| **Hardware genuineness** | The quote is signed by the CPU's endorsement key, which only a real Intel/AMD CPU possesses |
| **Measurement (code integrity)** | The SHA-384 hash of the enclave image at load time — any tampering with the binary changes this hash |
| **User data binding** | A 64-byte field the enclave writes before quoting — used to bind the quote to application context (see §7) |
| **TCB status** | Whether the platform firmware (CPU microcode, BIOS, QE) is current or needs updates (see §8) |

What a quote **does not** prove:
- That the enclave produced *correct* results (it proves the *code* was unmodified, not that the code is bug-free)
- That the inputs were valid (inputs are not included in the measurement)
- That the enclave did not time out or crash during execution

The TEE subnet template uses attestation to prove *code identity*: a validator can confirm that
miner-3 is running the exact binary version of the scoring code that the subnet owner published,
and has not tampered with it.

---

## 4. Intel TDX

**TDX = Trust Domain Extensions.** TDX is Intel's approach to TEE at the *virtual machine* level —
the entire VM is a Trust Domain (TD), not just a single process.

### How it works

1. A specially configured VM (the TD) is started under the TDX-aware hypervisor
2. The CPU encrypts all of the TD's memory with a key that only the CPU holds
3. On boot, the CPU measures every page loaded into the TD — producing MRTD (Measurement Register
   of the Trust Domain), a SHA-384 hash of the initial memory contents
4. The MRTD is later included in the attestation quote

### Quote generation

TDX quote generation uses a **DCAP (Data Center Attestation Primitives)** architecture:

1. The guest OS calls the TDX driver (`/dev/tdx_guest`) with a 64-byte `report_data` value
2. The CPU writes the report data into a TD Report and signs it with the hardware key
3. A Quoting Enclave (QE) — a separate Intel-signed enclave running on the same host — wraps the
   TD Report into a full DCAP quote with a PCK certificate chain
4. The quote is a binary blob the miner can publish and validators can verify

### What the TPP code does

In `subnet/tee/backends/tdx.py`:

```python
# Miner — generating the quote
report_data = TeeQuote.make_report_data(peer_id, epoch)  # sha256(peer_id:epoch), 64 bytes
raw_quote = libtdx_attest.tdx_attest_get_quote(report_data)  # IOCTL to /dev/tdx_guest
```

The raw quote layout:
```
TDX quote (v4):
  Offset  0:    Quote header (48 bytes)
  Offset 48:    TD Report body (584 bytes)
    Offset 48+272: TD_ATTRIBUTES (8 bytes)  ← debug bit lives here
    Offset 48+512: MRTD (48 bytes)          ← measurement lives here
  Offset 632:   QE Report (384 bytes)
  Offset 1016:  PCK certificate chain
  Offset ...:   ECDSA signature
```

### Hardware requirements

- **CPU:** Intel Xeon Scalable 3rd gen (Ice Lake-SP) or later, with TDX enabled in BIOS
- **Recommended:** 4th gen (Sapphire Rapids) — TDX is more mature and widely supported
- **Kernel:** Linux 6.2+ with `intel_vt_d` + TDX guest modules loaded
- **Driver:** `/dev/tdx_guest` must be present inside the guest VM
- **Library:** `libtdx-attest` (Intel's attestation library)

---

## 5. AMD SEV-SNP

**SEV-SNP = Secure Encrypted Virtualization — Secure Nested Paging.** AMD's equivalent to TDX,
also at the VM level, with a different signing architecture.

### How it differs from TDX

| Aspect | Intel TDX | AMD SEV-SNP |
|---|---|---|
| **Signing key** | Per-platform key generated in a Quoting Enclave | VCEK (Versioned Chip Endorsement Key) — unique per chip per firmware version |
| **Quote issuer** | Intel root CA via PCK cert chain | AMD root CA via VCEK cert chain |
| **Device node** | `/dev/tdx_guest` | `/dev/sev-guest` |
| **Kernel version** | 6.2+ | 5.19+ |
| **ioctl command** | `TDX_CMD_GET_QUOTE` | `SNP_GET_REPORT` |
| **Report size** | ~4KB (variable, includes cert chain) | 1184 bytes (fixed) + optional certificates |
| **Measurement register** | MRTD (SHA-384) | MEASUREMENT field at report offset `0x90` (SHA-384) |

### Quote generation

1. The guest calls `/dev/sev-guest` ioctl with `SNP_GET_REPORT` and a 96-byte request struct
   (64-byte user_data + VMPL level)
2. The PSP (Platform Security Processor — AMD's equivalent of Intel ME) generates the report
3. The report is signed by the VCEK, whose certificate chain leads to the AMD root CA

In `subnet/tee/backends/sev_snp.py`:

```python
# Miner — generating the report
report_data = TeeQuote.make_report_data(peer_id, epoch)  # same 64-byte binding as TDX
req = report_data + struct.pack("<I", 0) + b"\x00" * 28   # 96-byte SNP request
fcntl.ioctl(fd, SNP_GET_REPORT, buf)                      # ioctl to /dev/sev-guest
```

The attestation report layout (AMD SEV-SNP ABI spec, v1.55):
```
SNP Attestation Report (1184 bytes):
  Offset 0x00: VERSION (4 bytes)
  Offset 0x08: POLICY (8 bytes)       ← debug bit is bit 19
  Offset 0x90: MEASUREMENT (48 bytes) ← SHA-384, same role as TDX MRTD
  Offset 0xC0: HOST_DATA (32 bytes)   ← our user_data binding
  ...
```

### Hardware requirements

- **CPU:** AMD EPYC Milan (3rd gen) or Genoa (4th gen) with SEV-SNP enabled in BIOS
- **Kernel:** Linux 5.19+ with SEV-SNP guest modules
- **Driver:** `/dev/sev-guest` must be present inside the guest VM
- **Tools:** `sev-guest-tool` or `sevsnpattest` for quote/report generation

---

## 6. The DCAP attestation lifecycle

DCAP (Data Center Attestation Primitives) is Intel's attestation architecture for data centre
deployments — as opposed to the older EPID architecture which required a centralised Intel server
for every attestation. DCAP allows validators to verify quotes locally using cached certificate
collateral.

```
QUOTE GENERATION (miner side)
────────────────────────────────
1. Miner code prepares report_data = sha256(peer_id + ":" + epoch)

2. Hardware generates TD Report / SNP Report containing:
   - measurement (MRTD / MEASUREMENT)  — hash of the running code
   - report_data                        — our application binding
   - platform/firmware info

3. Quoting Enclave (TDX) or PSP (SEV-SNP) signs the report:
   - TDX: QE wraps TD Report + PCK certificate chain → DCAP quote
   - SEV-SNP: PSP signs with VCEK → attestation report

4. Miner publishes quote to DHT:
   nmap_put(TEE_QUOTE_TOPIC, f"{epoch}:{peer_id}", quote_bytes)

──────────────────────────────────────────────────────────────

QUOTE VERIFICATION (validator side, per epoch)
────────────────────────────────────────────────
1. Validator fetches quote from DHT:
   nmap_get(TEE_QUOTE_TOPIC, f"{epoch}:{peer_id}") → TeeQuote

2. Step-by-step DcapVerifier pipeline (first failure → 0.0):
   a. Quote found?              — missing → reject (not attesting)
   b. debug_mode=False?         — debug quotes always rejected
   c. quote.nonce == epoch?     — replay attack protection
   d. sha256(peer_id:epoch) == report_data?  — identity binding
   e. Certificate chain valid?  — mock: HMAC; real: PCK/VCEK chain
   f. measurement == EXPECTED_MEASUREMENT?   — code integrity check
   g. TCB status policy         — UpToDate→1.0; degraded→0.5 or 0.0

3. Returns VerificationResult{score: 0.0 | 0.5 | 1.0}
```

The validator never re-runs the miner's code. It only checks the cryptographic proof. This is what
makes TEE verification *fast* — milliseconds, not seconds — and *scalable* across arbitrarily
many miners.

---

## 7. Identity binding

A TEE quote proves that *some* enclave of measurement `M` is running. Without additional binding,
a rogue miner could:

1. Run the enclave once to generate a valid quote
2. Submit that quote for every epoch, forever (replay attack)
3. Generate one quote on machine A and submit it on behalf of machine B (Sybil attack)

The TEE subnet template prevents both attacks with **identity binding**: before generating the
quote, the miner computes:

```python
# subnet/tee/quote.py
report_data = sha256(f"{peer_id}:{epoch}".encode()).digest()  # 32 bytes
report_data = report_data + b"\x00" * 32                      # zero-padded to 64 bytes
```

This 64-byte value is written into the hardware's `report_data` / `user_data` field before the
CPU generates the quote. The CPU includes this value verbatim in the signed attestation.

The validator checks:

```python
# DcapVerifier step 4 — identity binding
expected = sha256(f"{peer_id}:{epoch}".encode()).hexdigest().ljust(128, "0")
if quote.report_data != expected:
    return VerificationResult.fail("identity_binding_failed")
```

Result:
- **Replay attack blocked:** A quote generated for epoch 5 will not pass verification in epoch 6
  (the epoch in `report_data` won't match)
- **Sybil attack blocked:** A quote generated for `peer_id=A` will not pass verification for
  `peer_id=B` (the peer ID in `report_data` won't match)

Identity binding is the difference between a TEE quote that proves "some legitimate code ran
somewhere" and one that proves "this specific node's code ran in this specific epoch."

---

## 8. TCB status

TCB stands for **Trusted Computing Base** — the set of hardware and firmware that the attestation
relies on. If any component in the TCB has known vulnerabilities, Intel/AMD flags the quote with
a degraded TCB status.

| TCB Status | Meaning | TEE subnet score |
|---|---|---|
| `UpToDate` | Platform firmware is fully patched | `1.0` |
| `SWHardeningNeeded` | Microcode update available (software mitigation only) | `0.5` (permissive) or `0.0` (strict) |
| `ConfigNeeded` | BIOS configuration needs updating | `0.5` (permissive) or `0.0` (strict) |
| `OutOfDate` | Firmware is significantly out of date | `0.0` |
| `Revoked` | Platform has been revoked by Intel/AMD | `0.0` |

**Strict vs permissive policy:** Controlled by the `TCB_POLICY` env var:
- `permissive` (default): `SWHardeningNeeded` and `ConfigNeeded` return 0.5 instead of 0.0
- `strict`: any status other than `UpToDate` returns 0.0

For production subnets with real value at stake, `strict` + `MIN_TEE_SCORE=1.0` is recommended.
This rejects any node whose platform is not fully patched.

---

## 9. The debug mode trap

Both Intel TDX and AMD SEV-SNP support a **debug mode** that allows the host OS to inspect the
enclave's memory — useful for development, but completely defeating the security guarantees.

A debug-mode quote looks exactly like a real production quote except for a single bit:
- TDX: `TD_ATTRIBUTES.debug` bit (at quote offset `48+272`, bit 0)
- SEV-SNP: `POLICY.debug_swap` bit (report offset `0x08`, bit 19)

The DcapVerifier checks this bit in step 2 of the pipeline and returns `score=0.0` unconditionally:

```python
# DcapVerifier step 2
if quote.debug_mode:
    return VerificationResult.fail("debug_mode")
```

This check is before any other evaluation — it cannot be bypassed by crafting a quote with a
valid certificate chain or correct measurement. A debug quote is always rejected.

This matters economically: if a node operator forgot to disable debug mode, they earn 0 emissions
on that epoch. The validator does not need to re-run the work to know the result is untrusted.

---

## 10. Sealed storage

Sealed storage is a TEE feature that binds encrypted data to the enclave's measurement. Data
encrypted with the measurement-derived key can only be decrypted by the exact same binary.

In the TEE subnet template (`subnet/tee/sealed/store.py`):

```python
# Key is derived from the enclave measurement (MRTD / MEASUREMENT)
sealing_key = sha256(measurement.encode()).digest()   # 32-byte AES-256 key

# Encrypt
ciphertext, nonce = aes_gcm_encrypt(sealing_key, plaintext)

# Decrypt — fails if called from a different binary version
plaintext = aes_gcm_decrypt(sealing_key, ciphertext, nonce)
```

**What this prevents:** If a subnet node stores sensitive data (model weights, user data, private
keys) in sealed storage, an operator who modifies the binary cannot access that data. The modified
binary has a different measurement → different sealing key → decryption fails.

**Limitation in the current implementation:** The sealing key is derived from the runtime
measurement, not the hardware sealing key (which would survive reboots across the same binary
version). For crash recovery (commit without reveal), the production fix is to persist the salt
to sealed storage before the commit extrinsic fires.

---

## 11. ARM TrustZone — a note

ARM TrustZone is the TEE architecture used in smartphones and embedded devices. It works at the
instruction set level (Secure World vs Normal World) rather than at the VM level like TDX/SEV-SNP.

TrustZone is **not supported** in the TEE subnet template. The relevant hardware for
subnet deployment is Intel TDX and AMD SEV-SNP. However, **production deployments require
Gramine/SGX** — CVM-only deployments (SEV-SNP, TDX without Gramine) are vulnerable to
runtime code tampering by the operator (see [anti-cheat §10a](04-anti-cheat.md#10a-runtime-code-tampering-inside-a-cvm)).

TrustZone may become relevant if the subnet template is extended to support edge inference
(running miners on ARM servers like AWS Graviton) — but that is a future scope item.

---

## 12. Cloud TEE options

You do not need to own physical hardware to run a TEE subnet. Several cloud providers
offer confidential VM instances with Intel TDX or AMD SEV-SNP. Note: CVM instances are
useful for **development and testing** real attestation, but **production requires
Gramine/SGX** for runtime integrity:

| Cloud | Instance type | TEE backend | Notes |
|---|---|---|---|
| **Microsoft Azure** | DCasv5-series, DCadsv5-series | AMD SEV-SNP | Generally available; VCEK cert chain via IMDS |
| **Microsoft Azure** | DCesv5-series (preview) | Intel TDX | Preview as of early 2026; requires attestation service enrollment |
| **Google Cloud** | N2D Confidential VM | AMD SEV-SNP | Generally available; VCEK via GCP IMDS |
| **Google Cloud** | C3 Confidential VM | Intel TDX | Generally available on Sapphire Rapids C3 |
| **AWS** | No production offering | — | AWS Nitro Enclaves use a different model (not DCAP-compatible) |
| **Bare metal** | Any Intel Sapphire Rapids / AMD EPYC Genoa server | TDX or SEV-SNP | Full control; no cloud overhead |

**AWS caveat:** AWS Nitro Enclaves provide process isolation but use a different attestation
mechanism that is not compatible with DCAP. If your subnet requires DCAP attestation, AWS is
not currently an option for production miners.

For development and CI, all cloud options are unnecessary — `MOCK_TEE=true` provides a
software-only attestation that exercises the full verification pipeline without hardware.

---

## 13. Hardware requirements

### Summary table

| Component | Intel TDX | AMD SEV-SNP |
|---|---|---|
| **CPU generation** | Intel Xeon Scalable 3rd gen (Ice Lake) or 4th gen (Sapphire Rapids) | AMD EPYC Milan (3rd gen) or Genoa (4th gen) |
| **BIOS setting** | TDX enabled under Virtualization settings | SEV-SNP enabled under AMD Memory Guard |
| **Linux kernel** | 6.2+ (TDX guest modules) | 5.19+ (SEV-SNP guest modules) |
| **Device node** | `/dev/tdx_guest` | `/dev/sev-guest` |
| **Userspace library** | `libtdx-attest` (Intel package) | `sev-guest-tool` or kernel ioctl directly |
| **PCCS / cert service** | Intel PCS or local PCCS instance | AMD KDS (Key Distribution Service) |

### Checking availability

```bash
# TDX
ls /dev/tdx_guest && echo "TDX available" || echo "TDX not available"

# SEV-SNP
ls /dev/sev-guest && echo "SEV-SNP available" || echo "SEV-SNP not available"
```

If neither device is present, use `MOCK_TEE=true` for development.

---

## 14. MOCK_TEE — development without hardware

The TEE subnet template ships with `MockBackend` — a software-only TEE simulation using HMAC-SHA256
instead of hardware signing. It implements the full quote lifecycle but uses a shared key instead
of hardware attestation.

```bash
# Enable mock TEE (default in docker-compose.tee-dev.yml)
MOCK_TEE=true docker compose -f docker-compose.tee-dev.yml up
```

| Mock TEE behaviour | Real TEE behaviour |
|---|---|
| Quote signed by HMAC with `MOCK_TEE_KEY` | Quote signed by CPU endorsement key |
| Score = `0.5` (always) | Score = `1.0` (UpToDate) or `0.5` (degraded TCB) |
| No hardware required | Requires TDX or SEV-SNP hardware or cloud VM |
| `tee_score = 0.5` in consensus | `tee_score ∈ {0.5, 1.0}` based on TCB |
| Passes all 194 tests | Requires hardware for hardware-specific tests |

Mock mode is **intentionally scored at 0.5**, not 1.0. This makes it immediately visible in
metrics whether a node is running mock or real hardware: if all nodes show `tee_score=0.5`, you
know no real hardware is involved. To require real hardware in production, set `MIN_TEE_SCORE=1.0`
in your subnet config — mock nodes will be excluded from rewards.

For production deployment with Gramine and Intel TDX, see [`GRAMINE.md`](../GRAMINE.md).

---

*Previous: [What Is Hypertensor?](./01-what-is-hypertensor.md)*  
*Next: [TEE Subnet Architecture](./03-tee-subnet-architecture.md)*
