"""版本兼容判定与发布准入。

判定顺序（对调用方可区分）：
1. 目标固件不存在      -> TargetVersionNotFoundError
2. 设备型号不被支持    -> ModelNotSupportedError
3. 来源版本跨度过大    -> VersionGapError
"""
from __future__ import annotations

import re

from app.errors import (
    ModelNotSupportedError,
    TargetVersionNotFoundError,
    VersionGapError,
)
from app.models import Device, Firmware

_NUMERIC_PREFIX = re.compile(r"^(\d+(?:\.\d+)*)")


def parse_version(value: str) -> tuple[int, ...]:
    """把 ``1.2.3`` 形式的版本解析为可比较的非负整数元组。

    取首个数字点分段（忽略 ``-rc1``、``+build`` 等后缀）；
    无法解析时抛出 ValueError，由上层转成业务错误，不直接透传。
    """
    if not isinstance(value, str):
        raise ValueError(f"版本必须是字符串: {value!r}")
    match = _NUMERIC_PREFIX.match(value.strip())
    if match is None:
        raise ValueError(f"无法解析的版本号: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def is_version_compatible(device_version: str, firmware: Firmware) -> bool:
    """仅做版本跨度判定（不含型号）。

    固件声明了 ``min_upgrade_from`` 时，设备当前版本必须不低于该版本，
    即不允许跨过大版本直接升级；未声明则只要求目标版本高于当前版本以外
    不设限（升级到更低版本由发布流程另行约束，这里放行）。
    """
    if firmware.min_upgrade_from is None:
        return True
    return parse_version(device_version) >= parse_version(firmware.min_upgrade_from)


def check_admission(device: Device, firmware: Firmware | None) -> None:
    """发布准入：通过返回 None，不通过抛出带 ``code`` 的业务错误。"""
    if firmware is None:
        raise TargetVersionNotFoundError("目标固件版本不存在")
    if device.model not in firmware.supported_models:
        raise ModelNotSupportedError(
            f"设备型号 {device.model} 不在固件 {firmware.version} 支持列表中"
        )
    try:
        compatible = is_version_compatible(device.version, firmware)
    except ValueError as exc:  # 版本号本身畸形，归类为跨度判定问题
        raise VersionGapError(f"版本号无法比较: {exc}") from exc
    if not compatible:
        raise VersionGapError(
            f"设备当前版本 {device.version} 低于允许升级的最低来源版本 "
            f"{firmware.min_upgrade_from}，版本跨度过大"
        )


__all__ = [
    "ModelNotSupportedError",
    "TargetVersionNotFoundError",
    "VersionGapError",
    "check_admission",
    "is_version_compatible",
    "parse_version",
]
