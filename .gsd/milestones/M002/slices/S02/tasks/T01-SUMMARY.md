---
id: T01
parent: S02
milestone: M002
provides:
  - tests/tee/test_envelope.py — complete spec-first test suite for envelope protocol and MockNodeProtocol integration
key_files:
  - tests/tee/test_envelope.py
key_decisions:
  - Envelope imports placed inside each test function (not module-level) so pytest can collect all 16 tests cleanly even before implementation exists; each test fails with ImportError/ModuleNotFoundError at run time, not at collection time
patterns_established:
  - Spec-first tests: import missing symbols inside each test function to allow --collect-only to succeed while still failing with ImportError at run time
  - Integration fixtures follow existing mock-node pattern — _make_proto(), _mine(), _validate() async helpers with RocksDB tmp_path
  - test_dht_key_format validates existing dht_key() — passes immediately as expected (tests existing code)
observability_surfaces:
  - "python3 -m pytest tests/tee/test_envelope.py --collect-only — lists all 16 test names; acts as acceptance contract"
  - "python3 -m pytest tests/tee/test_envelope.py -v --maxfail=100 — shows which tests still fail; failure name is self-documenting"
duration: 20m
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T01: Write failing tests for envelope protocol and MockNodeProtocol integration

**Created 16-test spec-first suite in `tests/tee/test_envelope.py` — all collected cleanly, 15 fail with ImportError, 1 passes (existing `dht_key`).**

## What Happened

Wrote the complete test suite for S02 before any implementation exists. The file covers four test classes:

- **TestWorkEnvelope** (5 tests): create/decrypt round-trip, request_id uniqueness, TeeDecryptionError on tampered ciphertext, to_bytes/from_bytes round-trip, extra-field forwards-compat deserialization.
- **TestOutputEnvelope** (5 tests): create/verify valid, tampered output → False, tampered signature → False, replay protection (different request_id with same sig → False), to_bytes/from_bytes round-trip.
- **TestRatlsCertTopic** (2 tests): RATLS_CERT_TOPIC constant value "ratls_cert", dht_key format `{epoch}:{peer_id}`.
- **TestMockProtocolSignedOutput** (4 tests): miner publishes cert_pem + OutputEnvelope; full validator round-trip (success=True, tee_score>0); no cert → error="no_ratls_cert"; corrupted signature → error="output_signature_invalid".

All imports from non-existing modules (`subnet.tee.ratls.envelope`, `RATLS_CERT_TOPIC`) are placed inside each test function so `--collect-only` succeeds with 0 collection errors.

## Verification

```
python3 -m pytest tests/tee/test_envelope.py --collect-only
# → 16 tests collected, no collection errors

python3 -m pytest tests/tee/test_envelope.py -v --maxfail=100
# → 15 FAILED (ModuleNotFoundError / ImportError) — expected
# → 1 PASSED: TestRatlsCertTopic::test_dht_key_format (tests existing dht_key())
# → 0 SyntaxErrors, 0 logic assertion failures in test code

python3 -m pytest tests/tee/test_ratls.py -v
# → 32/32 passed — zero regressions
```

## Diagnostics

- `python3 -m pytest tests/tee/test_envelope.py --collect-only` — lists the acceptance contract; a future agent can confirm all 16 names are present
- `python3 -m pytest tests/tee/test_envelope.py -v --maxfail=100` — after T02+T03, all 16 should pass; failing test names self-document what's incomplete

## Deviations

None. `test_dht_key_format` passes immediately (as expected — it tests existing `dht_key()` from `subnet.tee.quote`). This is correct and not a deviation.

## Known Issues

None. All failures are import-level as intended.

## Files Created/Modified

- `tests/tee/test_envelope.py` — new file; 16 tests across 4 classes defining the S02 acceptance contract
