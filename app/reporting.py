"""设备上报与心跳的幂等处理。

上报携带单调递增的 ``seq`` 序号，服务端为每台设备记录已处理的最大序号：

* ``seq < last_seq``        -> 乱序旧报文，抛 :class:`StaleReportError`
* ``seq == last_seq``       -> 重复报文，原样返回上次结论（dedup，不重复计数）
* ``seq > last_seq``        -> 正常处理并推进游标
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.engine import RolloutEngine
from app.errors import (
    DeviceUnknownError,
    RolloutError,
    RolloutNotFoundError,
    StaleReportError,
)
from app.models import ReportType, Rollout
from app.storage import InMemoryStore

logger = logging.getLogger("rollout.reporting")


@dataclass(frozen=True)
class ReportResult:
    """一次上报的处理结论。"""

    accepted: bool
    duplicate: bool
    rollback_triggered: bool
    rollout_status: str
    message: str


class ReportService:
    def __init__(self, store: InMemoryStore, engine: RolloutEngine) -> None:
        self._store = store
        self._engine = engine

    def handle_report(
        self,
        device_id: str,
        report_type: ReportType,
        seq: int,
        rollout_id: str | None = None,
    ) -> ReportResult:
        """处理一条设备上报，任何底层异常都被转译为可区分的领域错误。"""
        raise NotImplementedError
