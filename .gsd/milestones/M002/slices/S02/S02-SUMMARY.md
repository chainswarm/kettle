---
id: S02
parent: M002
milestone: M002
provides:
  - subnet/tee/ratls/envelope.py — WorkEnvelope (AES-GCM encrypted work items), OutputEnvelope (HMAC-SHA256 signed outputs), TeeDecryptionError
  - subnet/tee/quote.py — RATLS_CERT_TOPIC = "ratls_cert" constant
  - subnet/tee/ratls/__init__.py — three new symbols exported
  - subnet/node/mock.py — miner_loop publishes cert_pem to RATLS_CERT_TOPIC + stores signed OutputEnvelope; validator_call verifies cert via RaTlsClient + verifies OutputEnvelope signature; MockOverwatchVerifier unpacks OutputEnvelope without sig check
  - tests/tee/test_envelope.py — 16-test acceptance suite (envelope contract + MockNodeProtocol integration)
  - tests/test_mock_node.py — all tests updated for OutputEnvelope DHT format
  - .gsd/REQUIREMENTS.md — R014 validated
requires:
  - slice: S01
    provides: RaTlsServer, RaTlsClient, RaTlsSession (HKDF-SHA256, AES-GCM, HMAC sign/verify)
affects:
  - S03 — sealed storage is independent; no interface changes from S02
  - S04 — Gramine manifest depends on S01–S03; S02 adds no new gramine concerns
key_files:
  - subnet/tee/ratls/envelope.py
  - subnet/node/mock.py
  - tests/tee/test_envelope.py
  - tests/test_mock_node.py
  - subnet/tee/quote.py
key_decisions:
  - D010 — WorkEnvelope/OutputEnvelope serialization uses JSON + base64 via stdlib only (no new dependencies)
  - D011 — OutputEnvelope signs request_id + ":" + output (not output alone) for replay protection
  - D012 — MockOverwatchVerifier reads OutputEnvelope.output without signature verification (no session key — correct by design)
patterns_established:
  - Spec-first tests: imports placed inside each test function so pytest --collect-only succeeds before implementation exists
  - Envelope bytes serialization: base64-encoded JSON with d.get(key, default) for all fields (forwards-compat)
  - WorkEnvelope.create generates request_id = os.urandom(16).hex() (32 hex chars) per call — unique per work item
  - TeeDecryptionError wraps cryptography.exceptions.InvalidTag at the envelope boundary — protocol callers never import from cryptography.exceptions directly
  - MockOverwatchVerifier read pattern: OutputEnvelope.from_bytes(raw) → json.loads(output_env.output.decode()) — no sig check
  - Test tamper pattern: parse OutputEnvelope, mutate env.output bytes, store back with original signature → validator fails at sig check; overwatch fails at math check
observability_surfaces:
  - "[MockMiner] published ratls_cert epoch=<n> peer=<prefix>..." — INFO log when cert stored in DHT
  - "[MockMiner] signed output request_id=<id> epoch=<n>" — INFO log on OutputEnvelope creation
  - "[MockValidator] ratls_cert ok epoch=<n> peer=<prefix>... score=<s>" — INFO log on cert verify pass
  - "[MockValidator] no_ratls_cert epoch=<n> peer=<prefix>..." — WARNING on missing cert
  - "[MockValidator] ratls_cert_rejected epoch=<n> peer=<prefix>... reason=<r>" — WARNING on bad cert
  - "[MockValidator] output_signature_invalid epoch=<n> peer=<prefix>..." — WARNING on bad signature
  - "db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))" — inspect cert presence in DHT
  - "OutputEnvelope.from_bytes(db.nmap_get(_WORK_TOPIC, dht_key(epoch, peer_id)))" — inspect signed record
  - "NodeValidatorResult.error" — structured prefix: no_ratls_cert / ratls_cert_rejected:<reason> / output_signature_invalid
  - "TeeDecryptionError message: authentication failed: ciphertext tampered or wrong key" — stable string for log filtering
drill_down_paths:
  - .gsd/milestones/M002/slices/S02/tasks/T01-SUMMARY.md
  - .gsd/milestones/M002/slices/S02/tasks/T02-SUMMARY.md
  - .gsd/milestones/M002/slices/S02/tasks/T03-SUMMARY.md
duration: ~100m (T01: 20m, T02: 10m, T03: 30m + slice close: 40m)
verification_result: passed
completed_at: 2026-03-16
---

# S02: Input Encryption + Output Signing

**WorkEnvelope (AES-GCM) and OutputEnvelope (HMAC-SHA256) wired into MockNodeProtocol — miner signs every work record with the RA-TLS session key; validator verifies cert and signature before accepting result; R014 validated with 16 passing tests and zero regressions.**

## What Happened

S02 built the envelope protocol on top of S01's `RaTlsSession` and wired it into `MockNodeProtocol` in three tasks:

**T01 — Spec-first tests:** Wrote the 16-test acceptance suite in `tests/tee/test_envelope.py` before any implementation existed. Imports from non-existent modules (`subnet.tee.ratls.envelope`, `RATLS_CERT_TOPIC`) are placed inside each test function so `--collect-only` succeeds cleanly. Four test classes: `TestWorkEnvelope` (5), `TestOutputEnvelope` (5), `TestRatlsCertTopic` (2), `TestMockProtocolSignedOutput` (4). One test (`test_dht_key_format`) passed immediately, confirming the existing `dht_key()` function — expected and correct.

**T02 — Implementation:** Created `subnet/tee/ratls/envelope.py` (~140 lines) with `TeeDecryptionError`, `WorkEnvelope`, and `OutputEnvelope`. Added `RATLS_CERT_TOPIC = "ratls_cert"` to `subnet/tee/quote.py`. Updated `subnet/tee/ratls/__init__.py` to export the three new symbols. All 12 non-integration envelope tests passed; 32 RA-TLS tests unaffected.

**T03 — Integration wiring:** Updated `subnet/node/mock.py` in three places:
- `miner_loop`: instantiates `RaTlsServer`, publishes `cert_pem` to `RATLS_CERT_TOPIC` DHT key, derives session, creates `OutputEnvelope.create(request_id, json.dumps(record).encode(), session)`, stores `output_env.to_bytes()` in `_WORK_TOPIC`
- `validator_call`: fetches cert, verifies via `RaTlsClient`, derives session, fetches work record, parses `OutputEnvelope.from_bytes(raw)`, verifies signature — three structured error codes on failure
- `MockOverwatchVerifier.verify`: unpacks `OutputEnvelope.from_bytes(raw)`, reads `.output` directly (no sig check — overwatch has no session key)

Updated `tests/test_mock_node.py` to unpack `OutputEnvelope` before JSON parsing throughout. Renamed `test_validator_rejects_tampered_parity` → `test_validator_rejects_tampered_record_as_invalid_signature`. Resolved pre-existing merge conflict in `REQUIREMENTS.md`.

## Verification

```bash
# Primary slice verification
python3 -m pytest tests/tee/test_envelope.py -v
# → 16/16 PASSED

# RA-TLS regression check
python3 -m pytest tests/tee/test_ratls.py -v
# → 32/32 PASSED

# Full suite (excludes hypertensor/test_rpc.py — pre-existing live-node dependency)
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → 173/173 PASSED
```

## Requirements Advanced

- R013 — Enclave-to-enclave encrypted channels: WorkEnvelope proves that work items can be encrypted to the session key derived from the RA-TLS cert; decryption outside the enclave (wrong key or tampered ciphertext) raises TeeDecryptionError

## Requirements Validated

- R014 — Signed outputs: OutputEnvelope HMAC-SHA256 signs every miner output bound to `request_id`; validator verifies before accepting; tampered output detected with `score=0.0` and `error="output_signature_invalid"`; proven by `TestMockProtocolSignedOutput` and `TestOutputEnvelope::test_replay_protection`

## New Requirements Surfaced

- None discovered during this slice.

## Requirements Invalidated or Re-scoped

- None.

## Deviations

**test_validator_rejects_missing_work updated differently than planned.** The task plan stated the existing test only needed minor updates, but the original test called `miner._publisher.publish(EPOCH)` without mining — so the validator would short-circuit at `no_ratls_cert` before reaching `no_work_record`. The fix: call `await mine(miner)` first then `db.nmap_set(_WORK_TOPIC, key, None)`. This ensures cert is present and validator reaches the correct check path.

**REQUIREMENTS.md merge conflict resolved.** A `HEAD` vs `gsd/M002/S01` conflict existed in `REQUIREMENTS.md` from a prior merge. Resolved by keeping HEAD content for all sections, updating R014 to `validated *(M002/S02)*`.

## Known Limitations

- `WorkEnvelope` is implemented and tested but not yet used by `MockNodeProtocol` for validator→miner encrypted work dispatch. The mock uses a deterministic `request_id` (`f"mock:{epoch}:{peer_id[:8]}"`) rather than a validator-generated nonce from a `WorkEnvelope`. The real encrypted dispatch would require a bidirectional call pattern — deferred until a live transport layer exists (M004+).
- `RaTlsClient` allocates a temp `RocksDB` on every `verify_cert` call (D007). Acceptable at epoch cadence; flag for caching before high-frequency production use.
- `RATLS_CERT_TOPIC` cert published as raw bytes to DHT — no expiry or revocation mechanism. Stale certs from prior epochs are not actively cleaned up; epoch-scoped DHT key naturally expires as validators only fetch current-epoch keys.

## Follow-ups

- S03: Sealed storage — independent of S02; can start immediately
- S04: Gramine manifest — ties S01–S03; after S03 completes
- When a live transport (M004+) is added: wire `WorkEnvelope` for validator→miner encrypted work dispatch, replacing the deterministic mock `request_id` with a validator-generated nonce

## Files Created/Modified

- `subnet/tee/ratls/envelope.py` — new module: WorkEnvelope, OutputEnvelope, TeeDecryptionError
- `subnet/tee/quote.py` — added RATLS_CERT_TOPIC = "ratls_cert"
- `subnet/tee/ratls/__init__.py` — added WorkEnvelope, OutputEnvelope, TeeDecryptionError to exports and __all__
- `subnet/node/mock.py` — miner_loop + validator_call + MockOverwatchVerifier wired for S02 protocol
- `tests/tee/test_envelope.py` — new file: 16-test acceptance suite
- `tests/test_mock_node.py` — updated for OutputEnvelope DHT format; tamper test renamed
- `.gsd/REQUIREMENTS.md` — R014 status updated to validated *(M002/S02)*; merge conflict resolved

## Forward Intelligence

### What the next slice should know
- S03 (sealed storage) is fully independent — it touches `subnet/tee/sealed.py` and `tests/tee/test_sealed.py` only. No changes to `mock.py`, `envelope.py`, or the RA-TLS stack are needed.
- S04 (Gramine manifest) is the integration cap — it should read S01+S02+S03 summaries before writing the manifest to understand what paths, env vars, and syscalls are needed.
- `RATLS_CERT_TOPIC` is the canonical DHT key for cert lookup — all future cert fetch/publish must use this constant (already exported from `subnet.tee.quote`).

### What's fragile
- `MockOverwatchVerifier` assumes the DHT work record is always an `OutputEnvelope` — if `_WORK_TOPIC` ever stores a non-envelope payload (e.g. raw JSON from a pre-S02 node), `OutputEnvelope.from_bytes()` will raise a `KeyError` or `json.JSONDecodeError`. There is no version discriminator in the wire format.
- `TeeDecryptionError` catches `cryptography.exceptions.InvalidTag` only. Any other decryption error (wrong padding, truncated ciphertext) will propagate as an unhandled exception. Acceptable for mock; real implementation may need broader try/except.

### Authoritative diagnostics
- `NodeValidatorResult.error` — primary failure signal; three structured prefixes (`no_ratls_cert`, `ratls_cert_rejected:<reason>`, `output_signature_invalid`); grep for these in logs to locate failures fast
- `python3 -m pytest tests/tee/test_envelope.py -v` — canonical S02 health check; 16/16 green = S02 contract intact
- `db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))` — confirms cert presence; `None` means miner hasn't published for this epoch

### What assumptions changed
- Original plan assumed `WorkEnvelope` would be used for encrypted validator→miner dispatch in this slice. Actual: `WorkEnvelope` is implemented and unit-tested but not wired into `MockNodeProtocol` dispatch. The mock has no bidirectional call pattern yet. The envelope is ready; the transport integration waits for M004.
- Original plan said "different `request_id` → `verify()` returns False" for replay protection. Verified: the replay test (`test_replay_protection`) constructs a new `OutputEnvelope` with a different `request_id` using the same session and signature bytes, confirms `verify()` returns `False`. Protection is structural — the signed payload includes `request_id` so reuse fails cryptographically.
