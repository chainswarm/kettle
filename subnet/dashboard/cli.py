"""CLI entry point for the dashboard API server."""

import os
import sys
import time


def _log(msg: str) -> None:
    print(msg, flush=True)


def cli() -> None:
    """Run the dashboard WebSocket bridge + REST API server."""
    db_path = os.environ.get("DASHBOARD_DB_PATH", "/tmp/bootstrap")
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "8100"))

    _log(f"Starting TEE Subnet Dashboard API")
    _log(f"Database path: {db_path}")
    _log(f"Server: http://{host}:{port}")
    _log(f"WebSocket: ws://{host}:{port}/ws")
    print()

    from subnet.dashboard.ws_bridge import create_dashboard_app
    from subnet.utils.db.database import RocksDB

    app = create_dashboard_app()

    # Wait for the primary DB to be created by the validator node.
    # On Docker Compose, both start simultaneously so the DB may not exist yet.
    db_store_path = f"{db_path}_store"
    max_wait = 120
    waited = 0
    while not os.path.exists(os.path.join(db_store_path, "CURRENT")):
        if waited >= max_wait:
            _log(f"Warning: Timed out waiting for RocksDB at {db_store_path}")
            print("Dashboard will start without database access")
            break
        if waited % 10 == 0:
            _log(f"Waiting for validator DB at {db_store_path}... ({waited}s)")
        time.sleep(2)
        waited += 2
    else:
        # DB exists — open as secondary instance (can read alongside primary writer)
        try:
            db = RocksDB(base_path=db_path, secondary=True)
            app.state.db = db
            _log(f"RocksDB opened (secondary mode): {db_path}")
        except Exception as e:
            _log(f"Warning: Could not open RocksDB at {db_path}: {e}")
            print("Dashboard will start without database access")

    import uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
