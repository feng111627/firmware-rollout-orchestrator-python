"""灰度发布编排引擎：批次推进、阈值判定与自动回滚。

所有状态变更都在存储锁内完成，保证"上报 -> 计数 -> 判定 -> 推进/回滚"
这一串动作对单台设备是原子的。
"""

from __future__ import annotations

import logging
import uuid

from app.catalog import FirmwareCatalog
from app.errors import RolloutStateError, RolloutNotFoundError
from app.models import Batch, DeviceStatus, Rollout, RolloutStatus
from app.storage import InMemoryStore

logger = logging.getLogger("rollout.engine")


class RolloutEngine:
    def __init__(self, store: InMemoryStore, catalog: FirmwareCatalog) -> None:
        self._store = store
        self._catalog = catalog

    # ---- 创建与查询 ----
    def create_rollout(
        self,
        firmware_version: str,
        target_device_ids: list[str],
        failure_threshold: float,
        batch_size: int,
        rollout_id: str | None = None,
    ) -> Rollout:
        """创建发布单并按 batch_size 预切批次；准入在启动时逐设备校验。"""
        raise NotImplementedError

    def start(self, rollout_id: str) -> Rollout:
        """启动发布单：对所有目标设备做准入判定，随后启动第一个批次。

        准入不通过的设备被挡下（标记为 IDLE 且不进入批次），
        并记录拒绝原因；任何一台被挡下都不会让整单崩溃。
        """
        raise NotImplementedError

    # ---- 上报驱动的状态机（供 reporting 服务调用） ----
    def apply_device_result(
        self, rollout_id: str, device_id: str, success: bool
    ) -> Rollout:
        """登记一台设备的升级结果，必要时推进批次或触发自动回滚。

        成功/失败计数与状态翻转在同一把锁内完成，重复调用对同一结果幂等。
        """
        raise NotImplementedError

    def apply_rollback_done(self, rollout_id: str, device_id: str) -> Rollout:
        """设备确认回滚完成，版本恢复为升级前版本。幂等。"""
        raise NotImplementedError

    # ---- 内部步骤（签名先占位，实现阶段逐一填充） ----
    def _start_batch(self, rollout: Rollout, index: int) -> None:
        raise NotImplementedError

    def _maybe_advance(self, rollout: Rollout) -> None:
        """当前批次结束且未越阈值时推进下一批；全部完成则结单。"""
        raise NotImplementedError

    def _trigger_rollback(self, rollout: Rollout, reason: str) -> None:
        """暂停发布并回滚：只动尚未成功的设备，已成功者保留新版本。

        重复触发必须幂等，不能重复计数或重复下发回滚。
        """
        raise NotImplementedError
