"""灰度发布主链路测试：推进 / 自动回滚 / 重复与乱序上报。"""
from __future__ import annotations

import logging

import pytest

from app.errors import (
    DeviceStateError,
    DuplicateReportError,
    ReleaseNotFoundError,
    ReleaseStateError,
    ReleaseValidationError,
    StaleReportError,
)
from app.models import (
    Device,
    DeviceReport,
    DeviceStatus,
    Firmware,
    ReleaseStatus,
    ReportKind,
)
from app.rollout import RolloutService

logger = logging.getLogger("rollout-tests")

FW = Firmware(
    version="2.0.0",
    supported_models=frozenset({"MX-100"}),
    min_upgrade_from="1.0.0",
)


def build_service(
    versions: dict[str, str] | None = None,
    *,
    batch_sizes: list[int] | None = None,
    threshold: float = 0.5,
) -> tuple[RolloutService, str]:
    """构造一个 4 设备、两批(2+2)的标准发布环境。"""
    versions = versions or {}
    svc = RolloutService()
    svc.register_firmware(FW)
    for idx in range(4):
        dev_id = f"d{idx}"
        svc.register_device(
            Device(device_id=dev_id, model="MX-100",
                   version=versions.get(dev_id, "1.0.0"))
        )
    release = svc.create_release(
        release_id="rel",
        target_version="2.0.0",
        device_ids=["d0", "d1", "d2", "d3"],
        batch_sizes=batch_sizes or [2, 2],
        failure_threshold=threshold,
    )
    return svc, release.release_id


def report(device_id: str, kind: ReportKind, seq: int,
           report_id: str | None = None, release_id: str = "rel",
           version: str | None = None) -> DeviceReport:
    return DeviceReport(
        report_id=report_id or f"{device_id}-{kind.value}-{seq}",
        device_id=device_id, release_id=release_id, kind=kind,
        seq=seq, version=version, timestamp=float(seq),
    )


def success(device_id: str, seq: int = 1, **kw) -> DeviceReport:
    return report(device_id, ReportKind.UPGRADE_SUCCESS, seq,
                  version="2.0.0", **kw)


def failure(device_id: str, seq: int = 1, **kw) -> DeviceReport:
    return report(device_id, ReportKind.UPGRADE_FAILURE, seq, **kw)


# --------------------------------------------------------------------- #
# 场景一：灰度按批次逐步放量
# --------------------------------------------------------------------- #
def test_gradual_rollout_batch_by_batch(caplog) -> None:
    """场景1：批次严格顺序推进，未上报完不允许进入下一批。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service()

    rel = svc.advance(rel_id)
    assert rel.status is ReleaseStatus.IN_PROGRESS
    assert rel.current_batch == 0
    logger.info("场景1 启动第0批: %s", rel.batches[0].device_ids)

    with pytest.raises(ReleaseStateError):
        svc.advance(rel_id)  # 第0批未定论，不能进入第1批
    logger.info("场景1 第0批未完成时推进被拒绝: OK")

    svc.handle_report(success("d0", 1))
    svc.handle_report(success("d1", 1))
    assert svc.get_device_state("d0") is DeviceStatus.SUCCEEDED

    rel = svc.advance(rel_id)  # 第0批完成，进入第1批
    assert rel.current_batch == 1
    logger.info("场景1 第0批全部成功，进入第1批")

    svc.handle_report(success("d2", 1))
    svc.handle_report(success("d3", 1))
    rel = svc.advance(rel_id)  # 全部批次完成
    assert rel.status is ReleaseStatus.COMPLETED
    for dev_id in ("d0", "d1", "d2", "d3"):
        assert svc.store.get_device(dev_id).version == "2.0.0"
    logger.info("场景1 全部设备升级到2.0.0，发布完成: OK")


# --------------------------------------------------------------------- #
# 场景二：失败超阈值 -> 自动暂停并回滚
# --------------------------------------------------------------------- #
def test_failure_threshold_triggers_rollback(caplog) -> None:
    """场景2：批次失败比例超阈值自动暂停回滚，已成功设备保留新版本。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    # 单批 4 台，阈值 0.5：失败 > 2 台即自动回滚
    svc = RolloutService()
    svc.register_firmware(FW)
    for idx in range(4):
        svc.register_device(Device(f"d{idx}", "MX-100", "1.0.0"))
    rel_id = "rel"
    svc.create_release(rel_id, "2.0.0", ["d0", "d1", "d2", "d3"], [4], 0.5)
    svc.advance(rel_id)

    svc.handle_report(success("d0", 1))       # 成功
    svc.handle_report(failure("d1", 1))       # 失败 1/4
    rel = svc.get_release(rel_id)
    assert rel.status is ReleaseStatus.IN_PROGRESS
    logger.info("场景2 1台成功1台失败时发布继续: ratio=%.2f", 1 / 4)

    svc.handle_report(failure("d2", 1))       # 失败 2/4 = 0.5，未超阈值
    assert svc.get_release(rel_id).status is ReleaseStatus.IN_PROGRESS
    logger.info("场景2 失败比例等于阈值不触发: ratio=%.2f", 2 / 4)

    svc.handle_report(failure("d3", 1))       # 失败 3/4 = 0.75 > 0.5
    rel = svc.get_release(rel_id)
    assert rel.status is ReleaseStatus.ROLLED_BACK
    assert rel.auto_rolled_back is True
    assert "超过阈值" in (rel.rollback_reason or "")
    logger.info("场景2 失败比例%.2f超阈值，自动暂停并回滚: %s", 3 / 4,
                rel.rollback_reason)

    states = {d.device_id: (d.status, d.version)
              for d in svc.store.list_devices()}
    logger.info("场景2 回滚后设备快照: %s", states)
    # 已成功的 d0 保留新版本，不被回滚
    assert states["d0"] == (DeviceStatus.SUCCEEDED, "2.0.0")
    # 失败设备回到基线版本并标记 ROLLED_BACK
    for dev_id in ("d1", "d2", "d3"):
        assert states[dev_id] == (DeviceStatus.ROLLED_BACK, "1.0.0")


def test_rollback_keeps_succeeded_when_pending_exists(caplog) -> None:
    """场景2b：回滚时未开始(PENDING)的设备也要回到基线，且状态一致。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service(threshold=0.5)
    svc.advance(rel_id)  # 第0批 d0 d1
    svc.handle_report(success("d0", 1))
    svc.handle_report(failure("d1", 1))
    svc.advance(rel_id)  # 第1批 d2 d3 进入 PENDING

    # 第1批第1台失败即 1/2 = 0.5 不触发；第2台失败 1.0 触发
    svc.handle_report(failure("d2", 1))
    svc.handle_report(failure("d3", 1))
    rel = svc.get_release(rel_id)
    assert rel.status is ReleaseStatus.ROLLED_BACK

    devices = {d.device_id: d for d in svc.store.list_devices()}
    assert devices["d0"].status is DeviceStatus.SUCCEEDED
    assert devices["d0"].version == "2.0.0"
    for dev_id in ("d1", "d2", "d3"):
        assert devices[dev_id].status is DeviceStatus.ROLLED_BACK
        assert devices[dev_id].version == "1.0.0"
        assert devices[dev_id].target_version is None
    logger.info("场景2b 回滚后无半新半旧状态: %s",
                {k: (v.status.value, v.version) for k, v in devices.items()})


def test_rollback_is_idempotent_and_not_double_triggered(caplog) -> None:
    """场景2c：回滚后重复调用不产生副作用，后续上报被拒绝，回滚不重复触发。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service(threshold=0.5)
    svc.advance(rel_id)
    svc.handle_report(failure("d0", 1))
    svc.handle_report(failure("d1", 1))  # 2/2 = 1.0 自动回滚
    rel = svc.get_release(rel_id)
    assert rel.auto_rolled_back
    assert rel.failure_count == 2 and rel.success_count == 0

    again = svc.rollback(rel_id)  # 手动重复回滚
    assert again.status is ReleaseStatus.ROLLED_BACK
    assert again.failure_count == 2  # 计数未被重复累加
    logger.info("场景2c 重复回滚后计数保持 failure=2")

    # 回滚后的设备再上报失败 -> 发布单已终态，拒绝且不会改变计数
    with pytest.raises(ReleaseStateError):
        svc.handle_report(failure("d0", 2, report_id="late-1"))
    assert svc.get_release(rel_id).failure_count == 2
    logger.info("场景2c 回滚后的迟到上报被拒绝，回滚未重复触发: OK")


# --------------------------------------------------------------------- #
# 场景三：重复上报幂等
# --------------------------------------------------------------------- #
def test_duplicate_report_is_idempotent(caplog) -> None:
    """场景3：同一 report_id 重复上报不重复计数、不改变状态。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service()
    svc.advance(rel_id)
    r = success("d0", 1, report_id="fixed-id")
    svc.handle_report(r)

    with pytest.raises(DuplicateReportError) as exc:
        svc.handle_report(r)  # 完全相同的上报再来一次
    assert exc.value.code == "duplicate_report"

    # 换时间戳/内容但复用 report_id 仍算重复
    r2 = DeviceReport(report_id="fixed-id", device_id="d0", release_id=rel_id,
                      kind=ReportKind.UPGRADE_SUCCESS, seq=1, timestamp=99.0,
                      version="2.0.0")
    with pytest.raises(DuplicateReportError):
        svc.handle_report(r2)

    rel = svc.get_release(rel_id)
    assert rel.success_count == 1
    assert svc.store.get_device("d0").status is DeviceStatus.SUCCEEDED
    logger.info("场景3 重复上报被忽略，成功计数仍为1，状态未倒退: OK")


def test_terminal_device_cannot_be_overwritten(caplog) -> None:
    """场景3b：设备成功定论后，迟到的失败上报不得覆盖结论。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service()
    svc.advance(rel_id)
    svc.handle_report(success("d0", 1))
    with pytest.raises(DeviceStateError):
        svc.handle_report(failure("d0", 2, report_id="d0-late-fail"))
    device = svc.store.get_device("d0")
    assert device.status is DeviceStatus.SUCCEEDED
    assert device.version == "2.0.0"
    assert svc.get_release(rel_id).failure_count == 0
    logger.info("场景3b 成功结论未被迟到失败覆盖: OK")


# --------------------------------------------------------------------- #
# 场景四：乱序上报
# --------------------------------------------------------------------- #
def test_out_of_order_report_rejected(caplog) -> None:
    """场景4：seq 倒退的乱序上报被拒绝且不影响计数。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service()
    svc.advance(rel_id)

    svc.handle_report(report("d0", ReportKind.HEARTBEAT, seq=2,
                             report_id="d0-hb-2"))
    assert svc.store.get_device("d0").status is DeviceStatus.UPGRADING

    # seq=1 迟到（倒退）
    with pytest.raises(StaleReportError) as exc:
        svc.handle_report(report("d0", ReportKind.HEARTBEAT, seq=1,
                                 report_id="d0-hb-1"))
    assert exc.value.code == "stale_report"
    assert svc.store.get_device("d0").status is DeviceStatus.UPGRADING

    # seq=2 重复序号同样拒绝
    with pytest.raises(StaleReportError):
        svc.handle_report(report("d0", ReportKind.HEARTBEAT, seq=2,
                                 report_id="d0-hb-2b"))

    # seq=3 正常前进，成功定论
    svc.handle_report(success("d0", 3, report_id="d0-succ-3"))
    assert svc.store.get_device("d0").status is DeviceStatus.SUCCEEDED
    assert svc.get_release(rel_id).success_count == 1
    logger.info("场景4 乱序(seq=1)/重复序号(seq=2)被忽略，seq=3正常生效: OK")


def test_success_failure_arrive_then_dup_failure_does_not_rollback(caplog) -> None:
    """场景4b：重复失败上报不得把失败比例推过阈值触发误回滚。"""
    caplog.set_level(logging.INFO, logger="rollout-tests")
    svc, rel_id = build_service(threshold=0.5)
    svc.advance(rel_id)
    # 第0批 d0 成功、d1 失败 -> 0.5 不触发
    svc.handle_report(success("d0", 1))
    svc.handle_report(failure("d1", 1))
    # d1 的失败以新 report_id + 旧 seq 重放
    with pytest.raises(StaleReportError):
        svc.handle_report(failure("d1", 1, report_id="d1-replay"))
    # 同 report_id 重放
    with pytest.raises(DuplicateReportError):
        svc.handle_report(failure("d1", 1, report_id="d1-upgrade_failure-1"))
    rel = svc.get_release(rel_id)
    assert rel.status is ReleaseStatus.IN_PROGRESS
    assert rel.failure_count == 1
    logger.info("场景4b 重放失败未重复计数，发布未被误暂停/误回滚: OK")


# --------------------------------------------------------------------- #
# 场景五：建档准入与参数错误可区分
# --------------------------------------------------------------------- #
def test_create_release_rejects_incompatible_devices() -> None:
    """场景5：不满足升级条件的设备在建档时被挡下，原因可区分。"""
    svc = RolloutService()
    svc.register_firmware(FW)
    svc.register_device(Device("ok", "MX-100", "1.0.0"))
    svc.register_device(Device("bad-model", "MX-999", "1.0.0"))
    svc.register_device(Device("bad-gap", "MX-100", "0.9.0"))

    with pytest.raises(ReleaseValidationError) as exc:
        svc.create_release("r", "2.0.0",
                           ["ok", "bad-model", "bad-gap"], [3], 0.5)
    message = str(exc.value)
    assert "bad-model" in message and "型号" in message
    assert "bad-gap" in message and "版本跨度" in message


def test_create_release_target_version_missing() -> None:
    """场景5b：目标版本不存在，建档被挡下。"""
    svc = RolloutService()
    svc.register_device(Device("d0", "MX-100", "1.0.0"))
    with pytest.raises(ReleaseValidationError):
        svc.create_release("r", "9.9.9", ["d0"], [1], 0.5)


def test_unknown_release_and_device_membership() -> None:
    """场景5c：发布单不存在 / 设备不属于发布单，错误可区分。"""
    svc, _ = build_service()
    with pytest.raises(ReleaseNotFoundError):
        svc.advance("nope")
    svc.advance("rel")
    svc.register_device(Device("outsider", "MX-100", "1.0.0"))
    with pytest.raises(Exception) as exc:
        # outsider 不属于 rel，但 seq 校验先过；这里验证不会被静默吞掉
        svc.handle_report(success("outsider", 1, release_id="rel"))
    from app.errors import DeviceNotInReleaseError
    assert isinstance(exc.value, DeviceNotInReleaseError)


def test_success_report_version_mismatch_rejected() -> None:
    """场景5d：成功上报版本与目标版本不一致，视为非法上报。"""
    from app.errors import ReportValidationError
    svc, rel_id = build_service()
    svc.advance(rel_id)
    with pytest.raises(ReportValidationError):
        svc.handle_report(report("d0", ReportKind.UPGRADE_SUCCESS, 1,
                                 report_id="d0-wrong-ver", version="3.0.0"))
    # 非法上报被标记为已处理（report_id 已消费），设备状态不变
    assert svc.store.get_device("d0").status is DeviceStatus.PENDING
