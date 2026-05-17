# Phase 4: Security Event Indexer - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase)

<domain>
## Phase Boundary

Instrument DcapVerifier, overwatch, and consensus to emit security events into a dedicated RocksDB nmap. Only bad events recorded — valid attestations produce zero writes.

Events to index:
- TEE verification failures (bad measurement, identity binding, chain verification, debug mode)
- Hardware Sybil detections (duplicate CHIP_ID, duplicate GPU UUID)
- CVE-vulnerable firmware rejections (with CVE IDs and TCB details)
- Overwatch tamper detections and slash events
- Scoring anomalies

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — infrastructure phase. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

Key patterns to follow:
- Use RocksDB nmap `security_events` (same pattern as `tee_quote`, `heartbeat`, `mock_work`)
- Key format: `{epoch}:{peer_id}:{event_type}` for queryability
- Store as JSON-serializable dicts
- Emit events at the point of rejection in DcapVerifier, not in callers
- The "good is good, let it go" principle: no writes for successful verifications

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `subnet/tee/verifier.py` — DcapVerifier with all rejection points clearly identified
- `subnet/utils/db/database.py` — RocksDB with nmap_set/nmap_get/nmap_get_all
- `subnet/tee/quote.py` — TEE_QUOTE_TOPIC, dht_key() pattern
- `subnet/node/overwatch.py` — BaseOverwatchVerifier with tamper detection

### Established Patterns
- nmap topics: `tee_quote`, `heartbeat`, `mock_work`, `ratls_cert`
- Key format: `{epoch}:{peer_id}`
- Data stored as bytes (JSON-encoded)

### Integration Points
- DcapVerifier.verify() and verify_quote() — emit on rejection
- _check_hardware_uniqueness() — emit on duplicate detection
- _check_tcb_version() — emit on CVE/TCB rejection
- MockOverwatchVerifier — emit on tamper detection
- ChainOverwatchReporter — emit on slash submission

</code_context>

<specifics>
## Specific Ideas

- "Assume good is good let it go, but we need to record the invalid ones"
- "It looks like our subnet indexer"
- User wants this to feed the block explorer UI in later phases

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>
