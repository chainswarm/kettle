"""REST API endpoints for the dashboard."""

import logging
import os
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger(__name__)

# Auth token from environment
DASHBOARD_AUTH_TOKEN = os.environ.get("DASHBOARD_AUTH_TOKEN")


def _get_db(request: Request):
    """Get the RocksDB instance from app state."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return db


def _check_admin_auth(request: Request) -> None:
    """Check admin authorization if token is configured."""
    if not DASHBOARD_AUTH_TOKEN:
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth_header[len("Bearer ") :]
    if token != DASHBOARD_AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def create_rest_router() -> APIRouter:
    """Create the REST API router for the dashboard."""
    router = APIRouter(prefix="/api")

    @router.get("/nodes")
    async def get_nodes(request: Request):
        """Return all nodes derived from latest heartbeat data per unique peer_id."""
        db = _get_db(request)
        heartbeats = db.nmap_get_all("heartbeat")

        # Group by peer_id, keep the latest epoch entry
        nodes_by_peer: dict[str, dict] = {}
        max_epoch = 0

        for key, data in heartbeats.items():
            parts = key.split(":", 1)
            epoch_str = parts[0] if len(parts) > 0 else "0"
            peer_id = parts[1] if len(parts) > 1 else "unknown"
            epoch = int(epoch_str) if epoch_str.isdigit() else 0
            max_epoch = max(max_epoch, epoch)

            # Build a normalized heartbeat dict
            hb = _extract_heartbeat(data, epoch, peer_id)

            if peer_id not in nodes_by_peer or hb["epoch"] > nodes_by_peer[peer_id]["epoch"]:
                nodes_by_peer[peer_id] = hb

        # Determine online/offline status
        nodes = []
        for peer_id, hb in nodes_by_peer.items():
            status = "online" if (max_epoch - hb["epoch"]) <= 2 else "offline"
            nodes.append(
                {
                    "peer_id": peer_id,
                    "subnet_node_id": hb.get("subnet_node_id", 0),
                    "epoch": hb["epoch"],
                    "tee_score": hb.get("tee_score", 0.0),
                    "gpu": hb.get("gpu"),
                    "gpu_uuid": hb.get("gpu_uuid"),
                    "gpu_attested": hb.get("gpu_attested", False),
                    "models": hb.get("models"),
                    "status": status,
                    "last_seen": hb.get("last_seen", ""),
                    "vram_total_gb": hb.get("vram_total_gb"),
                    "vram_used_gb": hb.get("vram_used_gb"),
                    "requests_in_flight": hb.get("requests_in_flight", 0),
                    "latency_p95_ms": hb.get("latency_p95_ms", 0.0),
                    "nim_version": hb.get("nim_version"),
                }
            )

        return nodes

    @router.get("/nodes/{peer_id}")
    async def get_node_detail(peer_id: str, request: Request):
        """Return detailed node info: latest heartbeat + TEE quote + work record metadata."""
        db = _get_db(request)

        # Find latest heartbeat for this peer
        heartbeats = db.nmap_get_all("heartbeat")
        latest_hb = None
        for key, data in heartbeats.items():
            parts = key.split(":", 1)
            pid = parts[1] if len(parts) > 1 else ""
            if pid == peer_id:
                epoch = int(parts[0]) if parts[0].isdigit() else 0
                hb = _extract_heartbeat(data, epoch, peer_id)
                if latest_hb is None or hb["epoch"] > latest_hb["epoch"]:
                    latest_hb = hb

        if latest_hb is None:
            raise HTTPException(status_code=404, detail=f"Node {peer_id} not found")

        # Find latest TEE quote for this peer
        tee_quotes = db.nmap_get_all("tee_quote")
        latest_quote = None
        for key, data in tee_quotes.items():
            parts = key.split(":", 1)
            pid = parts[1] if len(parts) > 1 else ""
            if pid == peer_id:
                epoch = int(parts[0]) if parts[0].isdigit() else 0
                quote_data = _extract_dict(data)
                quote_data["epoch"] = epoch
                if latest_quote is None or epoch > latest_quote.get("epoch", 0):
                    latest_quote = quote_data

        # Find latest work record for this peer
        work_records = db.nmap_get_all("mock_work")
        latest_work = None
        for key, data in work_records.items():
            parts = key.split(":", 1)
            pid = parts[1] if len(parts) > 1 else ""
            if pid == peer_id:
                epoch = int(parts[0]) if parts[0].isdigit() else 0
                work_data = _extract_dict(data)
                work_data["epoch"] = epoch
                if latest_work is None or epoch > latest_work.get("epoch", 0):
                    latest_work = work_data

        return {
            "heartbeat": latest_hb,
            "tee_quote": latest_quote,
            "work_record": latest_work,
        }

    @router.get("/events")
    async def get_events(
        request: Request,
        topic: str = Query(default="heartbeat"),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        """Return recent events from a given topic nmap, newest first."""
        db = _get_db(request)

        valid_topics = ("heartbeat", "tee_quote", "mock_work")
        if topic not in valid_topics:
            raise HTTPException(status_code=400, detail=f"Invalid topic. Must be one of: {valid_topics}")

        entries = db.nmap_get_all(topic)

        events = []
        for key, data in entries.items():
            parts = key.split(":", 1)
            epoch = int(parts[0]) if parts[0].isdigit() else 0
            peer_id = parts[1] if len(parts) > 1 else "unknown"
            event_data = _extract_dict(data)
            event_data["epoch"] = epoch
            event_data["peer_id"] = peer_id
            event_data["type"] = topic  # Inject topic as event type
            events.append({"key": key, "epoch": epoch, "peer_id": peer_id, "data": event_data})

        # Sort by epoch descending
        events.sort(key=lambda e: e["epoch"], reverse=True)
        return events[:limit]

    @router.get("/topology")
    async def get_topology(request: Request):
        """Return topology data derived from shared-epoch heartbeat analysis."""
        db = _get_db(request)
        heartbeats = db.nmap_get_all("heartbeat")

        # Group peers by epoch
        epoch_peers: dict[int, set[str]] = defaultdict(set)
        peer_info: dict[str, dict] = {}
        max_epoch = 0

        for key, data in heartbeats.items():
            parts = key.split(":", 1)
            epoch = int(parts[0]) if parts[0].isdigit() else 0
            peer_id = parts[1] if len(parts) > 1 else "unknown"
            max_epoch = max(max_epoch, epoch)
            epoch_peers[epoch].add(peer_id)

            hb = _extract_heartbeat(data, epoch, peer_id)
            if peer_id not in peer_info or hb["epoch"] > peer_info[peer_id].get("epoch", 0):
                peer_info[peer_id] = hb

        # Build nodes list
        nodes = []
        for peer_id, hb in peer_info.items():
            status = "online" if (max_epoch - hb["epoch"]) <= 2 else "offline"
            nodes.append(
                {
                    "peer_id": peer_id,
                    "subnet_node_id": hb.get("subnet_node_id", 0),
                    "status": status,
                }
            )

        # Build edges: peers sharing an epoch are connected
        edges_set: set[tuple[str, str]] = set()
        for epoch, peers in epoch_peers.items():
            peers_list = sorted(peers)
            for i in range(len(peers_list)):
                for j in range(i + 1, len(peers_list)):
                    edge = (peers_list[i], peers_list[j])
                    edges_set.add(edge)

        edges = [{"from": e[0], "to": e[1]} for e in sorted(edges_set)]

        return {"nodes": nodes, "edges": edges}

    @router.get("/overwatch")
    async def get_overwatch(request: Request):
        """Return overwatch-related data from work records."""
        db = _get_db(request)
        work_records = db.nmap_get_all("mock_work")

        overwatch_events = []
        for key, data in work_records.items():
            parts = key.split(":", 1)
            epoch = int(parts[0]) if parts[0].isdigit() else 0
            peer_id = parts[1] if len(parts) > 1 else "unknown"

            work_data = _extract_dict(data)

            # Detect tampered or suspicious entries
            tampered = work_data.get("tampered", False)
            parity_ok = work_data.get("parity_ok", True)

            if tampered:
                result = "tampered"
                details = "Work record flagged as tampered"
            elif not parity_ok:
                result = "fail"
                details = "Parity mismatch detected"
            else:
                result = "pass"
                details = "Audit passed"

            overwatch_events.append(
                {
                    "epoch": epoch,
                    "peer_id": peer_id,
                    "result": result,
                    "details": details,
                    "data": work_data,
                }
            )

        overwatch_events.sort(key=lambda e: e["epoch"], reverse=True)
        return overwatch_events

    @router.get("/admin/db-stats")
    async def get_db_stats(request: Request):
        """Return nmap names and entry counts. Requires admin auth."""
        _check_admin_auth(request)
        db = _get_db(request)

        # Scan for all nmap names and their entry counts
        nmap_counts: dict[str, int] = defaultdict(int)
        prefix = f"nmap{db.SEPARATOR}"

        for key in db.store.keys():
            if isinstance(key, str) and key.startswith(prefix):
                remaining = key[len(prefix) :]
                if db.SEPARATOR in remaining:
                    nmap_name = remaining.split(db.SEPARATOR)[0]
                    nmap_counts[nmap_name] += 1

        return {
            "nmaps": [{"name": name, "count": count} for name, count in sorted(nmap_counts.items())],
            "total_entries": sum(nmap_counts.values()),
        }

    return router


def _extract_heartbeat(data: object, epoch: int, peer_id: str) -> dict:
    """Extract heartbeat fields from raw nmap data."""
    d = _extract_dict(data)
    d.setdefault("epoch", epoch)
    d.setdefault("peer_id", peer_id)
    return d


def _extract_dict(data: object) -> dict:
    """Convert various data formats to a plain dict."""
    if isinstance(data, dict):
        return dict(data)
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "__dict__"):
        return dict(data.__dict__)
    # Try parsing as JSON string (heartbeats stored as serialized JSON in RocksDB)
    import json
    raw = str(data)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return {"raw": raw}
