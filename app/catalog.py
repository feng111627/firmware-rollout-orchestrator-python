"""固件目录：固件元数据注册与发布准入（兼容性）判定。"""

from __future__ import annotations

import logging

from app.models import Firmware
from app.errors import (
    FirmwareNotFoundError,
    ModelUnsupportedError,
    VersionGapTooLargeError,
)
from app.versions import version_gap

logger = logging.getLogger("rollout.catalog")


class FirmwareCatalog:
    """内存固件注册表。"""

    def __init__(self) -> None:
        self._firmwares: dict[str, Firmware] = {}

    def register(self, firmware: Firmware) -> None:
        """注册一个固件版本（重复注册同一版本将覆盖旧记录）。"""
        self._firmwares[firmware.version] = firmware
        logger.info("已注册固件 %s，支持型号=%s", firmware.version,
                    sorted(firmware.supported_models))

    def get(self, version: str) -> Firmware:
        """按版本号取固件，不存在抛 :class:`FirmwareNotFoundError`。"""
        try:
            return self._firmwares[version]
        except KeyError:
            raise FirmwareNotFoundError(f"目标固件版本不存在: {version}") from None

    def check_admission(
        self, model: str, source_version: str, target_version: str
    ) -> Firmware:
        """发布准入判定。

        判定顺序固定，便于给出可区分、可解释的原因：

        1. 目标版本不存在 -> :class:`FirmwareNotFoundError`
        2. 型号不支持     -> :class:`ModelUnsupportedError`
        3. 版本跨度过大   -> :class:`VersionGapTooLargeError`

        返回固件元数据即表示准入通过。
        """
        # 1) 目标版本是否存在
        firmware = self.get(target_version)

        # 2) 型号是否在支持列表
        if model not in firmware.supported_models:
            raise ModelUnsupportedError(
                f"型号 {model} 不支持固件 {target_version}，"
                f"支持的型号: {sorted(firmware.supported_models)}"
            )

        # 3) 源版本是否达到最低可升级版本，且跨度不超限
        gap = version_gap(source_version, target_version)
        # 源版本低于最低源版本（同线补丁号比较）也视为跨度过大的一种，
        # 但先按 max_version_gap 这一显式规则判定，保持错误原因单一。
        if gap < 0:
            raise VersionGapTooLargeError(
                f"设备当前版本 {source_version} 高于目标版本 {target_version}，"
                "不允许降级"
            )
        if gap > firmware.max_version_gap:
            raise VersionGapTooLargeError(
                f"版本跨度过大: {source_version} -> {target_version}，"
                f"实际跨度 {gap}，允许最大跨度 {firmware.max_version_gap}，"
                f"要求源版本不低于 {firmware.min_source_version}"
            )
        return firmware

    def is_compatible(
        self, model: str, source_version: str, target_version: str
    ) -> bool:
        """准入判定的布尔视图，内部复用 :meth:`check_admission`。"""
        try:
            self.check_admission(model, source_version, target_version)
        except (FirmwareNotFoundError, ModelUnsupportedError,
                VersionGapTooLargeError):
            return False
        return True
