# firmware-rollout-orchestrator

固件分阶段灰度发布与自动回滚服务（FastAPI + 本地内存数据模拟设备上报）。

能力：

- 固件版本与设备型号的兼容性判定与发布准入，区分
  “目标版本不存在 / 型号不支持 / 版本跨度过大”三类原因；
- 按批次逐步放量，批次失败比例超阈值自动暂停并回滚到升级前版本，
- 已升级成功的设备不参与回滚，回滚后各设备状态与运行版本前后一致；
- 设备上报与心跳按 `report_id` + 单调 `seq` 幂等处理，重复/乱序上报
  不会造成状态倒退、重复计数或重复回滚；
- 所有失败返回带 `code` 的业务错误，不向调用方透传底层异常。

详细规则与本地验证方法见 [docs/ROLLOUT.md](docs/ROLLOUT.md)。

快速开始：

```bash
uv sync
uv run pytest                                   # 全量测试（含场景日志）
uv run python -m scripts.simulate_devices       # 设备上报模拟器
uv run python main.py                           # HTTP 服务
```
