---
id: T03
parent: S02
milestone: M002
provides:
  - subnet/node/mock.py — miner_loop publishes cert_pem to RATLS_CERT_TOPIC and stores OutputEnvelope; validator_call verifies cert via RaTlsClient and verifies OutputEnvelope signature; MockOverwatchVerifier unpacks OutputEnvelope without sig check
  - tests/test_mock_node.py — all tests updated for OutputEnvelope DHT format; test_validator_rejects_tampered_parity renamed to test_validator_rejects_tampered_record_as_invalid_signature
  - .gsd/REQUIREMENTS.md — R014 status updated to validated (M002/S02); merge conflict resolved (HEAD content kept)
key_files:
  - subnet/node/mock.py
  - tests/test_mock_node.py
  - .gsd/REQUIREMENTS.md
key_decisions:
  - test_validator_rejects_missing_work updated to mine first then delete work record (db.nmap_set to None); this ensures cert is present so validator reaches the no_work_record check rather than short-circuiting at no_ratls_cert
  - REQUIREMENTS.md merge conflict resolved by keeping HEAD content (*(Mxxx)* format) for all sections except R014 which is updated to validated *(M002/S02)*
patterns_established:
  - MockOverwatchVerifier reads OutputEnvelope.from_bytes(raw) then json.loads(output_env.output.decode()) — no signature check; correct by design since overwatch has no session key
  - Test tamper pattern: parse OutputEnvelope, mutate env.output bytes, store back with original signature — validator fails at sig check, overwatch fails at math check
  - request_id for mock is deterministic per epoch/peer: f"mock:{epoch}:{peer_id[:8]}" — sufficient for mock; real implementations use validator-provided request_id from WorkEnvelope
observability_surfaces:
  - "[MockMiner] published ratls_cert epoch=<n> peer=<prefix>..." — INFO log when cert stored in DHT
  - "[MockMiner] signed output request_id=<id> epoch=<n>" — INFO log on OutputEnvelope creation
  - "[MockValidator] ratls_cert ok epoch=<n> peer=<prefix>... score=<s>" — INFO log on cert verify pass
  - "[MockValidator] no_ratls_cert epoch=<n> peer=<prefix>..." — WARNING on missing cert
  - "[MockValidator] ratls_cert_rejected epoch=<n> peer=<prefix>... reason=<r>" — WARNING on bad cert
  - "[MockValidator] output_signature_invalid epoch=<n> peer=<prefix>..." — WARNING on sig failure
  - "db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))" — inspect cert presence
  - "OutputEnvelope.from_bytes(db.nmap_get(_WORK_TOPIC, dht_key(epoch, peer_id)))" — inspect signed record
  - "NodeValidatorResult.error" — structured prefix: no_ratls_cert / ratls_cert_rejected:<reason> / output_signature_invalid
duration: ~30min
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T03: Wire MockNodeProtocol — miner publishes cert_pem, validator verifies signed output

**Wired RaTlsServer, OutputEnvelope, and RaTlsClient into MockNodeProtocol — miner signs work with session key derived from RA-TLS cert; validator verifies cert then signature before accepting result.**

## What Happened

Updated `subnet/node/mock.py` with three changes:

**miner_loop**: After publishing TEE quote, instantiates `RaTlsServer` for the epoch, publishes `cert_pem` to `RATLS_CERT_TOPIC` DHT key, derives `session = server.make_session()`, builds the work record, creates `OutputEnvelope.create(request_id, json.dumps(record).encode(), session)`, and stores `output_env.to_bytes()` in `_WORK_TOPIC`. The `request_id` is `f"mock:{epoch}:{peer_id[:8]}"` — deterministic and epoch-bound. The `NodeMinerResult` return is unchanged (metrics still reference `record` fields directly).

**validator_call**: After the TEE quote pass check, fetches `cert_raw` from `RATLS_CERT_TOPIC`. No cert → `no_ratls_cert` (score=0.0). Calls `RaTlsClient(config=self._tee_config).verify_cert(cert_raw, peer_id, epoch)`. Bad cert → `ratls_cert_rejected:<reason>` (score=0.0). Derives `session = ra_result.session`. Fetches raw work record (None → `no_work_record`). Parses as `OutputEnvelope.from_bytes(raw)`, verifies signature — invalid → `output_signature_invalid`. Extracts `rec = json.loads(output_env.output.decode())` and continues with existing parity check.

**MockOverwatchVerifier.verify**: Unpacks `OutputEnvelope.from_bytes(raw)` then reads `json.loads(output_env.output.decode())`. No signature check — overwatch has no session key (correct by design).

Updated `tests/test_mock_node.py`:
- Imported `OutputEnvelope` at module level
- `test_miner_publishes_work_to_dht` and `test_miner_parity_is_correct`: unpack via `OutputEnvelope.from_bytes` before JSON parsing
- `test_validator_rejects_missing_work`: changed from `miner._publisher.publish(EPOCH)` only → `await mine(miner)` + `db.nmap_set(_WORK_TOPIC, key, None)` so cert is present when validator reaches the work record check
- `test_validator_rejects_tampered_parity` → `test_validator_rejects_tampered_record_as_invalid_signature`: tampers `env.output` bytes (leaving signature unchanged), asserts `error == "output_signature_invalid"`
- Overwatch tamper tests: parse OutputEnvelope, mutate `env.output`, store back; overwatch detects math mismatch without needing session key
- `TestTampering.test_tamper_rate_zero_never_tampers`: unpacks OutputEnvelope before reading parity
- `TestEndToEnd.test_tampered_parity_caught_by_both`: unpacks OutputEnvelope, mutates output, stores back; validator fails at signature, overwatch fails at parity math

Resolved `REQUIREMENTS.md` merge conflict (HEAD content kept for all sections, R014 updated to `validated *(M002/S02)*`).

## Verification

```
# Primary — all 16 envelope tests pass
python3 -m pytest tests/tee/test_envelope.py -v   → 16/16 PASSED

# RA-TLS regression — no regressions
python3 -m pytest tests/tee/test_ratls.py -q      → 32/32 PASSED

# Mock node — all tests pass including renamed test
python3 -m pytest tests/test_mock_node.py -v      → 24/24 PASSED

# Full suite (excluding hypertensor/test_rpc.py — pre-existing collection error, needs live node)
python3 -m pytest tests/ --ignore=tests/hypertensor -q  → 173/173 PASSED
```

`tests/hypertensor/test_rpc.py` CollectionError (ConnectionRefused to port 9944) is pre-existing — confirmed by running the same command on the pre-T03 codebase.

## Diagnostics

Inspect the full S02 protocol state at any epoch/peer_id:
```python
# Is cert in DHT?
cert_raw = db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))
# → None means no_ratls_cert; bytes starting with b"-----BEGIN CERTIFICATE-----" means present

# Is work record a valid OutputEnvelope?
output_env = OutputEnvelope.from_bytes(db.nmap_get(_WORK_TOPIC, dht_key(epoch, peer_id)))
rec = json.loads(output_env.output.decode())
# → rec contains n, parity, tee_quote_hash

# NodeValidatorResult.error structured prefixes:
#   no_ratls_cert — cert missing from DHT
#   ratls_cert_rejected:<reason> — cert failed RaTlsClient verification
#   output_signature_invalid — HMAC signature mismatch (tampered output or wrong session)
#   wrong_parity:n=<n> claimed=<p> — signature valid but parity math wrong (fault injection)
```

## Deviations

**test_validator_rejects_missing_work updated differently than originally planned.** The task plan said "Fetch raw work record (existing); if None: return existing 'no_work_record' result unchanged" implying the `no_work_record` path is reachable. But the original test only called `miner._publisher.publish(EPOCH)` (no cert published), so the validator would short-circuit at `no_ratls_cert` before reaching `no_work_record`. Updated the test to call `await mine(miner)` then `db.nmap_set(_WORK_TOPIC, key, None)` — this ensures cert is present and validator reaches the `no_work_record` check correctly.

## Known Issues

None.

## Files Created/Modified

- `subnet/node/mock.py` — miner_loop + validator_call + MockOverwatchVerifier wired for S02 protocol
- `tests/test_mock_node.py` — all tests updated for OutputEnvelope DHT format; tamper test renamed
- `.gsd/REQUIREMENTS.md` — merge conflict resolved; R014 status updated to `validated *(M002/S02)*`
