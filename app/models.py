"""领域模型：设备、固件、发布批次、升级记录。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeviceStatus(str, Enum):
    """设备当前状态。"""

    IDLE = "idle"                     # 空闲，未参与发布
    PENDING = "pending"               # 已纳入批次，等待下发
    UPGRADING = "upgrading"           # 升级中
    SUCCEEDED = "succeeded"           # 升级成功（运行新版本）
    FAILED = "failed"                 # 升级失败（仍为旧版本）
    ROLLING_BACK = "rolling_back"     # 回滚中
    ROLLED_BACK = "rolled_back"       # 已回滚到升级前版本


class ReleaseStatus(str, Enum):
    """发布单状态机。"""

    DRAFT = "draft"                   # 草稿，未开始
    IN_PROGRESS = "in_progress"       # 灰度推进中
    PAUSED = "paused"                 # 失败超阈值，已自动暂停
    ROLLING_BACK = "rolling_back"     # 回滚进行中
    ROLLED_BACK = "rolled_back"       # 已全部回滚
    COMPLETED = "completed"           # 全部批次成功
    CANCELLED = "cancelled"           # 人工取消


class ReportKind(str, Enum):
    """设备上报类型。"""

    UPGRADE_SUCCESS = "upgrade_success"
    UPGRADE_FAILURE = "upgrade_failure"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True)
class Firmware:
    """固件版本。"""

    version: str
    supported_models: frozenset[str]
    min_upgrade_from: str | None = None  # 允许跨版本升级的最低来源版本


@dataclass
class Device:
    """设备。"""

    device_id: str
    model: str
    version: str                        # 当前运行版本
    status: DeviceStatus = DeviceStatus.IDLE
    target_version: str | None = None
    baseline_version: str | None = None  # 升级前版本，回滚目标


@dataclass
class Batch:
    """灰度批次。"""

    batch_id: int
    device_ids: list[str]
    started: bool = False
    finished: bool = False
    success_count: int = 0
    failure_count: int = 0


@dataclass
class Release:
    """灰度发布单。"""

    release_id: str
    firmware: Firmware
    failure_threshold: float            # 失败比例阈值，超过即暂停并回滚
    batches: list[Batch] = field(default_factory=list)
    status: ReleaseStatus = ReleaseStatus.DRAFT
    current_batch: int = -1
    failure_count: int = 0
    success_count: int = 0
    decided_devices: int = 0            # 已上报成功/失败的设备数
    auto_rolled_back: bool = False      # 是否因超阈值触发过自动回滚
    rollback_reason: str | None = None  # 回滚原因（可解释）


@dataclass(frozen=True)
class DeviceReport:
    """设备上报事件。"""

    report_id: str                      # 幂等键
    device_id: str
    release_id: str
    kind: ReportKind
    version: str | None = None          # 上报时设备运行版本
    seq: int = 0                        # 设备端单调序号，用于乱序判定
    timestamp: float = 0.0
