"""WebSocket bridge from GossipSub/RocksDB to dashboard clients."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# Topics to poll from RocksDB nmaps
POLL_TOPICS = ("heartbeat", "tee_quote", "mock_work")

# Map nmap topic names to WebSocket event types
TOPIC_TO_EVENT_TYPE = {
    "heartbeat": "heartbeat",
    "tee_quote": "tee_quote",
    "mock_work": "work_record",
}


class WebSocketManager:
    """Manages connected WebSocket clients and broadcasts events."""

    def __init__(self) -> None:
        self.connected_clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connected_clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self.connected_clients))

    def disconnect(self, ws: WebSocket) -> None:
        self.connected_clients.discard(ws)
        logger.info("Dashboard client disconnected (%d total)", len(self.connected_clients))

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected clients."""
        if not self.connected_clients:
            return
        payload = json.dumps(message, default=str)
        stale: list[WebSocket] = []
        for ws in self.connected_clients:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.connected_clients.discard(ws)


def create_dashboard_app() -> FastAPI:
    """Create the dashboard FastAPI application with WebSocket bridge and REST endpoints."""
    app = FastAPI(title="TEE Subnet Dashboard API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    manager = WebSocketManager()
    app.state.ws_manager = manager

    # Track which nmap keys we have already seen, keyed by topic
    last_seen_keys: dict[str, set[str]] = {topic: set() for topic in POLL_TOPICS}

    async def _poll_loop() -> None:
        """Background loop that polls RocksDB for new entries and broadcasts them."""
        db = getattr(app.state, "db", None)
        if db is None:
            logger.warning("No RocksDB attached to app state; polling disabled")
            return

        while True:
            try:
                # Catch up with primary DB (secondary instance reads stale data otherwise)
                try:
                    db.store.try_catch_up_with_primary()
                except Exception:
                    pass

                for topic in POLL_TOPICS:
                    entries = db.nmap_get_all(topic)
                    current_keys = set(entries.keys())
                    new_keys = current_keys - last_seen_keys[topic]

                    for key in new_keys:
                        event_type = TOPIC_TO_EVENT_TYPE[topic]
                        data = entries[key]

                        # Normalize data for the WebSocket event
                        event_data = _normalize_event_data(topic, key, data)

                        await manager.broadcast(
                            {
                                "type": event_type,
                                "data": event_data,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )

                    last_seen_keys[topic] = current_keys
            except Exception:
                logger.exception("Error in dashboard poll loop")

            await asyncio.sleep(2)

    @app.on_event("startup")
    async def startup() -> None:
        asyncio.create_task(_poll_loop())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            while True:
                # Keep connection alive; we don't expect client messages
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    # Mount REST endpoints
    from subnet.dashboard.rest_api import create_rest_router

    app.include_router(create_rest_router())

    # Mount Explorer API endpoints
    from subnet.dashboard.explorer.router import create_explorer_router

    app.include_router(create_explorer_router())

    return app


def _normalize_event_data(topic: str, key: str, data: object) -> dict:
    """Normalize raw nmap data into a consistent dict for WebSocket events."""
    # Keys are formatted as "{epoch}:{peer_id}"
    parts = key.split(":", 1)
    epoch_str = parts[0] if len(parts) > 0 else "0"
    peer_id = parts[1] if len(parts) > 1 else "unknown"

    base: dict = {"epoch": int(epoch_str) if epoch_str.isdigit() else 0, "peer_id": peer_id}

    if isinstance(data, dict):
        base.update(data)
    elif hasattr(data, "__dict__"):
        base.update(data.__dict__)
    elif hasattr(data, "model_dump"):
        base.update(data.model_dump())
    else:
        base["raw"] = str(data)

    return base
