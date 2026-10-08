"""领域模型：枚举与数据结构定义。

本文件只描述数据形状，不包含业务逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeviceStatus(str, Enum):
    """设备在一次发布生命周期中的状态。"""

    IDLE = "idle"                    # 未参与发布
    TARGETED = "targeted"            # 被批次选中，等待升级
    UPGRADING = "upgrading"          # 已下发，升级中
    SUCCESS = "success"              # 升级成功
    FAILED = "failed"                # 升级失败
    ROLLING_BACK = "rolling_back"    # 回滚中
    ROLLED_BACK = "rolled_back"      # 已回滚到升级前版本


class RolloutStatus(str, Enum):
    """发布单整体状态。"""

    PENDING = "pending"        # 已创建，尚未开始
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"          # 触发阈值后自动暂停
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"


class ReportType(str, Enum):
    """设备上报类型。"""

    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLBACK_DONE = "rollback_done"


@dataclass(frozen=True)
class Firmware:
    """固件元数据与准入规则。"""

    version: str
    supported_models: frozenset[str]
    min_source_version: str
    max_version_gap: int


@dataclass
class Device:
    """设备及其在某次发布中的快照。"""

    device_id: str
    model: str
    version: str
    status: DeviceStatus = DeviceStatus.IDLE
    rollout_id: str | None = None
    previous_version: str | None = None
    target_version: str | None = None
    last_seq: int = -1


@dataclass
class Batch:
    """灰度发布中的一个批次。"""

    index: int
    device_ids: list[str]
    started: bool = False
    finished: bool = False
    rolled_back: bool = False
    failure_count: int = 0
    success_count: int = 0


@dataclass
class Rollout:
    """一次灰度发布单。"""

    rollout_id: str
    firmware_version: str
    target_device_ids: list[str]
    failure_threshold: float
    batch_size: int
    status: RolloutStatus = RolloutStatus.PENDING
    batches: list[Batch] = field(default_factory=list)
    current_batch: int = -1
    rolled_back: bool = False
