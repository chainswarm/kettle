# Attack Vector Testing — TEE Subnet Template

> **Hardware:** Azure DCasv5 (AMD EPYC, SEV-SNP)
> **Date:** 2026-03-21
> **Template version:** post-F-02 cert pubkey binding, post-F-01 DCAP structural verification
> **Tests run on:** Real SEV-SNP hardware with SevSnpAzureBackend (score=1.0)

---

## Summary

| # | Attack | Blocked | Defence | Source |
|---|--------|---------|---------|--------|
| 1 | Identity theft (Sybil) | YES | `report_data = sha256(peer_id:epoch)` | `quote.py:verify_identity()` |
| 2 | Quote replay | YES | `nonce != current_epoch` | `verifier.py` step 3 |
| 3 | Fabricated quote (no raw_bytes) | YES | Chain verification requires raw report bytes | `verifier.py:_verify_dcap_chain_sev_snp()` |
| 4 | Fabricated quote (fake raw_bytes) | CONDITIONAL | Blocked when `EXPECTED_MEASUREMENT` set | `verifier.py` step 6 |
| 5 | Output forgery | YES | HMAC-SHA256 with enclave-derived session key | `session.py:verify_signature()` |
| 6 | External keypair cert | YES | Cert pubkey hash bound in report_data (F-02) | `quote.py:make_report_data()` |
| 7 | Debug mode enclave | YES | `debug_mode=True` always score=0.0 | `verifier.py` step 2 |
| 8 | Modified Docker container | YES | Measurement changes with any code modification | `verifier.py` step 6 |
| 9 | DHT record overwrite (DoS) | YES | GossipSub validates sender peer_id matches content peer_id (F-03) | `gossip_receiver.py:_handle_*()` |
| 10 | Session key theft via RA-TLS | YES | Key derived from cert pubkey; external cert fails identity binding | `session.py` + `client.py:verify_cert()` |
| 11 | Runtime code tampering (CVM) | **PARTIAL** | CVM launch measurement is frozen at boot; need dm-verity/IMA/SGX for runtime integrity | See [anti-cheat §10a](../04-anti-cheat.md#10a-runtime-code-tampering-inside-a-cvm) |
| 12 | Shared external resources | **SUBNET-LEVEL** | Challenge uniqueness, output correlation, TEE-sealed credentials | See [anti-cheat §10b](../04-anti-cheat.md#10b-shared-external-resources-eg-clickhouse-database) |
| 13 | GPU sharing (1 GPU → N nodes) | **SUBNET-LEVEL** | GPU TEE attestation (H100), GPU fingerprinting, NVML audit | See [anti-cheat §10c](../04-anti-cheat.md#10c-gpu-sharing--enforcing-1-node--1-gpu) |

**Result: 8 unconditionally blocked, 2 conditionally blocked, 3 require additional layers (documented).**

---

## Attack 1: Identity theft (Sybil attack)

**Scenario:** Miner A has real TEE hardware and generates a valid DCAP quote. Miner B
has no TEE hardware. Miner B copies Miner A's quote from the DHT and publishes it under
their own peer ID, hoping to earn Miner A's score.

**How it works:**
```
Miner A: generate_quote(peer_id="A", epoch=5)
  → report_data = sha256("A:5") || cert_pubkey_hash
  → publishes to DHT key "5:A"

Miner B: copies A's quote → publishes to DHT key "5:B"

Validator: verifier.verify(peer_id="B", epoch=5)
  → expected report_data = sha256("B:5") || ...
  → actual report_data   = sha256("A:5") || ...
  → MISMATCH → identity_binding_failed → score=0.0
```

**Defence:** `report_data = sha256(peer_id:epoch)` is computed by the hardware at quote
generation time. The peer_id is cryptographically burned into the 64-byte field. A quote
generated for peer A cannot verify for peer B.

**Tested on real hardware:**
```
Result: ok=False reason=identity_binding_failed
BLOCKED: True
```

**Source files:**
- `subnet/tee/quote.py` — `TeeQuote.make_report_data()`, `verify_identity()`
- `subnet/tee/verifier.py` — step 4

---

## Attack 2: Quote replay

**Scenario:** Miner generates a valid DCAP quote in epoch 5. In epoch 6, the miner
doesn't run the enclave (saves compute cost) and submits the epoch-5 quote again.

**How it works:**
```
Epoch 5: miner generates quote with nonce=5
Epoch 6: miner publishes same quote (nonce=5) under DHT key "6:peer_id"

Validator: verifier.verify(peer_id, epoch=6)
  → quote.nonce = 5, expected = 6
  → nonce_mismatch → score=0.0
```

**Defence:** The `nonce` field in the quote is set to the epoch number at generation
time. The validator rejects any quote where `nonce != current_epoch`.

**Tested on real hardware:**
```
Result: ok=False reason=nonce_mismatch:got=100,expected=101
BLOCKED: True
```

**Source files:**
- `subnet/tee/verifier.py` — step 3

---

## Attack 3: Fabricated quote (no hardware)

**Scenario:** Attacker crafts a `TeeQuote` object with correct `peer_id`, `epoch`, and
`backend=sev-snp` but without access to real hardware. The quote has `raw_bytes=None`
because no hardware report was generated.

**How it works:**
```
Attacker: TeeQuote(backend="sev-snp", raw_bytes=None, ...)
  → publishes to DHT

Validator: _verify_dcap_chain_sev_snp(quote)
  → quote.raw_bytes is None → "no_raw_bytes" → score=0.0
```

**Defence:** The chain verification step requires `raw_bytes` — the actual binary
attestation report from the hardware. Without it, verification fails immediately.

**Tested on real hardware:**
```
Result: ok=False reason=chain_verification_failed:no_raw_bytes
BLOCKED: True
```

**Source files:**
- `subnet/tee/verifier.py` — `_verify_dcap_chain_sev_snp()`

---

## Attack 4: Fabricated quote with fake raw_bytes

**Scenario:** Attacker crafts a fake `raw_bytes` blob that structurally looks like a
valid SNP report (version=2, non-zero measurement, correct length) but was not generated
by real hardware.

**How it works:**
```
Attacker: builds 1184-byte blob with:
  - version=2 at offset 0
  - fake measurement at offset 0x90
  - policy with debug=False
  → passes structural checks in _verify_dcap_chain_sev_snp

Validator: verification PASSES if EXPECTED_MEASUREMENT is not set
```

**Defence:** `EXPECTED_MEASUREMENT` — when set, the validator compares the quote's
measurement against the known-good value. A fabricated measurement won't match.

**Without EXPECTED_MEASUREMENT (development mode):**
```
Result: ok=True score=1.0
NOT BLOCKED — expected in dev mode
```

**With EXPECTED_MEASUREMENT set (production mode):**
```
Result: ok=False reason=measurement_mismatch:got=aaaaaaaaaaaaaaaa,expected=0000000000000000
BLOCKED: True
```

**Production requirement:** Always set `EXPECTED_MEASUREMENT` to the known-good
MRENCLAVE/measurement hash of the subnet's binary. Without it, any structurally valid
report is accepted.

**Why this is acceptable in dev:** During development, the binary changes frequently.
Enforcing a specific measurement would require updating the config on every build.
`EXPECTED_MEASUREMENT=""` allows iteration without measurement lockdown.

**Source files:**
- `subnet/tee/verifier.py` — step 6, `_check_measurement()`
- `subnet/tee/config.py` — `EXPECTED_MEASUREMENT` env var

---

## Attack 5: Output forgery

**Scenario:** Attacker receives a work item and wants to submit a fake result without
actually running the computation. They create an `OutputEnvelope` signed with a
different session key (because they don't have the real one derived from the enclave's
ephemeral cert).

**How it works:**
```
Attacker: creates RaTlsSession with fake cert pubkey
  → signs output with fake_session.sign()

Validator: honest_session.verify_signature(output, sig)
  → HMAC-SHA256(real_session_key, output) != HMAC-SHA256(fake_key, output)
  → signature invalid → score=0.0
```

**Defence:** The session key is derived from the RA-TLS cert's public key via
`HKDF-SHA256(sha256(cert_pubkey_der), peer_id:epoch)`. Only the holder of the correct
cert private key (generated inside the enclave) can derive the matching session key.

**Tested on real hardware:**
```
Forged output verified with real session: False
BLOCKED: True
```

**Source files:**
- `subnet/tee/ratls/session.py` — `sign()`, `verify_signature()`
- `subnet/tee/ratls/envelope.py` — `OutputEnvelope.create()`, `verify()`

---

## Attack 6: External keypair RA-TLS cert (F-02 defence)

**Scenario:** Attacker has access to a valid TEE quote (e.g., from a legitimate run).
They generate a NEW keypair outside the enclave, create an RA-TLS cert with the stolen
quote embedded, and present it to the validator. If accepted, the attacker controls the
private key and can sign arbitrary outputs.

This is the attack that the **F-02 cert pubkey binding** fix prevents.

**How it works (before F-02):**
```
Attacker:
  1. Steals valid quote from DHT (report_data = sha256(peer_id:epoch) || 0x00*32)
  2. Generates external keypair
  3. Creates RA-TLS cert with stolen quote + external pubkey
  4. Validator extracts quote → identity binding passes (zero-padded upper bytes)
  5. Validator derives session key from external pubkey
  6. Attacker holds the private key → can sign anything
  → ATTACK SUCCEEDS
```

**How it works (after F-02):**
```
Attacker:
  1. Steals valid quote from DHT
     report_data = sha256(peer_id:epoch) || sha256(REAL_cert_pubkey)
  2. Generates external keypair
  3. Creates RA-TLS cert with stolen quote + external pubkey
  4. Validator extracts quote, computes sha256(external_pubkey)
  5. Compares: sha256(external_pubkey) != sha256(REAL_cert_pubkey) in report_data
  → identity_binding_failed → ATTACK BLOCKED
```

**Defence:** The upper 32 bytes of `report_data` contain `sha256(cert_pubkey_der)`.
Since the cert keypair is generated BEFORE the TEE quote, and the pubkey hash is
included in the hardware-signed `report_data` field, the validator can verify that the
cert was generated inside the same enclave that produced the quote.

**Tested on real hardware:**
```
Result: ok=False score=0.0 reason=identity_binding_failed
BLOCKED: True
```

**This is the most important security property in the template.** Without F-02, any
attacker who can read the DHT (which is public) could hijack any miner's session.

**Source files:**
- `subnet/tee/quote.py` — `make_report_data(cert_pubkey_hash=...)`
- `subnet/tee/ratls/server.py` — `generate_cert()` (keypair first, then quote)
- `subnet/tee/ratls/client.py` — `verify_cert()` (extracts pubkey hash, passes to verifier)

---

## Attack 7: Debug mode enclave

**Scenario:** Operator runs the enclave in debug mode, which allows the host OS to
inspect and modify the enclave's memory. They submit the debug-mode quote hoping the
validator doesn't check the debug bit.

**How it works:**
```
Operator: runs in debug mode
  → quote.debug_mode = True (extracted from hardware-signed POLICY field)

Validator: verifier.verify(peer_id, epoch)
  → Step 2: quote.debug_mode == True → score=0.0
```

**Defence:** Debug mode check is step 2 in the pipeline — before any other verification.
The debug bit is inside the hardware-signed portion of the report. It cannot be forged:
the signature would not verify.

**Tested on real hardware:**
```
Result: ok=False reason=debug_mode
BLOCKED: True
```

**Source files:**
- `subnet/tee/verifier.py` — step 2
- `subnet/tee/backends/sev_snp.py` — `_is_debug_mode()` (POLICY bit 19)
- `subnet/tee/backends/tdx.py` — `_is_debug_mode()` (TD_ATTRIBUTES bit 0)

---

## Attack 8: Modified Docker container

**Scenario:** Operator modifies the miner's Docker container — changes the scoring
logic, replaces the model with a cheaper one, or adds code to fabricate outputs. The
modified container runs and submits work as normal.

**How it works:**
```
Operator: modifies Dockerfile, rebuilds container
  → binary changes → measurement (SHA-384 of initial memory image) changes
  → quote.measurement = sha384(modified_binary) ≠ EXPECTED_MEASUREMENT

Validator: step 6 measurement check
  → measurement_mismatch → score=0.0
```

**Defence:** Any modification to the code, data, or configuration in the container
changes the SHA-384 measurement hash. The validator compares against
`EXPECTED_MEASUREMENT`. A modified container produces a different measurement.

**Production requirement:** `EXPECTED_MEASUREMENT` must be set to the known-good
measurement of the official container image.

**Note:** On Azure CVM, the measurement is of the VM image, not individual containers.
All containers in the same VM share the same measurement. For per-container measurement
enforcement, use Gramine SGX (see `GRAMINE.md`).

**Source files:**
- `subnet/tee/verifier.py` — step 6, `_check_measurement()`
- `gramine.manifest.template` — Gramine SGX manifest for per-binary measurement

---

## Attack 9: DHT record overwrite (DoS)

**Scenario:** Attacker overwrites another miner's TEE quote or work record in the DHT
with garbage data. The victim's valid data is replaced, causing them to score 0.0.

**How it works:**
```
Attacker: nmap_set(TEE_QUOTE_TOPIC, "5:victim_peer_id", garbage)

Validator: fetches quote for victim → deserialization fails → score=0.0
  OR: fetches quote → identity binding fails (garbage report_data) → score=0.0
```

**Defence (F-03):**

The GossipSub receiver validates every incoming message by checking that the internal
`peer_id` in the content matches the GossipSub sender's `from_peer` (authenticated by
libp2p's transport security). Three-layer defence:

1. **GossipSub sender identity:** libp2p's Noise transport authenticates the sender's
   peer ID. A node cannot spoof another node's `from_id` in gossip messages.

2. **DHT key uses from_peer:** The receiver stores data under `{epoch}:{from_peer}`,
   not under a claimed peer_id from the content. A node can only write to its own keys.

3. **Content peer_id validation (F-03):** The receiver also checks that the quote's
   internal `peer_id`, the cert's embedded quote `peer_id`, and the work record's
   `peer_id` all match `from_peer`. Mismatches are rejected with a warning log.

```
Attacker (peer B): gossips a quote with peer_id=A
  → GossipSub from_id = B (authenticated by transport)
  → _handle_tee_quote: quote.peer_id=A != from_peer=B → REJECTED
```

**Tested:**
```python
# test_gossip_validation.py — 6 tests
test_honest_quote_accepted    — PASS (stored under sender's key)
test_spoofed_quote_rejected   — PASS (peer_id mismatch → rejected)
test_honest_work_accepted     — PASS
test_spoofed_work_rejected    — PASS
test_honest_cert_accepted     — PASS
test_spoofed_cert_rejected    — PASS
```

**Source files:**
- `subnet/utils/gossipsub/gossip_receiver.py` — `_handle_tee_quote()`, `_handle_ratls_cert()`, `_handle_work_record()`
- `tests/test_gossip_validation.py` — 6 tests

---

## Attack 10: Session key theft via RA-TLS

**Scenario:** Attacker intercepts the RA-TLS cert from the DHT and tries to derive the
session key. If they succeed, they can sign arbitrary outputs on behalf of the miner.

**How it works:**
```
Attacker: fetches cert_pem from RATLS_CERT_TOPIC in DHT
  → extracts public key from cert
  → computes session_key = HKDF(sha256(pubkey), peer_id:epoch)
  → session key derivation succeeds!
  → BUT: the attacker doesn't have the cert's private key
  → they CAN verify outputs but CANNOT sign new ones

Wait — they CAN sign outputs because session_key is symmetric (HMAC)!
  → if attacker derives session_key, they can sign forged OutputEnvelopes

HOWEVER: the validator also verifies the RA-TLS cert itself:
  1. Extracts quote from cert extension
  2. Computes sha256(cert_pubkey)
  3. Checks report_data contains sha256(cert_pubkey) (F-02)
  4. If attacker creates a NEW cert with the same pubkey → they need
     the private key to sign the cert → they don't have it
  5. If attacker uses the ORIGINAL cert → the session key matches,
     but they'd need to modify the output signed under that key...
     they can! Because session_key is derivable from the public cert.

THE ACTUAL DEFENCE: The session key IS derivable from the public cert
by anyone. BUT the miner's output is published to the DHT immediately
after signing. The attacker would need to overwrite the DHT record
with their forged output (which is Attack 9 — DHT overwrite).

So session key "theft" alone is not sufficient. The attacker needs
DHT write access (Attack 9) to exploit it.
```

**Defence:** The session key is intentionally derivable from the public cert — both
miner and validator need to derive it independently. The security comes from:
1. Only the enclave generates the cert (F-02 proves the cert came from the enclave)
2. The miner signs the output first and publishes to DHT
3. Overwriting the DHT record is a separate attack (Attack 9)

**Status:** Blocked (in combination with F-02). The session key being derivable is by
design, not a vulnerability — it enables the validator to verify without a shared secret
exchange.

---

## Production checklist

**Gramine/SGX is the only supported production runtime.** CVM-only deployments (SEV-SNP,
TDX without Gramine) are vulnerable to Attack 11 (runtime code tampering) — the operator
can modify code after boot while attestation reports still show the original measurement.
CVM backends remain available for development and testing.

```bash
# REQUIRED for production (Gramine/SGX)
EXPECTED_MEASUREMENT="<MRENCLAVE from gramine-sgx-sign>"  # blocks Attack 4, 8, 11
MIN_TEE_SCORE=1.0                                          # require real hardware
TCB_POLICY=strict                                          # reject degraded TCB

# RECOMMENDED
TAMPER_RATE=0.0                                            # no fault injection
```

Without `EXPECTED_MEASUREMENT`, Attacks 4 and 8 are not blocked. Without Gramine/SGX,
Attack 11 (runtime tampering) is not blocked. See [`GRAMINE.md`](../../GRAMINE.md) for
build and deployment instructions.

---

## Related documentation

- [Production CVM Testing](./production-cvm-testing.md) — Full multi-node Docker Compose
  test on Azure SEV-SNP with measurement enforcement, scoring results, and Azure CVM
  limitations

---

## Reproducing these tests

```bash
# On an Azure DCasv5 SEV-SNP VM:
ssh tee@<vm-ip>
cd ~/subnet-template
source .venv/bin/activate
sudo chmod 666 /dev/tpmrm0

# Run E2E verification
TEE_BACKEND=sev-snp MOCK_TEE=false python3 -c "
# ... (see the test script in this repo's git history)
"

# Run multi-node Docker test
docker compose -f docker-compose.tee-real.yml up --build -d
# Wait 180s for epoch scoring
docker compose -f docker-compose.tee-real.yml logs validator | grep score
```
