"""HTTP 接入层测试：验证错误被翻译成稳定可区分的响应，不透传底层异常。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import Device, Firmware, ReportKind
from app.rollout import RolloutService
from app.api import create_app

FW = Firmware(version="2.0.0", supported_models=frozenset({"MX-100"}),
              min_upgrade_from="1.0.0")


@pytest.fixture()
def client() -> TestClient:
    svc = RolloutService()
    svc.register_firmware(FW)
    for i in range(4):
        svc.register_device(Device(f"d{i}", "MX-100", "1.0.0"))
    return TestClient(create_app(svc))


def create_release(client: TestClient, rel: str = "r1",
                   batches=None, threshold: float = 0.5) -> None:
    resp = client.post("/releases", json={
        "release_id": rel, "target_version": "2.0.0",
        "device_ids": ["d0", "d1", "d2", "d3"],
        "batch_sizes": batches or [2, 2], "failure_threshold": threshold,
    })
    assert resp.status_code == 201, resp.text


def test_health(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_create_release_target_not_found() -> None:
    svc = RolloutService()
    svc.register_device(Device("d0", "MX-100", "1.0.0"))
    c = TestClient(create_app(svc))
    resp = c.post("/releases", json={
        "release_id": "x", "target_version": "9.9.9",
        "device_ids": ["d0"], "batch_sizes": [1], "failure_threshold": 0.5,
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "release_validation_error"


def test_rollout_and_duplicate_report_http(client) -> None:
    create_release(client)
    assert client.post("/releases/r1/advance").json()["current_batch"] == 0

    payload = {
        "report_id": "rep-1", "device_id": "d0", "release_id": "r1",
        "kind": ReportKind.UPGRADE_SUCCESS.value, "version": "2.0.0",
        "seq": 1, "timestamp": 1.0,
    }
    assert client.post("/reports", json=payload).status_code == 202
    dup = client.post("/reports", json=payload)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "duplicate_report"


def test_stale_report_http(client) -> None:
    create_release(client)
    client.post("/releases/r1/advance")
    client.post("/reports", json={
        "report_id": "hb-2", "device_id": "d1", "release_id": "r1",
        "kind": ReportKind.HEARTBEAT.value, "seq": 2})
    resp = client.post("/reports", json={
        "report_id": "hb-1", "device_id": "d1", "release_id": "r1",
        "kind": ReportKind.HEARTBEAT.value, "seq": 1})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "stale_report"


def test_auto_rollback_visible_in_release_view(client) -> None:
    create_release(client, batches=[4], threshold=0.5)
    client.post("/releases/r1/advance")
    client.post("/reports", json={
        "report_id": "s0", "device_id": "d0", "release_id": "r1",
        "kind": "upgrade_success", "version": "2.0.0", "seq": 1})
    for i, dev in enumerate(("d1", "d2", "d3"), start=1):
        client.post("/reports", json={
            "report_id": f"f{i}", "device_id": dev, "release_id": "r1",
            "kind": "upgrade_failure", "seq": 1})
    view = client.get("/releases/r1").json()
    assert view["status"] == "rolled_back"
    assert view["auto_rolled_back"] is True
    assert view["rollback_reason"]


def test_advance_after_rollback_rejected(client) -> None:
    resp = client.post("/releases", json={
        "release_id": "r1", "target_version": "2.0.0",
        "device_ids": ["d0", "d1"], "batch_sizes": [2],
        "failure_threshold": 0.5})
    assert resp.status_code == 201, resp.text
    client.post("/releases/r1/advance")
    for dev in ("d0", "d1"):
        client.post("/reports", json={
            "report_id": f"f-{dev}", "device_id": dev, "release_id": "r1",
            "kind": "upgrade_failure", "seq": 1})
    resp = client.post("/releases/r1/advance")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "release_invalid_state"
