"""
Tests for MockDatabase — F-21: WAL mode for concurrent Docker containers.

Covers:
- WAL journal mode is enabled by default
- Two MockDatabase instances pointing to the same file can both write
  without SQLITE_BUSY errors (concurrent access safety)
- Basic CRUD operations still work after WAL enablement
"""

import os
import pytest
import sqlite3

from subnet.hypertensor.mock.mock_db import MockDatabase


@pytest.fixture
def db_path(tmp_path):
    """Return a path to a temporary SQLite DB file (not yet created)."""
    return str(tmp_path / "test_mock_chain.db")


class TestWalMode:
    """F-21: SQLite WAL mode is enabled to prevent SQLITE_BUSY errors."""

    def test_wal_mode_enabled(self, db_path):
        """MockDatabase uses WAL journal mode."""
        db = MockDatabase(db_path=db_path)
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal", f"Expected WAL journal mode, got: {mode}"

    def test_two_instances_same_file_both_write(self, db_path):
        """
        Two MockDatabase instances opening the same file can both write
        without raising OperationalError (SQLITE_BUSY).

        This simulates multiple Docker containers sharing a mock chain DB.
        """
        db1 = MockDatabase(db_path=db_path)
        db2 = MockDatabase(db_path=db_path)

        node1 = {
            "subnet_node_id": 1,
            "coldkey": "cold1",
            "hotkey": "hot1",
            "peer_info": {},
            "bootnode_peer_info": {},
            "client_peer_info": {},
            "delegate_account": "del1",
            "identity": "id1",
            "classification": {},
            "delegate_reward_rate": 0,
            "last_delegate_reward_rate_update": 0,
            "unique": "u1",
            "non_unique": "nu1",
        }
        node2 = {
            "subnet_node_id": 2,
            "coldkey": "cold2",
            "hotkey": "hot2",
            "peer_info": {},
            "bootnode_peer_info": {},
            "client_peer_info": {},
            "delegate_account": "del2",
            "identity": "id2",
            "classification": {},
            "delegate_reward_rate": 0,
            "last_delegate_reward_rate_update": 0,
            "unique": "u2",
            "non_unique": "nu2",
        }

        # Both instances write without error
        db1.insert_subnet_node(subnet_id=1, node_info=node1)
        db2.insert_subnet_node(subnet_id=1, node_info=node2)

        # Both records are visible from either connection
        rows1 = db1.get_all_subnet_nodes(subnet_id=1)
        rows2 = db2.get_all_subnet_nodes(subnet_id=1)

        node_ids1 = {r["subnet_node_id"] for r in rows1}
        node_ids2 = {r["subnet_node_id"] for r in rows2}

        assert 1 in node_ids1
        assert 2 in node_ids1
        assert node_ids1 == node_ids2

    def test_consensus_data_roundtrip(self, db_path):
        """WAL mode does not break basic consensus data insert/get."""
        db = MockDatabase(db_path=db_path)
        data = {
            "validator_id": 7,
            "validator_epoch_progress": 1,
            "attests": [],
            "subnet_nodes": [],
            "prioritize_queue_node_id": None,
            "remove_queue_node_id": None,
            "data": [],
            "args": None,
        }
        db.insert_consensus_data(subnet_id=1, epoch=100, data=data)
        fetched = db.get_consensus_data(subnet_id=1, epoch=100)
        assert fetched is not None
        assert fetched["validator_id"] == 7
