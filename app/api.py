"""FastAPI 路由层：把领域错误映射为可区分的 HTTP 响应。

不把底层异常（KeyError、NotImplementedError 等）透给调用方，
未知错误统一收敛为 500 并记录日志。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from app.catalog import FirmwareCatalog
from app.errors import (
    DeviceUnknownError,
    FirmwareNotFoundError,
    ModelUnsupportedError,
    RolloutError,
    RolloutNotFoundError,
    RolloutStateError,
    StaleReportError,
    VersionGapTooLargeError,
)
from app.models import ReportType

logger = logging.getLogger("rollout.api")

router = APIRouter()


# ---- 请求/响应模型（实现阶段补充） ----
class RolloutCreateRequest(BaseModel):
    firmware_version: str
    target_device_ids: list[str] = Field(default_factory=list)
    failure_threshold: float = 0.3
    batch_size: int = 2


class ReportRequest(BaseModel):
    device_id: str
    report_type: ReportType
    seq: int = 0
    rollout_id: str | None = None


def create_app(catalog: FirmwareCatalog | None = None) -> FastAPI:
    """构造 FastAPI 应用，并完成默认数据装配（骨架阶段返回空应用）。"""
    return FastAPI()
