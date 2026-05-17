"""Tests for subnet.x402.config — environment-driven configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

from subnet.x402.config import X402Config


class TestX402Config:
    """Tests for X402Config loading and validation."""

    def test_defaults(self):
        config = X402Config()
        assert config.enabled is False
        assert config.receiver_address == ""
        assert config.facilitator_url == "https://x402.org/facilitator"
        assert config.network == "base-sepolia"
        assert config.scheme == "upto"
        assert config.max_timeout_seconds == 60

    def test_from_env(self):
        env = {
            "X402_ENABLED": "true",
            "X402_RECEIVER_ADDRESS": "0xMyWallet",
            "X402_ASSET_ADDRESS": "0xUSDC",
            "X402_NETWORK": "base",
            "X402_MAX_AMOUNT_REQUIRED": "5000",
            "X402_FACILITATOR_URL": "https://custom-facilitator.example.com",
            "X402_CDP_API_KEY_ID": "my-key-id",
            "X402_CDP_API_KEY_SECRET": "my-secret",
        }
        with patch.dict(os.environ, env, clear=False):
            config = X402Config()
        assert config.enabled is True
        assert config.receiver_address == "0xMyWallet"
        assert config.asset_address == "0xUSDC"
        assert config.network == "base"
        assert config.max_amount_required == "5000"
        assert config.cdp_api_key_id == "my-key-id"

    def test_is_configured_false_when_disabled(self):
        config = X402Config(
            enabled=False,
            receiver_address="0xWallet",
            asset_address="0xToken",
        )
        assert config.is_configured() is False

    def test_is_configured_false_when_missing_receiver(self):
        config = X402Config(enabled=True, asset_address="0xToken")
        assert config.is_configured() is False

    def test_is_configured_false_when_missing_asset(self):
        config = X402Config(enabled=True, receiver_address="0xWallet")
        assert config.is_configured() is False

    def test_is_configured_true(self):
        config = X402Config(
            enabled=True,
            receiver_address="0xWallet",
            asset_address="0xToken",
        )
        assert config.is_configured() is True
