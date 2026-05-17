"""GossipSub messages for node join / leave events."""

from __future__ import annotations

from pydantic import BaseModel


class NodeJoinMessage(BaseModel):
    """Broadcast by a node immediately after it joins the cluster."""

    type: str = "node_join"
    peer_id: str
    gpu_type: str
    gpu_uuid: str
    assigned_model: str

    def to_bytes(self) -> bytes:
        """Serialize to UTF-8 JSON bytes for pubsub."""
        return self.model_dump_json().encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "NodeJoinMessage":
        """Deserialize from UTF-8 JSON bytes."""
        return cls.model_validate_json(data)


class NodeLeaveMessage(BaseModel):
    """Broadcast by a node when it is about to leave the cluster."""

    type: str = "node_leave"
    peer_id: str
    reason: str = "graceful"

    def to_bytes(self) -> bytes:
        """Serialize to UTF-8 JSON bytes for pubsub."""
        return self.model_dump_json().encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "NodeLeaveMessage":
        """Deserialize from UTF-8 JSON bytes."""
        return cls.model_validate_json(data)
