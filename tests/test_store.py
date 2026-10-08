"""存储层幂等与序号推进测试。"""
from __future__ import annotations

import pytest

from app.errors import ReportValidationError
from app.models import Device, DeviceReport, Firmware, ReportKind
from app.store import InMemoryStore


def make_report(report_id: str = "r1", seq: int = 1) -> DeviceReport:
    return DeviceReport(
        report_id=report_id,
        device_id="d1",
        release_id="rel1",
        kind=ReportKind.HEARTBEAT,
        seq=seq,
    )


def test_firmware_and_device_crud() -> None:
    store = InMemoryStore()
    fw = Firmware(version="2.0.0", supported_models=frozenset({"MX-100"}))
    store.add_firmware(fw)
    assert store.get_firmware("2.0.0") is fw
    assert store.get_firmware("9.9.9") is None
    d = Device(device_id="d1", model="MX-100", version="1.0.0")
    store.add_device(d)
    assert store.get_device("d1") is d
    assert [x.device_id for x in store.list_devices()] == ["d1"]


def test_report_idempotency() -> None:
    store = InMemoryStore()
    assert not store.has_report("r1")
    store.mark_report(make_report())
    assert store.has_report("r1")
    assert store.get_report("r1").seq == 1


def test_mark_report_requires_id() -> None:
    store = InMemoryStore()
    with pytest.raises(ReportValidationError):
        store.mark_report(make_report(report_id=""))


def test_seq_must_strictly_advance() -> None:
    store = InMemoryStore()
    assert store.advance_seq("d1", 1)
    assert store.get_last_seq("d1") == 1
    assert not store.advance_seq("d1", 1)   # 重复序号
    assert not store.advance_seq("d1", 0)   # 乱序倒退
    assert store.advance_seq("d1", 2)
    assert store.get_last_seq("d1") == 2


def test_seq_isolated_per_device() -> None:
    store = InMemoryStore()
    assert store.advance_seq("d1", 5)
    assert store.advance_seq("d2", 1)
