"""Unit tests for ChainOverwatchReporter."""
import logging
from unittest.mock import MagicMock

import pytest

from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter


def make_reporter(overwatch_node_id=1, subnet_id=42):
    hypertensor = MagicMock()
    return ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id), hypertensor


class TestChainOverwatchReporter:
    def test_slash_calls_commit_and_reveal(self):
        """commit_overwatch_subnet_weights and reveal_overwatch_subnet_weights are both called."""
        reporter, ht = make_reporter(overwatch_node_id=1, subnet_id=42)
        ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
        ht.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)

        reporter.slash("peer123", epoch=5, evidence=None)

        ht.commit_overwatch_subnet_weights.assert_called_once()
        ht.reveal_overwatch_subnet_weights.assert_called_once()

    def test_slash_returns_reveal_receipt_on_success(self):
        """slash() returns the reveal ExtrinsicReceipt when both calls succeed."""
        reporter, ht = make_reporter()
        commit_receipt = MagicMock(is_success=True)
        reveal_receipt = MagicMock(is_success=True)
        ht.commit_overwatch_subnet_weights.return_value = commit_receipt
        ht.reveal_overwatch_subnet_weights.return_value = reveal_receipt

        result = reporter.slash("peer_abc", epoch=3, evidence=None)

        assert result is reveal_receipt

    def test_slash_returns_commit_receipt_when_commit_fails(self):
        """Failed commit (is_success=False) is returned early — reveal is not called."""
        reporter, ht = make_reporter()
        commit_receipt = MagicMock(is_success=False, error_message="BadCommit")
        ht.commit_overwatch_subnet_weights.return_value = commit_receipt

        result = reporter.slash("peer_xyz", epoch=1, evidence=None)

        assert result is commit_receipt
        ht.reveal_overwatch_subnet_weights.assert_not_called()

    def test_slash_logs_error_on_failed_reveal(self, caplog):
        """Failed reveal receipt is returned and error is logged."""
        reporter, ht = make_reporter()
        ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
        reveal_receipt = MagicMock(is_success=False, error_message="BadReveal")
        ht.reveal_overwatch_subnet_weights.return_value = reveal_receipt

        with caplog.at_level(logging.ERROR, logger="subnet.consensus.chain_overwatch_reporter"):
            result = reporter.slash("peer_def", epoch=2, evidence=None)

        assert result is reveal_receipt
        assert any("BadReveal" in record.message for record in caplog.records)

    def test_slash_exception_returns_none(self):
        """Exception from commit is caught; slash() returns None."""
        reporter, ht = make_reporter()
        ht.commit_overwatch_subnet_weights.side_effect = Exception("network down")

        result = reporter.slash("peer_ghi", epoch=0, evidence=None)

        assert result is None
