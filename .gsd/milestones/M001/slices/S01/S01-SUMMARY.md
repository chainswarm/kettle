---
slice: S01
status: complete
commit: 2d2f8fd
tests_added: 52
tests_total: 52
---

# S01 Summary: Quote schema + identity binding + mock backend + DHT publisher

## What was built

- `subnet/tee/quote.py` — `TeeQuote` dataclass: backend, measurement, report_data (64 bytes), nonce (epoch), peer_id, timestamp, debug_mode, tcb_status, sig, raw_bytes. `verify_identity()` catches replay + Sybil. JSON serialisation for DHT.
- `subnet/tee/config.py` — `TeeConfig` from env vars: `MOCK_TEE`, `TEE_BACKEND`, `MOCK_TEE_KEY`, `EXPECTED_MEASUREMENT`, `MIN_TEE_SCORE`, `TCB_POLICY`, `PCCS_URL`
- `subnet/tee/backends/base.py` — `TeeBackendBase` ABC
- `subnet/tee/backends/mock.py` — `MockBackend`: HMAC-SHA256 signed, deterministic, no hardware
- `subnet/tee/backends/tdx.py` — `TdxBackend`: real `/dev/tdx_guest` + `libtdx_attest` ctypes calls, MRTD extraction, debug flag check
- `subnet/tee/backends/sev_snp.py` — `SevSnpBackend`: `/dev/sev-guest` SNP_GET_REPORT ioctl, POLICY.debug bit check
- `subnet/tee/backends/__init__.py` — `get_backend(config)` factory with graceful fallback to MockBackend
- `subnet/tee/publisher.py` — `TeePublisher.publish(epoch)` → `nmap_set("tee_quote", "{epoch}:{peer_id}", quote.to_bytes())`

## Key contract

`report_data = sha256(f"{peer_id}:{epoch}".encode())` zero-padded to 64 bytes. Every backend enforces this. `verify_identity(peer_id, epoch)` is the single call that rejects replay (wrong epoch) and stolen quotes (wrong peer_id).

## Tests

52 unit tests: `tests/tee/test_quote.py`, `tests/tee/test_mock_backend.py`, `tests/tee/test_publisher.py`
