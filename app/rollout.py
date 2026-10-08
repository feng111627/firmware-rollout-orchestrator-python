"""灰度发布编排：准入、批次推进、上报处理、自动暂停与回滚。

关键规则：
- 准入：目标版本不存在 / 型号不支持 / 版本跨度过大 三类错误可区分。
- 推进：发布单按批次严格顺序放量，批次内全部设备有定论后才允许进入下一批。
- 幂等：以 report_id 去重；以设备单调 seq 拒绝乱序倒退；重复/乱序不改变
  任何计数与状态，也不会重复触发回滚。
- 回滚：某批次失败比例超过阈值 -> 自动暂停；回滚只作用于"未升级成功"的
  设备，已成功设备保留新版本，各设备状态与其运行版本严格一致。
"""
from __future__ import annotations


from app.compatibility import check_admission
from app.errors import (
    DeviceNotFoundError,
    DeviceNotInReleaseError,
    DeviceStateError,
    DuplicateReportError,
    ReleaseNotFoundError,
    ReleaseStateError,
    ReleaseValidationError,
    ReportValidationError,
    StaleReportError,
)
from app.models import (
    Batch,
    Device,
    DeviceReport,
    DeviceStatus,
    Firmware,
    Release,
    ReleaseStatus,
    ReportKind,
)
from app.store import InMemoryStore

_TERMINAL_REPORT_STATES = {
    DeviceStatus.SUCCEEDED,
    DeviceStatus.FAILED,
    DeviceStatus.ROLLED_BACK,
}


class RolloutService:
    """灰度发布编排服务。"""

    def __init__(self, store: InMemoryStore | None = None) -> None:
        self.store = store or InMemoryStore()

    # ------------------------------------------------------------------ #
    # 建档
    # ------------------------------------------------------------------ #
    def register_firmware(self, firmware: Firmware) -> None:
        self.store.add_firmware(firmware)

    def register_device(self, device: Device) -> None:
        self.store.add_device(device)

    def create_release(
        self,
        release_id: str,
        target_version: str,
        device_ids: list[str],
        batch_sizes: list[int],
        failure_threshold: float,
    ) -> Release:
        if not 0.0 < failure_threshold <= 1.0:
            raise ReleaseValidationError("failure_threshold 必须在 (0, 1] 区间")
        if not batch_sizes or any(size <= 0 for size in batch_sizes):
            raise ReleaseValidationError("batch_sizes 必须是非空正整数序列")
        firmware = self.store.get_firmware(target_version)
        if firmware is None:
            raise ReleaseValidationError(f"目标固件版本不存在: {target_version}")

        total = sum(batch_sizes)
        if total != len(device_ids):
            raise ReleaseValidationError(
                f"批次设备总数 {total} 与设备清单 {len(device_ids)} 不一致"
            )
        if len(set(device_ids)) != len(device_ids):
            raise ReleaseValidationError("设备清单存在重复设备")

        # 逐设备准入：先收集全部失败，保证建档时一次性暴露所有不兼容设备。
        rejected: list[str] = []
        for device_id in device_ids:
            device = self.store.get_device(device_id)
            if device is None:
                raise DeviceNotFoundError(f"设备不存在: {device_id}")
            try:
                check_admission(device, firmware)
            except Exception as exc:  # 转成可解释的建档失败信息
                rejected.append(f"{device_id}: {exc}")
        if rejected:
            raise ReleaseValidationError(
                "存在不满足升级条件的设备 -> " + "; ".join(rejected)
            )

        batches: list[Batch] = []
        offset = 0
        for index, size in enumerate(batch_sizes):
            batches.append(Batch(batch_id=index, device_ids=device_ids[offset:offset + size]))
            offset += size

        release = Release(
            release_id=release_id,
            firmware=firmware,
            failure_threshold=failure_threshold,
            batches=batches,
        )
        self.store.add_release(release)
        return release

    # ------------------------------------------------------------------ #
    # 批次推进
    # ------------------------------------------------------------------ #
    def advance(self, release_id: str) -> Release:
        """推进到下一批次。

        - DRAFT：启动第 0 批；
        - IN_PROGRESS 且当前批次已全部定论：进入下一批；全部批次完成则完成发布；
        - 其余状态（PAUSED/回滚/终态）一律拒绝。
        """
        with self.store.lock:
            release = self._require_release(release_id)
            status = release.status

            if status in (ReleaseStatus.PAUSED, ReleaseStatus.ROLLING_BACK,
                          ReleaseStatus.ROLLED_BACK, ReleaseStatus.COMPLETED,
                          ReleaseStatus.CANCELLED):
                raise ReleaseStateError(
                    f"发布单状态为 {status.value}，不允许继续推进"
                )

            if status is ReleaseStatus.IN_PROGRESS:
                current = release.batches[release.current_batch]
                decided = current.success_count + current.failure_count
                if decided < len(current.device_ids):
                    raise ReleaseStateError(
                        f"第 {current.batch_id} 批尚有 "
                        f"{len(current.device_ids) - decided} 台设备未上报结果"
                    )
                # 当前批次必然未超阈值（超阈值会在上报时自动暂停），放行。
                if release.current_batch + 1 >= len(release.batches):
                    release.status = ReleaseStatus.COMPLETED
                    return release

            next_index = release.current_batch + 1
            batch = release.batches[next_index]
            batch.started = True
            release.current_batch = next_index
            release.status = ReleaseStatus.IN_PROGRESS

            for device_id in batch.device_ids:
                device = self.store.get_device(device_id)
                assert device is not None  # 建档时已校验
                device.status = DeviceStatus.PENDING
                device.target_version = release.firmware.version
                device.baseline_version = device.version
            return release

    # ------------------------------------------------------------------ #
    # 设备上报
    # ------------------------------------------------------------------ #
    def handle_report(self, report: DeviceReport) -> None:
        """幂等处理一次设备上报。

        处理顺序（每一步都是明确的业务错误，不透传底层异常）：
        1. report_id 重复 -> DuplicateReportError（状态与计数保持不变）
        2. seq 倒退/重复   -> StaleReportError
        3. 发布单/设备/归属/内容/状态校验
        4. 应用事件并更新计数；若批次失败比例超阈值则自动暂停并回滚。
        """
        if report.kind not in tuple(ReportKind):
            raise ReportValidationError(f"未知上报类型: {report.kind!r}")

        with self.store.lock:
            if self.store.has_report(report.report_id):
                raise DuplicateReportError(
                    f"重复上报被忽略: report_id={report.report_id}"
                )
            if not self.store.advance_seq(report.device_id, report.seq):
                raise StaleReportError(
                    f"乱序上报被忽略: device={report.device_id} seq={report.seq} "
                    f"last={self.store.get_last_seq(report.device_id)}"
                )

            release = self._require_release(report.release_id)
            device = self.store.get_device(report.device_id)
            if device is None:
                raise DeviceNotFoundError(f"设备不存在: {report.device_id}")
            if not self._device_in_release(release, report.device_id):
                raise DeviceNotInReleaseError(
                    f"设备 {report.device_id} 不属于发布单 {report.release_id}"
                )
            if release.status not in (ReleaseStatus.IN_PROGRESS,):
                raise ReleaseStateError(
                    f"发布单状态为 {release.status.value}，不接受设备上报"
                )
            batch = release.batches[release.current_batch]
            if report.device_id not in batch.device_ids:
                raise DeviceStateError("该设备不在当前进行中的批次内")

            # 幂等标记与事件应用放在同一临界区：后续重复上报直接被第 1 步挡下。
            self.store.mark_report(report)

            if report.kind is ReportKind.HEARTBEAT:
                # 心跳只做活性确认；PENDING -> UPGRADING 表示设备已开始动作。
                if device.status is DeviceStatus.PENDING:
                    device.status = DeviceStatus.UPGRADING
                return

            if device.status in _TERMINAL_REPORT_STATES:
                # 成功/失败已定论的设备，新的成功/失败上报不允许覆盖结论。
                raise DeviceStateError(
                    f"设备状态 {device.status.value} 已有最终结论，拒绝重复定论"
                )

            if report.kind is ReportKind.UPGRADE_SUCCESS:
                if report.version not in (None, release.firmware.version):
                    raise ReportValidationError(
                        f"成功上报版本 {report.version} 与目标版本 "
                        f"{release.firmware.version} 不一致"
                    )
                self._apply_success(release, batch, device)
            elif report.kind is ReportKind.UPGRADE_FAILURE:
                self._apply_failure(release, batch, device)

            self._maybe_auto_pause_and_rollback(release, batch)

    # ------------------------------------------------------------------ #
    # 回滚
    # ------------------------------------------------------------------ #
    def rollback(self, release_id: str) -> Release:
        """把尚未升级成功的设备回滚到各自基线版本。

        - 已 SUCCEEDED 的设备保留新版本，绝不回滚；
        - PENDING / UPGRADING / FAILED 的设备回到 baseline_version 并置
          ROLLED_BACK；ROLLING_BACK 是中间态，同样收敛为 ROLLED_BACK；
        - 操作可重复调用（幂等），已 ROLLED_BACK 的设备不受影响。
        """
        with self.store.lock:
            release = self._require_release(release_id)
            if release.status in (ReleaseStatus.COMPLETED, ReleaseStatus.CANCELLED):
                raise ReleaseStateError(
                    f"发布单状态为 {release.status.value}，无需/不可回滚"
                )
            release.status = ReleaseStatus.ROLLING_BACK
            for batch in release.batches:
                if not batch.started:
                    continue
                for device_id in batch.device_ids:
                    device = self.store.get_device(device_id)
                    assert device is not None
                    if device.status is DeviceStatus.SUCCEEDED:
                        continue  # 已成功设备不参与回滚
                    if device.status is DeviceStatus.ROLLED_BACK:
                        continue  # 幂等
                    if device.baseline_version is not None:
                        device.version = device.baseline_version
                    device.target_version = None
                    device.status = DeviceStatus.ROLLED_BACK
            release.status = ReleaseStatus.ROLLED_BACK
            return release

    # ------------------------------------------------------------------ #
    # 查询辅助
    # ------------------------------------------------------------------ #
    def get_device_state(self, device_id: str) -> DeviceStatus:
        device = self.store.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(f"设备不存在: {device_id}")
        return device.status

    def get_release(self, release_id: str) -> Release:
        release = self.store.get_release(release_id)
        if release is None:
            raise ReleaseNotFoundError(f"发布单不存在: {release_id}")
        return release

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #
    def _require_release(self, release_id: str) -> Release:
        release = self.store.get_release(release_id)
        if release is None:
            raise ReleaseNotFoundError(f"发布单不存在: {release_id}")
        return release

    @staticmethod
    def _device_in_release(release: Release, device_id: str) -> bool:
        return any(device_id in batch.device_ids for batch in release.batches)

    @staticmethod
    def _apply_success(release: Release, batch: Batch, device: Device) -> None:
        device.status = DeviceStatus.SUCCEEDED
        device.version = release.firmware.version
        device.target_version = None
        batch.success_count += 1
        release.success_count += 1
        release.decided_devices += 1
        if batch.success_count + batch.failure_count == len(batch.device_ids):
            batch.finished = True

    @staticmethod
    def _apply_failure(release: Release, batch: Batch, device: Device) -> None:
        # 失败设备仍运行升级前版本（本地模拟：设备端未刷写成功）。
        if device.baseline_version is not None:
            device.version = device.baseline_version
        device.status = DeviceStatus.FAILED
        device.target_version = None
        batch.failure_count += 1
        release.failure_count += 1
        release.decided_devices += 1
        if batch.success_count + batch.failure_count == len(batch.device_ids):
            batch.finished = True

    def _maybe_auto_pause_and_rollback(self, release: Release, batch: Batch) -> None:
        decided = batch.success_count + batch.failure_count
        if decided == 0:
            return
        ratio = batch.failure_count / len(batch.device_ids)
        if ratio > release.failure_threshold:
            reason = (
                f"第 {batch.batch_id} 批失败比例 {ratio:.0%} 超过阈值 "
                f"{release.failure_threshold:.0%}，自动暂停并回滚"
            )
            release.status = ReleaseStatus.PAUSED
            release.rollback_reason = reason
            self.rollback(release.release_id)
            release.auto_rolled_back = True
