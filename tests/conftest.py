"""测试运行日志：打印每个场景的名称、用例标题与通过情况。"""
from __future__ import annotations

import logging

_scenario_logged: set[str] = set()


def pytest_runtest_logstart(nodeid, location):  # noqa: ANN001
    logger = logging.getLogger("scenario")
    name = nodeid.split("::")[-1]
    module = nodeid.split("::")[0].split("/")[-1]
    logger.info("")
    logger.info("▶ 开始 [%s] %s", module, name)


def pytest_runtest_logreport(report):  # noqa: ANN001
    if report.when != "call":
        if report.when == "setup" and report.failed:
            logging.getLogger("scenario").error("✗ 用例准备失败: %s", report.nodeid)
        return
    logger = logging.getLogger("scenario")
    if report.passed:
        logger.info("✔ 通过: %s (%.3fs)", report.nodeid, report.duration)
    elif report.failed:
        logger.error("✘ 失败: %s", report.nodeid)
    elif report.skipped:
        logger.warning("⊘ 跳过: %s", report.nodeid)


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ANN001
    counts = {
        "通过": len(terminalreporter.stats.get("passed", [])),
        "失败": len(terminalreporter.stats.get("failed", [])),
        "跳过": len(terminalreporter.stats.get("skipped", [])),
    }
    terminalreporter.write_sep("=", "场景执行汇总")
    for label, count in counts.items():
        terminalreporter.write_line(f"{label}: {count}")
