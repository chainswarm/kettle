# Phase 8: TEE-Attested Gateway - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the x402 frontier TEE-aware:
1. /attestation endpoint returning gateway's TEE quote (agents verify before paying)
2. RA-TLS forwarding from x402 frontier to inference nodes
3. Gateway measurement publishable on-chain for independent verification

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
- Add /attestation GET endpoint to the x402 frontier FastAPI app
- Return the gateway's own TeeQuote (backend auto-detected from TEE_BACKEND env)
- RA-TLS client for forwarding inference requests to nodes (reuse subnet/tee/ratls/client.py)
- On-chain measurement: publish gateway's measurement hash to Hypertensor chain (or expose via API for now)
- Use existing SevSnpAzureBackend/TdxBackend/MockBackend — same pattern as nodes

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `subnet/tee/backends/` — all TEE backends (mock, tdx, sev_snp, sev_snp_azure)
- `subnet/tee/publisher.py` — TeePublisher generates and stores quotes
- `subnet/tee/ratls/client.py` — RaTlsClient for verified connections to nodes
- `subnet/tee/ratls/server.py` — RaTlsServer pattern
- `subnet/tee/quote.py` — TeeQuote with hardware_id, tcb_version fields
- `subnet/x402/` — the x402 frontier from Phase 7

### Integration Points
- Add /attestation to subnet/x402/ FastAPI app
- RA-TLS client wraps inference forwarding (replace direct HTTP)
- TEE backend initialized at startup (same as nodes)

</code_context>

<specifics>
## Specific Ideas

The unique value: agents can cryptographically verify the gateway is honest before sending money. No other x402 service offers this.

</specifics>

<deferred>
## Deferred Ideas

None

</deferred>
