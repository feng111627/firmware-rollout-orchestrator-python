"""应用装配：把存储、固件目录、引擎、上报服务组装到一起。"""

from __future__ import annotations

from app.catalog import FirmwareCatalog
from app.engine import RolloutEngine
from app.reporting import ReportService
from app.storage import InMemoryStore


def build_services(seed: bool = True):
    """构造并返回 (catalog, store, engine, report_service)。

    seed=True 时写入一批本地模拟固件与设备，便于直接启动演示。
    """
    raise NotImplementedError
