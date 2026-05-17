"""Capacity table for frontier router.

Tracks which peers serve which models, their current load, and p95 latency.
Provides least-loaded routing, stale-entry eviction, and overload detection.
Thread-safe via a single threading.Lock (accessed from both heartbeat handler
and HTTP request handler).
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NodeEntry:
    """A single peer/model entry in the capacity table."""

    peer_id: str
    model: str
    load: float          # 0.0–1.0
    latency_p95: float   # milliseconds
    last_seen: float = field(default_factory=time.monotonic)


class CapacityTable:
    """In-memory routing table built from node heartbeats.

    Parameters
    ----------
    staleness_threshold:
        Seconds after which a node entry is considered stale and eligible for
        eviction via :meth:`evict_stale`.  Default is 6.0 s (enough to survive
        one missed heartbeat at the 5 s heartbeat interval).
    """

    def __init__(self, staleness_threshold: float = 6.0) -> None:
        self._threshold = staleness_threshold
        # Primary index: peer_id -> NodeEntry
        self._entries: dict[str, NodeEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update(
        self,
        peer_id: str,
        *,
        model: str,
        load: float,
        latency_p95: float,
    ) -> None:
        """Add or update the entry for *peer_id*.

        All keyword arguments are required to avoid accidental partial updates.
        """
        entry = NodeEntry(
            peer_id=peer_id,
            model=model,
            load=load,
            latency_p95=latency_p95,
            last_seen=time.monotonic(),
        )
        with self._lock:
            self._entries[peer_id] = entry

    def remove(self, peer_id: str) -> None:
        """Explicitly remove *peer_id* from the table (e.g. on disconnect)."""
        with self._lock:
            self._entries.pop(peer_id, None)

    def evict_stale(self) -> list[str]:
        """Remove all entries not seen within *staleness_threshold* seconds.

        Returns the list of evicted peer_ids.
        """
        now = time.monotonic()
        evicted: list[str] = []
        with self._lock:
            stale = [
                pid
                for pid, entry in self._entries.items()
                if (now - entry.last_seen) > self._threshold
            ]
            for pid in stale:
                del self._entries[pid]
                evicted.append(pid)
        return evicted

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def nodes_for_model(self, model: str) -> list[NodeEntry]:
        """Return all live entries serving *model*."""
        with self._lock:
            return [e for e in self._entries.values() if e.model == model]

    def pick_node(self, model: str) -> Optional[NodeEntry]:
        """Return the least-loaded node for *model*, or ``None`` if none exist."""
        nodes = self.nodes_for_model(model)
        if not nodes:
            return None
        return min(nodes, key=lambda n: n.load)

    def all_models(self) -> set[str]:
        """Return the set of all distinct model names currently in the table."""
        with self._lock:
            return {e.model for e in self._entries.values()}

    def is_overloaded(self, model: str, threshold: float = 0.9) -> bool:
        """Return ``True`` if **every** node serving *model* exceeds *threshold*.

        Returns ``False`` if there are no nodes for *model* (vacuously false —
        an empty pool is not considered overloaded; it is simply unavailable).
        """
        nodes = self.nodes_for_model(model)
        if not nodes:
            return False
        return all(n.load > threshold for n in nodes)
