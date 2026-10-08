"""线程安全的内存数据存储，模拟设备侧数据。"""

from __future__ import annotations

import threading

from app.models import Device, Rollout


class InMemoryStore:
    """集中保存设备与发布单，服务层通过它读写，不直接持有可变状态。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, Device] = {}
        self._rollouts: dict[str, Rollout] = {}

    # ---- 设备 ----
    def add_device(self, device: Device) -> None:
        raise NotImplementedError

    def get_device(self, device_id: str) -> Device:
        """不存在时抛 KeyError，由服务层转成 DeviceUnknownError。"""
        raise NotImplementedError

    def list_devices(self) -> list[Device]:
        raise NotImplementedError

    # ---- 发布单 ----
    def add_rollout(self, rollout: Rollout) -> None:
        raise NotImplementedError

    def get_rollout(self, rollout_id: str) -> Rollout:
        """不存在时抛 KeyError，由服务层转成 RolloutNotFoundError。"""
        raise NotImplementedError

    def list_rollouts(self) -> list[Rollout]:
        raise NotImplementedError

    @property
    def lock(self) -> threading.RLock:
        """服务层在需要跨对象原子推进时持有的锁。"""
        return self._lock
