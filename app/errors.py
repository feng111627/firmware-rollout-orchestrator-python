"""领域错误定义。

所有对外暴露的错误都继承自 :class:`RolloutError`，调用方只需要面对
语义清晰的领域错误，底层异常在服务层被包装，不直接透传。
"""

from __future__ import annotations


class RolloutError(Exception):
    """所有固件发布相关错误的基类。"""


class FirmwareNotFoundError(RolloutError):
    """目标固件版本不存在。"""


class ModelUnsupportedError(RolloutError):
    """设备型号不在该固件的支持列表中。"""


class VersionGapTooLargeError(RolloutError):
    """源版本与目标版本跨度超过固件允许的最大跨度。"""


class DeviceUnknownError(RolloutError):
    """上报的设备不存在。"""


class RolloutNotFoundError(RolloutError):
    """发布单不存在。"""


class RolloutStateError(RolloutError):
    """发布单当前状态不允许执行该操作（例如已暂停后还推进批次）。"""


class StaleReportError(RolloutError):
    """上报乱序：收到了比设备当前游标更旧的上报序号。"""
