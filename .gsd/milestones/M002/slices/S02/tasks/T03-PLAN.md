---
estimated_steps: 6
estimated_files: 4
---

# T03: Wire MockNodeProtocol — miner publishes cert_pem, validator verifies signed output

**Slice:** S02 — Input Encryption + Output Signing
**Milestone:** M002

## Description

Wire `WorkEnvelope`/`OutputEnvelope` and `RaTlsClient` into `MockNodeProtocol` to demonstrate the full S02 protocol in-process. This is the reference implementation that subnet owners follow.

**Miner side** (`miner_loop`):
1. Generate RA-TLS cert (`RaTlsServer`), publish `cert_pem` to `RATLS_CERT_TOPIC` DHT key
2. Derive session from the cert (`server.make_session()`)
3. Sign the work record as an `OutputEnvelope` (bound to a `request_id`) and store it in `_WORK_TOPIC`

**Validator side** (`validator_call`):
1. After existing TEE quote check, fetch `cert_pem` from `RATLS_CERT_TOPIC` — no cert → `score=0.0`, `error="no_ratls_cert"`
2. Verify cert via `RaTlsClient` — invalid cert → `score=0.0`, `error="ratls_cert_rejected:<reason>"`
3. Derive session from verification result
4. Fetch `OutputEnvelope` from `_WORK_TOPIC`, verify signature — bad sig → `score=0.0`, `error="output_signature_invalid"`
5. Extract `n`, `parity` from `output_env.output` for existing parity check

After this task, all `TestMockProtocolSignedOutput` tests pass and R014 is validated.

### The `request_id` in the mock

In the mock, the miner self-generates work (no WorkEnvelope from validator). The `request_id` is deterministic per epoch: `f"mock:{epoch}:{peer_id[:8]}"`. This is sufficient for the mock's purpose — output is signed and epoch-bound. Subnet owners who implement real work routing pass the validator's `request_id` from a `WorkEnvelope` to `OutputEnvelope.create()`.

## Steps

1. Update `MockNodeProtocol.miner_loop` in `subnet/node/mock.py`:
   - Add imports at the top of the module (or inside the method to avoid circular imports if needed): `from subnet.tee.ratls.server import RaTlsServer`, `from subnet.tee.ratls.envelope import OutputEnvelope`, `from subnet.tee.quote import RATLS_CERT_TOPIC`
   - After publishing TEE quote, instantiate `RaTlsServer(peer_id=self.peer_id, epoch=epoch, backend=self._backend)`, access `server.cert_bundle.cert_pem`, and publish it: `self.db.nmap_set(RATLS_CERT_TOPIC, _dht_key(epoch, self.peer_id), cert_pem)`; log INFO: `"[MockMiner] published ratls_cert epoch=%d peer=%s", epoch, self.peer_id[:16]`
   - Call `session = server.make_session()`
   - After building `record` dict (existing code), compute `request_id = f"mock:{epoch}:{self.peer_id[:8]}"`, create `output_env = OutputEnvelope.create(request_id=request_id, output=json.dumps(record).encode(), session=session)`, and store `self.db.nmap_set(_WORK_TOPIC, _dht_key(epoch, self.peer_id), output_env.to_bytes())`; log INFO: `"[MockMiner] signed output request_id=%s epoch=%d", request_id, epoch`
   - Keep `NodeMinerResult` return unchanged (metrics still reference `record` fields directly)

2. Update `MockNodeProtocol.validator_call` in `subnet/node/mock.py`:
   - Add imports: `from subnet.tee.ratls.client import RaTlsClient`, `from subnet.tee.ratls.envelope import OutputEnvelope`, `from subnet.tee.quote import RATLS_CERT_TOPIC`
   - After the existing TEE quote pass check (after the `tee.score == 0.0` guard), fetch the cert: `cert_raw = self.db.nmap_get(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id))`
   - If `cert_raw is None`: log WARNING `"[MockValidator] no_ratls_cert epoch=%d peer=%s", epoch, peer_id[:16]`, return `NodeValidatorResult(peer_id=peer_id, success=False, metrics={"tee_score": 0.0}, error="no_ratls_cert")`
   - Call `ra_result = RaTlsClient(config=self._tee_config).verify_cert(cert_raw, peer_id, epoch)`; if `not ra_result.ok`: log WARNING `"[MockValidator] ratls_cert_rejected epoch=%d peer=%s reason=%s", epoch, peer_id[:16], ra_result.rejection_reason`, return `NodeValidatorResult(success=False, metrics={"tee_score": 0.0}, error=f"ratls_cert_rejected:{ra_result.rejection_reason}")`
   - `session = ra_result.session`; log INFO `"[MockValidator] ratls_cert ok epoch=%d peer=%s score=%.1f", epoch, peer_id[:16], tee.score`
   - Fetch raw work record (existing); if `None`: return existing "no_work_record" result unchanged
   - Parse: `output_env = OutputEnvelope.from_bytes(raw)` instead of `json.loads(raw.decode())`
   - Verify: `if not output_env.verify(session)`: log WARNING `"[MockValidator] output_signature_invalid epoch=%d peer=%s", epoch, peer_id[:16]`, return `NodeValidatorResult(success=False, metrics={"tee_score": tee.score}, error="output_signature_invalid")`
   - Extract: `rec = json.loads(output_env.output.decode())`; continue with existing `n`, `parity` extraction and parity check

3. Run the full envelope test suite to confirm all tests pass. If `TestMockProtocolSignedOutput` tests use a `trio.run` or async setup, ensure the fixture uses `pytest-trio` or wraps the async calls correctly (follow the pattern in the existing mock node tests if they exist, or use `trio.run()` inline in sync test functions).

4. Update `MockOverwatchVerifier.verify()` in `subnet/node/mock.py` to unpack `OutputEnvelope` before reading the work record. The overwatch does NOT verify the signature (it has no session key — that's correct by design), but it must parse `OutputEnvelope.from_bytes(raw)` and read `json.loads(output_env.output.decode())` to get `n`, `parity`, `tee_quote_hash`. The verification logic itself is unchanged — only the unpacking step changes.

5. Update `tests/test_mock_node.py` to handle the new storage format:
   - `TestMiner.test_miner_publishes_work_to_dht`: `raw = db.nmap_get(...)` → `output_env = OutputEnvelope.from_bytes(raw)` → `rec = json.loads(output_env.output.decode())`
   - `TestMiner.test_miner_parity_is_correct`: same unpacking pattern
   - `TestValidator.test_validator_rejects_tampered_parity`: this test tampers with the raw record bytes and expects `"wrong_parity" in result.error`. After S02, tampered record bytes → invalid signature → `error == "output_signature_invalid"` (caught earlier, at signature level — which is stronger protection). Update the assertion to `result.error == "output_signature_invalid"` and rename the test `test_validator_rejects_tampered_record_as_invalid_signature`.
   - `TestOverwatch.test_overwatch_detects_tampered_parity`: tamper now requires accessing the OutputEnvelope's output, modifying parity, and rebuilding a *new* OutputEnvelope (without a valid session key — so the overwatch verifier sees an OutputEnvelope whose output has tampered parity). But since the overwatch doesn't check the signature, it just reads the raw output. Update the test to directly overwrite `output_env.output` bytes in the stored envelope (keep `signature` unchanged — overwatch doesn't check it).
   - `TestOverwatch.test_overwatch_detects_tampered_tee_hash`: same as above.

6. Resolve the `REQUIREMENTS.md` merge conflict and mark R014 validated:
   - In `REQUIREMENTS.md`, find R014. The file has a `<<<<<<< HEAD` / `>>>>>>> gsd/M002/S01` merge conflict. Keep the HEAD content for R014 but update status to `validated (M002/S02)`:
     ```
     ## R014 — Signed outputs
     **Status:** `validated` *(M002/S02)*
     Miner's enclave signs each output with its ephemeral session key (bound to RA-TLS)...
     ```
   - Leave R015 (sealed storage) and R016 (Gramine) with their current status — those are S03/S04 targets.

5. Run the full test suite (`python3 -m pytest tests/ -q`) and confirm all tests pass with zero failures.

## Must-Haves

- [ ] Miner publishes `cert_pem` to `RATLS_CERT_TOPIC` DHT key before publishing work record
- [ ] Miner stores `OutputEnvelope.to_bytes()` in `_WORK_TOPIC` (not raw JSON)
- [ ] Validator returns `error="no_ratls_cert"` with `tee_score=0.0` when cert is absent from DHT
- [ ] Validator returns `error="output_signature_invalid"` with `tee_score>0` when signature fails
- [ ] Validator returns `success=True` and `tee_score>0` when the full flow is correct
- [ ] `MockOverwatchVerifier` updated to unpack `OutputEnvelope.from_bytes(raw)` before reading `n`, `parity`, `tee_quote_hash` — overwatch does NOT verify signature (no session key; correct by design)
- [ ] `tests/test_mock_node.py` updated: all direct `json.loads(raw)` calls on work records replaced with `OutputEnvelope.from_bytes(raw)` + `json.loads(output_env.output.decode())`; `test_validator_rejects_tampered_parity` updated to assert `error == "output_signature_invalid"`
- [ ] R014 status updated to `validated (M002/S02)` in `REQUIREMENTS.md`
- [ ] All tests in `tests/tee/test_envelope.py` pass
- [ ] `tests/tee/test_ratls.py` — 32/32 still pass (no regressions)
- [ ] Full suite (`python3 -m pytest tests/ -q`) — zero failures

## Verification

```bash
# Primary verification
python3 -m pytest tests/tee/test_envelope.py -v

# RA-TLS regression check
python3 -m pytest tests/tee/test_ratls.py -v

# Full suite
python3 -m pytest tests/ -q
```

## Observability Impact

- Signals added/changed:
  - `[MockMiner] published ratls_cert epoch=<n> peer=<prefix>...` — INFO, confirms cert is in DHT
  - `[MockMiner] signed output request_id=<id> epoch=<n>` — INFO, confirms OutputEnvelope created
  - `[MockValidator] ratls_cert ok epoch=<n> peer=<prefix>... score=<s>` — INFO, confirms cert verified
  - `[MockValidator] no_ratls_cert epoch=<n> peer=<prefix>...` — WARNING, triggers on missing cert
  - `[MockValidator] ratls_cert_rejected epoch=<n> peer=<prefix>... reason=<r>` — WARNING, cert invalid
  - `[MockValidator] output_signature_invalid epoch=<n> peer=<prefix>...` — WARNING, sig failed
- How a future agent inspects this:
  - `db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))` — is cert in DHT?
  - `OutputEnvelope.from_bytes(db.nmap_get(_WORK_TOPIC, dht_key(epoch, peer_id)))` — is work record a valid OutputEnvelope?
  - `NodeValidatorResult.error` — structured prefix string identifies failure category
- Failure state exposed:
  - Three distinct `error` strings: `no_ratls_cert`, `ratls_cert_rejected:<reason>`, `output_signature_invalid`
  - Each maps to a specific failure mode; log warnings appear at the corresponding site

## Inputs

- `subnet/node/mock.py` — current `MockNodeProtocol.miner_loop`, `validator_call`, and `MockOverwatchVerifier.verify` implementations
- `subnet/tee/ratls/envelope.py` (from T02) — `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`
- `subnet/tee/ratls/server.py` — `RaTlsServer.cert_bundle.cert_pem`, `RaTlsServer.make_session()`
- `subnet/tee/ratls/client.py` — `RaTlsClient.verify_cert(cert_pem, peer_id, epoch)` → `RaTlsVerificationResult`
- `subnet/tee/quote.py` — `RATLS_CERT_TOPIC` (from T02), `dht_key()`
- `tests/tee/test_envelope.py` (from T01) — `TestMockProtocolSignedOutput` tests that must pass
- `REQUIREMENTS.md` — R014 status needs updating; merge conflict must be resolved

## Expected Output

- `subnet/node/mock.py` — miner_loop (cert publish + OutputEnvelope sign), validator_call (cert fetch + RaTlsClient verify + signature check), MockOverwatchVerifier (OutputEnvelope unpack, no sig check)
- `tests/test_mock_node.py` — all tests updated for new work record format; `test_validator_rejects_tampered_parity` → `test_validator_rejects_tampered_record_as_invalid_signature`
- `REQUIREMENTS.md` — R014 `validated (M002/S02)`
- `tests/tee/test_envelope.py` — all tests passing (all four test classes)
- Full test suite — zero failures
