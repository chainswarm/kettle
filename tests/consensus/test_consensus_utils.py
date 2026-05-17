"""Tests for consensus utility functions."""
import pytest
from subnet.consensus.utils import compare_consensus_data, get_attestation_ratio
from subnet.hypertensor.chain_data import SubnetNodeConsensusData


class TestGetAttestationRatio:
    def test_empty_subnet_nodes_returns_zero(self):
        """F-24: should not raise ZeroDivisionError."""
        class FakeData:
            attests = []
            subnet_nodes = []
        assert get_attestation_ratio(FakeData()) == 0.0

    def test_normal_ratio(self):
        class FakeData:
            attests = [1, 2]
            subnet_nodes = [1, 2, 3, 4]
        assert get_attestation_ratio(FakeData()) == 0.5


class TestCompareConsensusData:
    def test_identical_data_returns_1(self):
        a = [SubnetNodeConsensusData(subnet_node_id=1, score=100)]
        b = [SubnetNodeConsensusData(subnet_node_id=1, score=100)]
        assert compare_consensus_data(a, b) == 1.0

    def test_empty_lists_returns_100(self):
        assert compare_consensus_data([], []) == 100.0

    def test_different_scores_returns_less_than_1(self):
        a = [SubnetNodeConsensusData(subnet_node_id=1, score=100)]
        b = [SubnetNodeConsensusData(subnet_node_id=1, score=200)]
        result = compare_consensus_data(a, b)
        assert result < 1.0


class TestCompareConsensusDataSemantics:
    """F-09: comparison should handle score differences correctly."""

    def test_same_node_different_score_is_mismatch(self):
        a = [SubnetNodeConsensusData(subnet_node_id=1, score=int(5e17))]
        b = [SubnetNodeConsensusData(subnet_node_id=1, score=int(5e17) + 1)]
        result = compare_consensus_data(a, b)
        assert result < 1.0

    def test_order_independent(self):
        a = [
            SubnetNodeConsensusData(subnet_node_id=1, score=100),
            SubnetNodeConsensusData(subnet_node_id=2, score=200),
        ]
        b = [
            SubnetNodeConsensusData(subnet_node_id=2, score=200),
            SubnetNodeConsensusData(subnet_node_id=1, score=100),
        ]
        assert compare_consensus_data(a, b) == 1.0
