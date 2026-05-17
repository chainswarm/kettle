"""Tests for the Explorer API endpoints."""

import pytest
from fastapi.testclient import TestClient

from subnet.dashboard.ws_bridge import create_dashboard_app


class MockDB:
    """Minimal mock RocksDB that supports nmap_get_all."""

    SEPARATOR = ":"

    def __init__(self):
        self._data: dict[str, dict[str, object]] = {}

    def nmap_set(self, nmap: str, key: str, value: object) -> None:
        self._data.setdefault(nmap, {})[key] = value

    def nmap_get_all(self, nmap: str) -> dict[str, object]:
        return dict(self._data.get(nmap, {}))

    @property
    def store(self):
        """Minimal store mock for admin/db-stats endpoint."""
        return _FakeStore(self._data)


class _FakeStore:
    def __init__(self, data):
        self._data = data

    def keys(self):
        result = []
        for nmap, entries in self._data.items():
            for key in entries:
                result.append(f"nmap:{nmap}:{key}")
        return result

    def try_catch_up_with_primary(self):
        pass


def _make_app_with_data() -> TestClient:
    """Create a test app populated with sample data."""
    app = create_dashboard_app()
    db = MockDB()

    # Heartbeats for epochs 10, 11, 12
    db.nmap_set("heartbeat", "10:peer-aaa", {
        "tee_score": 1.0, "status": "ok", "subnet_node_id": 1,
        "hardware_id": "chip-001",
    })
    db.nmap_set("heartbeat", "11:peer-aaa", {
        "tee_score": 1.0, "status": "ok", "subnet_node_id": 1,
    })
    db.nmap_set("heartbeat", "10:peer-bbb", {
        "tee_score": 0.8, "status": "ok", "subnet_node_id": 2,
    })
    db.nmap_set("heartbeat", "12:peer-ccc", {
        "tee_score": 1.0, "status": "ok", "subnet_node_id": 3,
    })

    # TEE quotes
    db.nmap_set("tee_quote", "10:peer-aaa", {
        "tee_type": "sev-snp", "tee_score": 1.0,
    })
    db.nmap_set("tee_quote", "10:peer-bbb", {
        "tee_type": "sev-snp", "tee_score": 0.5,
    })

    # Work records (overwatch audit data)
    db.nmap_set("mock_work", "10:peer-aaa", {
        "parity_ok": True, "tampered": False, "result": 42,
    })
    db.nmap_set("mock_work", "10:peer-bbb", {
        "parity_ok": False, "tampered": False, "result": 0,
        "parity_hash": "abc", "expected_hash": "def",
    })
    db.nmap_set("mock_work", "11:peer-aaa", {
        "parity_ok": True, "tampered": True, "result": 99,
        "hardware_id": "chip-tampered",
    })

    app.state.db = db
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────
# EXP-01: Query security events with filters
# ─────────────────────────────────────────────────────────────────────


class TestQueryEvents:
    """Tests for GET /api/explorer/events (EXP-01)."""

    def test_get_all_events(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        # 4 heartbeats + 2 tee_quotes + 3 work_records = 9
        assert body["total"] == 9
        assert len(body["items"]) == 9

    def test_filter_by_epoch_range(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={"epoch_min": 11, "epoch_max": 12})
        assert resp.status_code == 200
        body = resp.json()
        # epoch 11: heartbeat(peer-aaa) + work(peer-aaa), epoch 12: heartbeat(peer-ccc)
        assert body["total"] == 3
        for item in body["items"]:
            assert 11 <= item["epoch"] <= 12

    def test_filter_by_peer_id(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={"peer_id": "peer-aaa"})
        assert resp.status_code == 200
        body = resp.json()
        # peer-aaa: 2 heartbeats + 1 tee_quote + 2 work_records = 5
        assert body["total"] == 5
        for item in body["items"]:
            assert item["peer_id"] == "peer-aaa"

    def test_filter_by_event_type(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={"event_type": "tee_quote"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["event_type"] == "tee_quote"

    def test_filter_by_severity(self):
        client = _make_app_with_data()
        # Critical: tampered work record
        resp = client.get("/api/explorer/events", params={"severity": "critical"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["peer_id"] == "peer-aaa"
        assert body["items"][0]["severity"] == "critical"

    def test_filter_by_severity_warning(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={"severity": "warning"})
        assert resp.status_code == 200
        body = resp.json()
        # peer-bbb tee_quote (score 0.5) + peer-bbb work_record (parity_ok=False)
        assert body["total"] == 2

    def test_pagination(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={"limit": 3, "offset": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 3
        assert body["total"] == 9
        assert body["offset"] == 0
        assert body["limit"] == 3

    def test_combined_filters(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/events", params={
            "epoch_min": 10, "epoch_max": 10, "peer_id": "peer-aaa",
            "event_type": "heartbeat",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["epoch"] == 10
        assert body["items"][0]["peer_id"] == "peer-aaa"

    def test_no_db_returns_503(self):
        app = create_dashboard_app()
        client = TestClient(app)
        resp = client.get("/api/explorer/events")
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────
# EXP-02: Epoch history
# ─────────────────────────────────────────────────────────────────────


class TestEpochHistory:
    """Tests for GET /api/explorer/epochs and /api/explorer/epochs/{epoch} (EXP-02)."""

    def test_all_epochs(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs")
        assert resp.status_code == 200
        body = resp.json()
        epochs = body["epochs"]
        # Epochs 10, 11, 12
        assert len(epochs) == 3
        # Sorted descending
        assert epochs[0]["epoch"] == 12
        assert epochs[1]["epoch"] == 11
        assert epochs[2]["epoch"] == 10

    def test_epoch_summary_content(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs")
        body = resp.json()
        # Epoch 10: peer-aaa + peer-bbb = 2 nodes
        epoch_10 = [e for e in body["epochs"] if e["epoch"] == 10][0]
        assert epoch_10["node_count"] == 2
        # heartbeats: 2, tee_quotes: 2, work_records: 2
        assert epoch_10["heartbeat_count"] == 2
        assert epoch_10["tee_quote_count"] == 2
        assert epoch_10["work_record_count"] == 2
        assert epoch_10["event_count"] == 6

    def test_epoch_scores(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs")
        body = resp.json()
        epoch_10 = [e for e in body["epochs"] if e["epoch"] == 10][0]
        assert "peer-aaa" in epoch_10["scores"]
        assert epoch_10["scores"]["peer-aaa"] == 1.0

    def test_epoch_tamper_detected(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs")
        body = resp.json()
        epoch_11 = [e for e in body["epochs"] if e["epoch"] == 11][0]
        # Epoch 11 has tampered work record
        assert epoch_11["tamper_detected"] is True
        epoch_12 = [e for e in body["epochs"] if e["epoch"] == 12][0]
        assert epoch_12["tamper_detected"] is False

    def test_epoch_range_filter(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs", params={"epoch_min": 11})
        body = resp.json()
        assert len(body["epochs"]) == 2
        assert all(e["epoch"] >= 11 for e in body["epochs"])

    def test_single_epoch_detail(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs/10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["epoch"] == 10
        assert body["node_count"] == 2

    def test_single_epoch_not_found(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/epochs/999")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# EXP-03: Node history
# ─────────────────────────────────────────────────────────────────────


class TestNodeHistory:
    """Tests for GET /api/explorer/nodes/{peer_id}/history (EXP-03)."""

    def test_node_history(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/nodes/peer-aaa/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["peer_id"] == "peer-aaa"
        assert body["total"] == 5  # 2 heartbeats + 1 tee_quote + 2 work_records
        for item in body["items"]:
            assert item["peer_id"] == "peer-aaa"

    def test_node_history_sorted_by_epoch_desc(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/nodes/peer-aaa/history")
        body = resp.json()
        epochs = [item["epoch"] for item in body["items"]]
        assert epochs == sorted(epochs, reverse=True)

    def test_node_not_found(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/nodes/nonexistent/history")
        assert resp.status_code == 404

    def test_node_history_pagination(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/nodes/peer-aaa/history", params={"limit": 2})
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5


# ─────────────────────────────────────────────────────────────────────
# EXP-04: Overwatch audit log
# ─────────────────────────────────────────────────────────────────────


class TestAuditLog:
    """Tests for GET /api/explorer/audit (EXP-04)."""

    def test_all_audit_entries(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3  # 3 work records

    def test_audit_result_types(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit")
        body = resp.json()
        results = {item["result"] for item in body["items"]}
        assert "pass" in results
        assert "fail" in results
        assert "tampered" in results

    def test_audit_tamper_evidence(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit")
        body = resp.json()
        tampered = [i for i in body["items"] if i["result"] == "tampered"]
        assert len(tampered) == 1
        assert tampered[0]["evidence"]["tampered"] is True

    def test_audit_parity_evidence(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit")
        body = resp.json()
        failed = [i for i in body["items"] if i["result"] == "fail"]
        assert len(failed) == 1
        assert failed[0]["evidence"]["parity_ok"] is False
        assert "parity_hash" in failed[0]["evidence"]
        assert "expected_hash" in failed[0]["evidence"]

    def test_audit_filter_by_peer(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit", params={"peer_id": "peer-bbb"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["peer_id"] == "peer-bbb"

    def test_audit_filter_by_epoch(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit", params={"epoch_min": 11})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["epoch"] == 11

    def test_audit_sorted_by_epoch_desc(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/audit")
        body = resp.json()
        epochs = [item["epoch"] for item in body["items"]]
        assert epochs == sorted(epochs, reverse=True)


# ─────────────────────────────────────────────────────────────────────
# EXP-05: Search
# ─────────────────────────────────────────────────────────────────────


class TestSearch:
    """Tests for GET /api/explorer/search (EXP-05)."""

    def test_search_by_peer_id(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "peer-bbb"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] > 0
        for item in body["items"]:
            assert item["match_type"] == "peer_id"
            assert item["event"]["peer_id"] == "peer-bbb"

    def test_search_by_epoch(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "12"})
        body = resp.json()
        assert body["total"] > 0
        epoch_matches = [i for i in body["items"] if i["match_type"] == "epoch"]
        assert len(epoch_matches) > 0
        for m in epoch_matches:
            assert m["event"]["epoch"] == 12

    def test_search_by_event_type(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "tee_quote"})
        body = resp.json()
        assert body["total"] > 0
        for item in body["items"]:
            assert item["match_type"] == "event_type"

    def test_search_by_hardware_id(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "chip-001"})
        body = resp.json()
        assert body["total"] > 0
        for item in body["items"]:
            assert item["match_type"] == "hardware_id"

    def test_search_no_results(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "zzz-nonexistent-zzz"})
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_search_pagination(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search", params={"q": "peer", "limit": 2})
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] > 2

    def test_search_requires_query(self):
        client = _make_app_with_data()
        resp = client.get("/api/explorer/search")
        assert resp.status_code == 422  # Missing required param
