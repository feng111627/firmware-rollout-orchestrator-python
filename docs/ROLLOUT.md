# 固件分阶段灰度发布与自动回滚

本服务在现有 FastAPI 后端内提供固件版本兼容判定、按批次灰度放量、
设备上报幂等处理与失败自动回滚能力。设备端上报使用本地内存数据模拟，
无需外部数据库。

## 1. 模块结构

| 文件 | 职责 |
| --- | --- |
| `app/models.py` | 领域模型：固件、设备、批次、发布单、上报事件及状态枚举 |
| `app/errors.py` | 业务错误码，调用方可区分，不向调用方透传底层异常 |
| `app/compatibility.py` | 版本号解析、版本跨度判定、发布准入 |
| `app/store.py` | 线程安全的本地内存存储（上报幂等表 + 设备序号） |
| `app/rollout.py` | 编排核心：建档准入、批次推进、上报处理、自动暂停/回滚 |
| `app/api.py` | FastAPI 接入层，业务错误到 HTTP 响应的统一翻译 |
| `scripts/simulate_devices.py` | 本地设备上报模拟器（含重复/乱序/超阈值场景） |
| `tests/` | 兼容、存储、编排主链路、HTTP 层测试 |

## 2. 兼容性与发布准入

建档时（`create_release`）对每台设备依次做准入判定，任何一台不通过都会
阻止整个发布单创建，并在错误信息中逐台列出原因。三类失败严格区分：

| 错误码 `error.code` | 含义 |
| --- | --- |
| `target_version_not_found` | 目标固件版本不存在（固件库中查不到） |
| `model_not_supported` | 设备型号不在固件 `supported_models` 列表内 |
| `version_gap_too_large` | 设备当前版本低于固件声明的 `min_upgrade_from`，版本跨度过大 |

版本号按数字点分段比较（`1.10.0 > 1.9.0`），后缀如 `-rc1` 忽略。
固件未声明 `min_upgrade_from` 时不做跨度限制。

## 3. 灰度发布推进规则

- 发布单按 `batch_sizes`（如 `[2, 3, 5]`）严格顺序放量。
- 状态机：`draft → in_progress → (paused → rolling_back → rolled_back)`
  或 `in_progress → completed`。
- `advance` 的准入条件：
  - `draft`：启动第 0 批，批内设备置 `pending`，记录各自基线版本
    （升级前版本）；
  - `in_progress`：当前批次所有设备都已上报成功/失败（有定论）后，
    才允许进入下一批；当前批次未完成时推进返回
    `release_invalid_state`；
  - `paused / rolling_back / rolled_back / completed / cancelled`：
    一律拒绝推进。
- 批次失败比例 = 批内失败数 / 批内设备总数（**不是**已定论数），
  与 `failure_threshold` 比较：**严格大于**阈值才触发
  （等于阈值不触发）。

## 4. 自动暂停与回滚判定

- 某批次失败比例超过阈值时，该次失败上报在同一临界区内完成：
  发布单置 `paused` 并记录 `rollback_reason`（人类可读，含批次、
  实际比例与阈值），随后自动执行回滚，最终状态为 `rolled_back`，
  `auto_rolled_back=True`。
- 回滚只作用于**未升级成功**的设备：

  | 回滚前状态 | 回滚处理 |
  | --- | --- |
  | `succeeded`（已运行新版本） | **保留新版本，不回滚** |
  | `pending` / `upgrading` / `failed` | 版本恢复为各自基线版本，状态置 `rolled_back`，清空目标版本 |
  | `rolled_back` | 幂等，无变化 |

- 因此回滚后设备状态与其 `version` 字段严格一致：成功设备是
  `succeeded@新版本`，其余是 `rolled_back@基线版本`，不存在
  “半新半旧又说不清”的中间态。
- 回滚可重复调用（幂等）；回滚后的迟到上报会被
  `release_invalid_state` 拒绝，不会二次触发回滚，计数也不重复累加。

## 5. 上报幂等与乱序处理

每个设备维护两个去重维度，判定在同一把锁内原子完成：

1. **`report_id` 幂等键**：重复 `report_id` 返回
   `duplicate_report`（HTTP 409），计数与状态完全不变。
2. **设备单调序号 `seq`**：`seq` 必须严格递增，重复或倒退返回
   `stale_report`（HTTP 409）。乱序心跳不会把 `upgrading` 拉回
   `pending`，乱序/重放的失败不会把失败比例推过阈值。

其余可区分错误：

| 错误码 | 含义 |
| --- | --- |
| `device_not_found` / `release_not_found` | 设备或发布单不存在 |
| `device_not_in_release` | 设备不属于该发布单 |
| `device_invalid_state` | 设备不在当前批次，或已有成功/失败最终结论 |
| `release_invalid_state` | 发布单状态不接受该操作（如回滚后继续上报/推进） |
| `report_validation_error` | 上报非法（类型未知、成功上报版本与目标不符等） |

心跳（`heartbeat`）只表示设备开始动作：`pending → upgrading`，
不计入成功/失败统计。

## 6. HTTP 接口

| 方法与路径 | 说明 |
| --- | --- |
| `POST /admin/firmwares` | 登记固件 |
| `POST /admin/devices` | 登记设备 |
| `POST /releases` | 创建发布单（创建时做全量准入） |
| `POST /releases/{id}/advance` | 启动/推进下一批 |
| `POST /releases/{id}/rollback` | 手动回滚（幂等） |
| `GET  /releases/{id}` | 查询发布单视图（状态、计数、回滚原因） |
| `POST /reports` | 设备上报（成功/失败/心跳） |

错误统一为 `{"error": {"code": "...", "message": "..."}}`：
资源不存在 404；重复/乱序/状态冲突 409；准入与参数问题 422。

## 7. 本地验证方法

```bash
# 安装依赖（uv 项目）
uv sync

# 运行全部测试（日志会逐条打印场景开始/通过，并在结尾汇总）
uv run pytest

# 只看主链路（灰度推进 / 自动回滚 / 重复乱序）
uv run pytest tests/test_rollout.py

# 启动 HTTP 服务
uv run python main.py        # http://127.0.0.1:8000/docs

# 运行本地设备上报模拟器（观察拒绝重复/乱序上报与自动回滚快照）
uv run python -m scripts.simulate_devices
```

测试场景覆盖：

- 兼容判定：三种准入失败可区分、版本后缀解析、无跨度限制固件；
- 灰度推进：批次顺序、未完成批次禁止推进、全部成功后完成；
- 失败回滚：比例等于阈值不触发、超过阈值自动暂停回滚、
  已成功设备保留新版本、待升级设备一并回滚、回滚幂等、
  迟到上报不二次触发；
- 幂等/乱序：重复 `report_id`、`seq` 倒退与重复、成功结论不被
  迟到失败覆盖、重放失败不造成误回滚；
- HTTP 层：错误码与状态码翻译、发布视图中的回滚原因可见。
