"""Tests for node join/leave GossipSub messages."""

from subnet.frontier.messages import NodeJoinMessage, NodeLeaveMessage


# ---------------------------------------------------------------------------
# 1. test_join_roundtrip
# ---------------------------------------------------------------------------


def test_join_roundtrip():
    """Serializing a NodeJoinMessage to bytes and back preserves all fields."""
    original = NodeJoinMessage(
        peer_id="Qm1234567890abcdef",
        gpu_type="NVIDIA A100",
        gpu_uuid="GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        assigned_model="nvidia/nemotron-3-8b",
    )
    restored = NodeJoinMessage.from_bytes(original.to_bytes())

    assert restored.peer_id == original.peer_id
    assert restored.gpu_type == original.gpu_type
    assert restored.gpu_uuid == original.gpu_uuid
    assert restored.assigned_model == original.assigned_model
    assert restored.type == original.type


# ---------------------------------------------------------------------------
# 2. test_leave_roundtrip
# ---------------------------------------------------------------------------


def test_leave_roundtrip():
    """Serializing a NodeLeaveMessage to bytes and back preserves all fields."""
    original = NodeLeaveMessage(
        peer_id="Qm1234567890abcdef",
        reason="upgrade",
    )
    restored = NodeLeaveMessage.from_bytes(original.to_bytes())

    assert restored.peer_id == original.peer_id
    assert restored.reason == original.reason
    assert restored.type == original.type


# ---------------------------------------------------------------------------
# 3. test_join_type_field
# ---------------------------------------------------------------------------


def test_join_type_field():
    """NodeJoinMessage must carry type='node_join'."""
    msg = NodeJoinMessage(
        peer_id="peer-abc",
        gpu_type="NVIDIA H100",
        gpu_uuid="GPU-yyyyyyyy",
        assigned_model="meta/llama-3.1-70b",
    )
    assert msg.type == "node_join"

    # Also check the field survives serialization.
    restored = NodeJoinMessage.from_bytes(msg.to_bytes())
    assert restored.type == "node_join"


# ---------------------------------------------------------------------------
# 4. test_leave_default_reason
# ---------------------------------------------------------------------------


def test_leave_default_reason():
    """NodeLeaveMessage should default reason to 'graceful'."""
    msg = NodeLeaveMessage(peer_id="peer-xyz")
    assert msg.reason == "graceful"

    # Default must also survive a roundtrip.
    restored = NodeLeaveMessage.from_bytes(msg.to_bytes())
    assert restored.reason == "graceful"
