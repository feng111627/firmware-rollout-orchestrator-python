"""FastAPI 接入层：把业务错误翻译成稳定、可区分的 HTTP 响应。

对外不抛出底层异常，统一返回 {"error": {"code", "message"}} 结构。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.errors import (
    DeviceNotFoundError,
    DeviceNotInReleaseError,
    DeviceStateError,
    DuplicateReportError,
    OrchestratorError,
    ReleaseNotFoundError,
    ReleaseStateError,
    ReleaseValidationError,
    ReportValidationError,
    StaleReportError,
)
from app.models import DeviceReport, ReportKind
from app.rollout import RolloutService

_HTTP_STATUS = {
    # 404：资源不存在
    ReleaseNotFoundError.code: 404,
    DeviceNotFoundError.code: 404,
    # 409：冲突（重复、乱序、状态不允许）
    DuplicateReportError.code: 409,
    StaleReportError.code: 409,
    DeviceStateError.code: 409,
    ReleaseStateError.code: 409,
    DeviceNotInReleaseError.code: 409,
    # 422：准入/参数问题
    "model_not_supported": 422,
    "version_gap_too_large": 422,
    "target_version_not_found": 422,
    ReleaseValidationError.code: 422,
    ReportValidationError.code: 422,
}


class FirmwareIn(BaseModel):
    version: str
    supported_models: list[str]
    min_upgrade_from: str | None = None


class DeviceIn(BaseModel):
    device_id: str
    model: str
    version: str


class ReleaseIn(BaseModel):
    release_id: str
    target_version: str
    device_ids: list[str]
    batch_sizes: list[int]
    failure_threshold: float = Field(gt=0.0, le=1.0)


class ReportIn(BaseModel):
    report_id: str
    device_id: str
    release_id: str
    kind: ReportKind
    version: str | None = None
    seq: int = 0
    timestamp: float = 0.0


def create_app(service: RolloutService | None = None) -> FastAPI:
    """构造 FastAPI 应用，可注入自定义服务（便于测试）。"""
    svc = service or RolloutService()
    app = FastAPI(title="firmware-rollout-orchestrator", version="0.1.0")

    @app.exception_handler(OrchestratorError)
    async def _handle_business_error(_request, exc: OrchestratorError):
        status = _HTTP_STATUS.get(exc.code, 400)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/admin/firmwares", status_code=201)
    def register_firmware(payload: FirmwareIn):
        from app.models import Firmware
        svc.register_firmware(
            Firmware(
                version=payload.version,
                supported_models=frozenset(payload.supported_models),
                min_upgrade_from=payload.min_upgrade_from,
            )
        )
        return {"version": payload.version}

    @app.post("/admin/devices", status_code=201)
    def register_device(payload: DeviceIn):
        from app.models import Device
        svc.register_device(Device(**payload.model_dump()))
        return {"device_id": payload.device_id}

    @app.post("/releases", status_code=201)
    def create_release(payload: ReleaseIn):
        release = svc.create_release(**payload.model_dump())
        return _release_view(release)

    @app.post("/releases/{release_id}/advance", status_code=200)
    def advance(release_id: str):
        return _release_view(svc.advance(release_id))

    @app.post("/releases/{release_id}/rollback", status_code=200)
    def rollback(release_id: str):
        return _release_view(svc.rollback(release_id))

    @app.get("/releases/{release_id}", status_code=200)
    def get_release(release_id: str):
        return _release_view(svc.get_release(release_id))

    @app.post("/reports", status_code=202)
    def submit_report(payload: ReportIn):
        svc.handle_report(DeviceReport(**payload.model_dump()))
        return {"accepted": True}

    return app


def _release_view(release) -> dict:
    return {
        "release_id": release.release_id,
        "target_version": release.firmware.version,
        "status": release.status.value,
        "current_batch": release.current_batch,
        "success_count": release.success_count,
        "failure_count": release.failure_count,
        "decided_devices": release.decided_devices,
        "auto_rolled_back": release.auto_rolled_back,
        "rollback_reason": release.rollback_reason,
        "batches": [
            {
                "batch_id": b.batch_id,
                "size": len(b.device_ids),
                "started": b.started,
                "finished": b.finished,
                "success_count": b.success_count,
                "failure_count": b.failure_count,
            }
            for b in release.batches
        ],
    }


app = create_app()

__all__ = ["create_app", "app"]
