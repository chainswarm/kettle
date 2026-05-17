# Phase 7: x402 Payment Middleware - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the x402 payment layer for the inference frontier. FastAPI middleware that:
1. Returns 402 + PAYMENT-REQUIRED header on unpaid requests
2. Parses PAYMENT-SIGNATURE header on retries
3. Verifies payment via Coinbase facilitator /verify endpoint
4. Forwards to inference after verification
5. Settles actual usage via facilitator /settle endpoint (upto scheme)
6. Returns PAYMENT-RESPONSE header with tx hash

Uses upto scheme: agent signs max authorization, server settles for actual token usage.

</domain>

<decisions>
## Implementation Decisions

### Payment Architecture
- Separate FastAPI app (`subnet/x402/`) — not mixed into existing frontier
- x402 middleware wraps the /v1/chat/completions endpoint
- upto scheme only (not exact) — variable pricing per output token
- Coinbase mainnet facilitator at https://api.cdp.coinbase.com/platform/v2/x402

### Pricing Model
- Price table per model in config (e.g., {"llama-3-8b": 0.0001, "llama-3-70b": 0.001} per 1K output tokens)
- Amount in USDC (6 decimals on Base)
- Agent signs max amount, server computes actual after inference, settles for actual

### Protocol Implementation
- Follow x402 v2 spec headers: PAYMENT-REQUIRED, PAYMENT-SIGNATURE, PAYMENT-RESPONSE
- PaymentRequired includes: scheme="upto", network="eip155:8453", asset=USDC address, payTo=owner wallet, maxTimeoutSeconds
- PaymentPayload: base64 JSON with Permit2 signature (handled by @x402/fetch on client side)
- Use httpx to call facilitator /verify and /settle endpoints
- CDP API key auth for facilitator (JWT from cdp-sdk)

### Config
- RECEIVER_ADDRESS: subnet owner wallet (receives USDC)
- CDP_API_KEY_ID + CDP_API_KEY_SECRET: for facilitator auth
- CHAIN_ID: 8453 (Base mainnet) or 84532 (Base Sepolia testnet)
- USDC_ADDRESS: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (Base mainnet)
- PRICE_TABLE: JSON model→price mapping

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `subnet/frontier/app.py` — existing OpenRouter frontier (FastAPI, /v1/chat/completions)
- `subnet/frontier/capacity.py` — CapacityTable for node routing
- `docs/references/x402/specs/schemes/upto/` — upto scheme spec
- `docs/references/gateway/src/` — working x402 integration (TypeScript/Hono, adapt to Python/FastAPI)
- `docs/references/gateway/demo-x402/server.js` — minimal working example

### Established Patterns
- FastAPI apps with Pydantic models
- Environment-based config (TeeConfig pattern)
- httpx for outbound HTTP calls

### Integration Points
- New FastAPI app at subnet/x402/app.py
- Docker Compose service (phase 9)
- Will be wrapped with TEE attestation in phase 8

</code_context>

<specifics>
## Specific Ideas

- Reference the gateway demo-x402/server.js for the flow pattern
- Use httpx (already in deps) for facilitator API calls
- CDP auth: follow the pattern from docs/references/gateway for JWT generation
- The facilitator handles all blockchain interaction — we just call /verify and /settle

</specifics>

<deferred>
## Deferred Ideas

None

</deferred>
