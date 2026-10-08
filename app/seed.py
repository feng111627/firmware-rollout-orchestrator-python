"""本地模拟数据：固件版本、设备型号与初始版本。"""

from __future__ import annotations

from app.catalog import FirmwareCatalog
from app.models import Device, Firmware
from app.storage import InMemoryStore


def seed_data(catalog: FirmwareCatalog, store: InMemoryStore) -> None:
    """注册若干固件版本与设备，覆盖兼容/不兼容等典型情形。"""
    raise NotImplementedError
