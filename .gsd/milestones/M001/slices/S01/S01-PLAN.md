# S01: Quote schema + identity binding + mock backend + DHT publisher

**Goal:** A miner generates a peer_id+epoch-bound TEE quote via the mock backend and publishes it to the DHT. Replay attacks and stolen quotes are rejected at the schema level.
**Demo:** Unit tests prove: mock quote generated, identity-bound, published to DHT, fetched back, replay rejected, stolen-quote rejected.

## Must-Haves

- `TeeQuote` dataclass with all fields required for later DCAP verification
- `report_data = sha256(peer_id + ":" + epoch)` binding enforced by every backend
- `MockBackend` generates HMAC-signed quotes, verifiable without hardware
- `TeePublisher` writes quote to DHT via `nmap_put("tee_quote", "{epoch}:{peer_id}", ...)`
- Tests covering: generate, publish, fetch, replay rejection, wrong-peer_id rejection

## Proof Level

- This slice proves: contract (unit tests, no running network)
- Real runtime required: no
- Human/UAT required: no

## Verification

- `cd /home/aphex5/work/subnet-template && python -m pytest tests/tee/ -v`
- All tests pass, zero skips

## Tasks

- [ ] **T01: TeeQuote dataclass + serialisation** `est:30m`
- [ ] **T02: TEE config + backend abstraction** `est:20m`
- [ ] **T03: MockBackend — HMAC-signed identity-bound quotes** `est:30m`
- [ ] **T04: TdxBackend + SevSnpBackend stubs** `est:20m`
- [ ] **T05: TeePublisher — epoch quote → DHT** `est:30m`
- [ ] **T06: Tests — all scenarios** `est:45m`

## Files Likely Touched

- `subnet/tee/__init__.py`
- `subnet/tee/config.py`
- `subnet/tee/quote.py`
- `subnet/tee/backends/__init__.py`
- `subnet/tee/backends/mock.py`
- `subnet/tee/backends/tdx.py`
- `subnet/tee/backends/sev_snp.py`
- `subnet/tee/publisher.py`
- `tests/tee/__init__.py`
- `tests/tee/test_quote.py`
- `tests/tee/test_mock_backend.py`
- `tests/tee/test_publisher.py`
