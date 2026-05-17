---
created: 2026-03-25T16:42:40.894Z
title: Run x402 inference against mocked inference on 2 CVMs
area: testing
files:
  - subnet/x402/middleware.py
  - subnet/x402/cli.py
  - docker-compose.tee-real.yml
  - docker-compose.tee-remote.yml
---

## Problem

Need to verify end-to-end x402 payment flow works across two Azure CVMs (tee-one westeurope + teetwo northeurope). The cross-CVM libp2p networking is now working (GossipSub propagation confirmed), but x402 inference hasn't been tested in a multi-CVM deployment.

Key questions to answer:
- Can an external agent hit the Frontier gateway on either CVM and get inference?
- Does the x402 402 negotiation → payment → inference → settlement flow work cross-CVM?
- How do the 2 nodes behave when both serve inference behind x402?

## Solution

1. Start both CVMs (tee-one + teetwo)
2. Deploy x402-frontier service on both (already in tee-dev compose, needs adding to tee-real)
3. Send x402 requests to both endpoints
4. Compare responses, verify settlement receipts
5. Test with the example x402 client from examples/
