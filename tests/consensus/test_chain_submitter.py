"""Unit tests for ChainScoreSubmitter."""
import logging
from unittest.mock import MagicMock, patch

import pytest

from subnet.consensus.chain_submitter import ChainScoreSubmitter
from subnet.hypertensor.chain_data import SubnetNodeConsensusData


def make_submitter(subnet_id=1):
    hypertensor = MagicMock()
    return ChainScoreSubmitter(hypertensor, subnet_id=subnet_id), hypertensor


class TestChainScoreSubmitter:
    def test_submit_calls_propose_attestation_with_correct_params(self):
        """propose_attestation is called with subnet_id and correctly serialised data."""
        submitter, ht = make_submitter(subnet_id=42)
        scores = [
            SubnetNodeConsensusData(subnet_node_id=1, score=int(1e18)),
            SubnetNodeConsensusData(subnet_node_id=2, score=int(0.5e18)),
        ]
        submitter.submit(scores)
        ht.propose_attestation.assert_called_once_with(
            42,
            data=[
                {"subnet_node_id": 1, "score": int(1e18)},
                {"subnet_node_id": 2, "score": int(0.5e18)},
            ],
        )

    def test_submit_returns_receipt_on_success(self):
        """submit() returns the ExtrinsicReceipt when is_success=True."""
        submitter, ht = make_submitter()
        receipt = MagicMock(is_success=True)
        ht.propose_attestation.return_value = receipt

        result = submitter.submit([SubnetNodeConsensusData(subnet_node_id=3, score=100)])

        assert result is receipt

    def test_submit_empty_list_calls_through(self):
        """submit([]) calls propose_attestation with data=[] — no short-circuit."""
        submitter, ht = make_submitter()
        submitter.submit([])
        ht.propose_attestation.assert_called_once_with(1, data=[])

    def test_submit_logs_error_on_failed_receipt(self, caplog):
        """Failed receipt (is_success=False) is returned (not None) and error is logged."""
        submitter, ht = make_submitter()
        receipt = MagicMock(is_success=False, error_message="BadProof")
        ht.propose_attestation.return_value = receipt

        with caplog.at_level(logging.ERROR, logger="subnet.consensus.chain_submitter"):
            result = submitter.submit([])

        assert result is receipt
        assert any("BadProof" in record.message for record in caplog.records), (
            "Expected error log containing 'BadProof'"
        )

    def test_submit_exception_returns_none(self):
        """Exception from propose_attestation is caught; submit() returns None."""
        submitter, ht = make_submitter()
        ht.propose_attestation.side_effect = Exception("network down")

        result = submitter.submit([SubnetNodeConsensusData(subnet_node_id=5, score=0)])

        assert result is None

    def test_wiring_pattern_two_nodes(self):
        """Score type conversion and subnet_node_id mapping match the server.py wiring pattern."""
        submitter, ht = make_submitter(subnet_id=42)
        receipt = MagicMock(is_success=True)
        ht.propose_attestation.return_value = receipt

        scores = [
            SubnetNodeConsensusData(subnet_node_id=1, score=int(0.5 * 1e18)),
            SubnetNodeConsensusData(subnet_node_id=2, score=int(1.0 * 1e18)),
        ]
        result = submitter.submit(scores)

        ht.propose_attestation.assert_called_once_with(
            42,
            data=[
                {"subnet_node_id": 1, "score": int(0.5e18)},
                {"subnet_node_id": 2, "score": int(1.0e18)},
            ],
        )
        assert result is receipt
