"""本地内存数据存储，模拟设备端上报的数据底座。

所有读写都在同一把锁内完成，保证重复上报/并发上报时
幂等判定与序号推进是原子的。
"""
from __future__ import annotations

import threading

from app.errors import ReportValidationError
from app.models import Device, DeviceReport, Firmware, Release


class InMemoryStore:
    """线程安全的内存存储。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._firmwares: dict[str, Firmware] = {}
        self._devices: dict[str, Device] = {}
        self._releases: dict[str, Release] = {}
        self._seen_reports: dict[str, DeviceReport] = {}
        self._last_seq: dict[str, int] = {}

    @property
    def lock(self) -> threading.RLock:
        """供服务层在一个临界区内组合多次读写。"""
        return self._lock

    # ---- 固件 ----
    def add_firmware(self, firmware: Firmware) -> None:
        with self._lock:
            self._firmwares[firmware.version] = firmware

    def get_firmware(self, version: str) -> Firmware | None:
        with self._lock:
            return self._firmwares.get(version)

    # ---- 设备 ----
    def add_device(self, device: Device) -> None:
        with self._lock:
            self._devices[device.device_id] = device

    def get_device(self, device_id: str) -> Device | None:
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[Device]:
        with self._lock:
            return list(self._devices.values())

    # ---- 发布单 ----
    def add_release(self, release: Release) -> None:
        with self._lock:
            self._releases[release.release_id] = release

    def get_release(self, release_id: str) -> Release | None:
        with self._lock:
            return self._releases.get(release_id)

    # ---- 上报幂等与乱序 ----
    def has_report(self, report_id: str) -> bool:
        with self._lock:
            return report_id in self._seen_reports

    def get_report(self, report_id: str) -> DeviceReport | None:
        with self._lock:
            return self._seen_reports.get(report_id)

    def mark_report(self, report: DeviceReport) -> None:
        with self._lock:
            if not report.report_id:
                raise ReportValidationError("report_id 不能为空")
            self._seen_reports[report.report_id] = report

    def get_last_seq(self, device_id: str) -> int:
        with self._lock:
            return self._last_seq.get(device_id, -1)

    def advance_seq(self, device_id: str, seq: int) -> bool:
        """序号严格前进才记录并返回 True；倒退/重复序号返回 False。"""
        with self._lock:
            if seq <= self._last_seq.get(device_id, -1):
                return False
            self._last_seq[device_id] = seq
            return True
