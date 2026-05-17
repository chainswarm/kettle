#!/usr/bin/env python3
"""Example autonomous agent client for the x402 Frontier gateway.

Demonstrates the full x402 payment flow:
  1. Send a chat completion request
  2. Receive 402 Payment Required with pricing
  3. Construct and submit payment
  4. Resend request with X-PAYMENT header
  5. Receive inference result + settlement receipt

Usage:
    python agent_client.py --url http://localhost:8402

Environment variables:
    AGENT_WALLET_ADDRESS  - Agent's wallet address (default: demo address)
    AGENT_TX_HASH         - Pre-authorized transaction hash (default: demo hash)

In production, the agent would use @x402/fetch or an on-chain wallet
SDK to construct real payment transactions. This example uses mock
payment headers for demonstration.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)


DEFAULT_URL = "http://localhost:8402"
DEMO_WALLET = "0xAgentWallet1234567890abcdef1234567890abcdef"
DEMO_TX_HASH = "0xdemotxhash1234567890abcdef1234567890abcdef1234567890abcdef12345678"


def make_chat_request(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 256,
    payment_header: str | None = None,
) -> httpx.Response:
    """Send a chat completion request, optionally with payment."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if payment_header is not None:
        headers["X-PAYMENT"] = payment_header

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    with httpx.Client(timeout=30.0) as client:
        return client.post(f"{base_url}/v1/chat/completions", json=body, headers=headers)


def construct_payment(pricing_response: dict[str, Any], wallet: str, tx_hash: str) -> str:
    """Construct an X-PAYMENT header from a 402 pricing response.

    In production, this would:
    1. Read pricing from the 402 response
    2. Create an on-chain transaction for the required amount
    3. Sign the payment authorization (EIP-712)
    4. Return the payment proof as JSON

    This demo constructs a mock payment header.
    """
    payment = {
        "tx_hash": tx_hash,
        "network": pricing_response.get("acceptedNetworks", ["base-sepolia"])[0],
        "token": pricing_response.get("acceptedTokens", ["USDC"])[0],
        "amount": pricing_response.get("maxAmountRequired", "0"),
        "payer": wallet,
        "signature": "0xdemosignature",
    }
    return json.dumps(payment)


def run_agent(
    base_url: str,
    model: str,
    prompt: str,
    wallet: str,
    tx_hash: str,
) -> None:
    """Run the full x402 agent flow."""
    messages = [{"role": "user", "content": prompt}]

    print(f"\n--- Step 1: Send request to {base_url} ---")
    print(f"Model: {model}")
    print(f"Prompt: {prompt}")

    resp = make_chat_request(base_url, model, messages)

    if resp.status_code == 402:
        print(f"\n--- Step 2: Received 402 Payment Required ---")
        pricing = resp.json()
        print(f"Payment address: {pricing.get('paymentAddress', 'N/A')}")
        print(f"Max amount: {pricing.get('maxAmountRequired', 'N/A')} base units")
        print(f"Networks: {pricing.get('acceptedNetworks', [])}")
        print(f"Tokens: {pricing.get('acceptedTokens', [])}")

        print(f"\n--- Step 3: Construct payment ---")
        payment_header = construct_payment(pricing, wallet, tx_hash)
        print(f"Payment header: {payment_header[:80]}...")

        print(f"\n--- Step 4: Resend with payment ---")
        resp = make_chat_request(base_url, model, messages, payment_header=payment_header)

    print(f"\n--- Result: HTTP {resp.status_code} ---")
    print(f"Body: {json.dumps(resp.json(), indent=2)}")

    # Check for settlement receipt
    receipt = resp.headers.get("x-receipt")
    if receipt:
        print(f"\n--- Settlement Receipt ---")
        receipt_data = json.loads(receipt)
        print(f"Receipt ID: {receipt_data.get('receipt_id', 'N/A')}")
        print(f"Amount charged: {receipt_data.get('amount_charged', 'N/A')}")
        print(f"Status: {receipt_data.get('status', 'N/A')}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="x402 Agent Client Example")
    parser.add_argument("--url", default=DEFAULT_URL, help="x402 frontier URL")
    parser.add_argument("--model", default="nvidia/nemotron-3-49b", help="Model to use")
    parser.add_argument("--prompt", default="Explain TEE attestation in one sentence.", help="Prompt")
    parser.add_argument("--wallet", default=DEMO_WALLET, help="Agent wallet address")
    parser.add_argument("--tx-hash", default=DEMO_TX_HASH, help="Transaction hash")
    args = parser.parse_args()

    run_agent(args.url, args.model, args.prompt, args.wallet, args.tx_hash)


if __name__ == "__main__":
    main()
