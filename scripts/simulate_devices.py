"""本地设备端上报模拟。

用内存数据模拟一批设备按灰度批次上报心跳 / 成功 / 失败，
并构造重复、乱序、超阈值失败等异常上报，观察发布编排如何得出
稳定可解释的结论。运行：

    uv run python -m scripts.simulate_devices
"""
from __future__ import annotations

import logging

from app.models import Device, DeviceReport, Firmware, ReportKind
from app.rollout import RolloutService

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("simulator")


def run() -> None:
    svc = RolloutService()
    svc.register_firmware(Firmware(
        version="2.0.0", supported_models=frozenset({"MX-100"}),
        min_upgrade_from="1.0.0"))
    for i in range(6):
        svc.register_device(Device(f"d{i}", "MX-100", "1.0.0"))

    # 两批：3 + 3，阈值 0.34（批次内失败超过 1/3 即回滚）
    svc.create_release("rel-1", "2.0.0",
                       ["d0", "d1", "d2", "d3", "d4", "d5"],
                       [3, 3], failure_threshold=0.34)

    logger.info("== 启动第 0 批 ==")
    svc.advance("rel-1")

    def send(device_id: str, kind: ReportKind, seq: int, *,
             rid: str | None = None, version: str | None = None) -> None:
        report = DeviceReport(
            report_id=rid or f"{device_id}-{kind.value}-{seq}",
            device_id=device_id, release_id="rel-1", kind=kind,
            seq=seq, version=version)
        try:
            svc.handle_report(report)
            logger.info("接受: device=%s kind=%s seq=%s", device_id, kind.value, seq)
        except Exception as exc:  # 模拟器只记录，不让异常中断后续异常上报
            logger.warning("拒绝: device=%s kind=%s seq=%s -> [%s] %s",
                           device_id, kind.value, seq,
                           getattr(exc, "code", "error"), exc)

    # 心跳、成功、失败
    send("d0", ReportKind.HEARTBEAT, 1)
    send("d0", ReportKind.UPGRADE_SUCCESS, 2, version="2.0.0")
    send("d1", ReportKind.UPGRADE_SUCCESS, 1, version="2.0.0")
    send("d2", ReportKind.UPGRADE_FAILURE, 1)

    # 异常上报：d0 成功重放（重复 report_id + 乱序 seq）
    send("d0", ReportKind.UPGRADE_SUCCESS, 2, rid="d0-upgrade_success-2",
         version="2.0.0")
    # d2 失败重放，试图重复计数
    send("d2", ReportKind.UPGRADE_FAILURE, 1, rid="d2-replay")

    release = svc.get_release("rel-1")
    logger.info("第0批结论: status=%s success=%d failure=%d reason=%s",
                release.status.value, release.success_count,
                release.failure_count, release.rollback_reason)

    if release.status.value == "in_progress":
        logger.info("== 进入第 1 批 ==")
        svc.advance("rel-1")
        for dev in ("d3", "d4", "d5"):
            send(dev, ReportKind.HEARTBEAT, 1)
        send("d3", ReportKind.UPGRADE_SUCCESS, 2, version="2.0.0")
        send("d4", ReportKind.UPGRADE_FAILURE, 2)
        send("d5", ReportKind.UPGRADE_FAILURE, 2)  # 2/3 失败 -> 超阈值
        release = svc.get_release("rel-1")

    logger.info("最终发布: status=%s auto_rolled_back=%s",
                release.status.value, release.auto_rolled_back)
    for device in sorted(svc.store.list_devices(), key=lambda d: d.device_id):
        logger.info("设备快照 %s: status=%-11s version=%s baseline=%s",
                    device.device_id, device.status.value,
                    device.version, device.baseline_version)


if __name__ == "__main__":
    run()
