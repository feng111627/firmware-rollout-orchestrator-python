"""业务错误定义：对调用方可区分，不泄漏底层异常。"""
from __future__ import annotations


class OrchestratorError(Exception):
    """所有业务错误的基类。"""

    code: str = "orchestrator_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code


class CompatibilityError(OrchestratorError):
    """准入校验失败基类。"""

    code = "compatibility_error"


class ModelNotSupportedError(CompatibilityError):
    """设备型号不在固件支持列表中。"""

    code = "model_not_supported"


class VersionGapError(CompatibilityError):
    """当前版本低于允许升级的最低来源版本（跨度过大）。"""

    code = "version_gap_too_large"


class TargetVersionNotFoundError(CompatibilityError):
    """目标固件版本不存在。"""

    code = "target_version_not_found"


class ReleaseStateError(OrchestratorError):
    """发布单状态不允许该操作。"""

    code = "release_invalid_state"


class DeviceNotInReleaseError(OrchestratorError):
    """设备不属于该发布单。"""

    code = "device_not_in_release"


class DuplicateReportError(OrchestratorError):
    """重复上报（幂等命中）。"""

    code = "duplicate_report"


class StaleReportError(OrchestratorError):
    """乱序/过期上报（序号倒退）。"""

    code = "stale_report"


class DeviceStateError(OrchestratorError):
    """设备当前状态不接受该上报。"""

    code = "device_invalid_state"


class ReportValidationError(OrchestratorError):
    """上报内容非法。"""

    code = "report_validation_error"


class ReleaseNotFoundError(OrchestratorError):
    """发布单不存在。"""

    code = "release_not_found"


class DeviceNotFoundError(OrchestratorError):
    """设备不存在。"""

    code = "device_not_found"


class ReleaseValidationError(OrchestratorError):
    """发布单参数非法。"""

    code = "release_validation_error"
