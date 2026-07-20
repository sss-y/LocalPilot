# LocalPilot P0 工程体检

P0 是 LocalPilot 的本地、只读工程体检入口。请从仓库根目录使用当前虚拟环境运行唯一命令：

```bash
.venv/bin/python -m p0_baseline
```

P0 默认离线运行，不需要 Provider 凭证，也不会自动安装依赖、修改工作区或创建提交。

## 支持环境与准备

当前只验证以下组合：

- macOS Darwin arm64；
- CPython 3.12.x；
- `requirements-p0.lock` 中精确版本和哈希对应的 P0 依赖。

首次准备或锁文件变化后，由使用者显式安装依赖：

```bash
.venv/bin/python -m pip install --require-hashes -r requirements-p0.lock
```

Runner 自身不会安装或修复依赖。不支持的运行环境或依赖不匹配会得到 `failure / 1`。

## 状态和退出码

| 状态 | 退出码 | 含义 |
| --- | ---: | --- |
| `success` | `0` | 全部活动必需检查通过，环境、离线、凭证和干净工作树资格门也通过 |
| `failure` | `1` | 已发现确定问题，例如依赖不匹配、必需检查失败或离线边界违规 |
| `incomplete` | `2` | 检查没有完整结束，或工作树 dirty 等资格条件阻止正式成功 |

确定失败优先于未完成。dirty 工作树不会被清理，也不会把已通过的检查改成失败，但总体至多为 `incomplete / 2`。

## 输出格式

默认 human 输出包含状态、退出码和检查统计，最后一行是大写总体状态：

```bash
.venv/bin/python -m p0_baseline --format human
```

JSON 模式向标准输出写出一个经过 Schema 校验和脱敏的对象：

```bash
.venv/bin/python -m p0_baseline --format json
```

需要同时保存 JSON 时使用：

```bash
.venv/bin/python -m p0_baseline --format json --output temp/p0-report.json
```

指定文件写入失败时，总体至少为 `incomplete / 2`；如果运行已经存在确定失败，则仍为 `failure / 1`。

## 本地验收命令

以下四个自动质量门都应以退出码 `0` 结束：

```bash
.venv/bin/python -m unittest discover -s tests/p0 -t .
.venv/bin/python -m compileall -q p0_baseline tests/p0
.venv/bin/python -m p0_baseline --help
.venv/bin/python -m unittest tests.p0.test_dirty_semantics.DirtySemanticVerificationTests.test_real_p0_reports_dirty_as_the_only_acceptance_blocker
```

最后一个是外层验收测试：它内部运行真实 P0，并确认 dirty 工作树返回 `incomplete / 2`，且 dirty 是唯一阻止 success 的资格条件。这个测试不在活动 Manifest 中，因此不会递归执行自身。

裸跑 `.venv/bin/python -m p0_baseline --format json` 用于人工观察。开发工作树 dirty 时它按设计返回 `2`，不要求为了得到 `0` 而删除、覆盖或提交用户文件。

## 已知限制

本轮没有验证或承诺以下能力：

- LocalPilot 的全量产品行为；
- 旧版 56/62 条 Requirement 的完整认证；报告中的旧映射仅作为兼容元数据；
- 针对恶意 Python、动态 Loader、直接文件读取或 native 扩展的强沙箱；
- 自动 candidate commit、clean clone 或独立验收环境；
- 真实外网和在线 Provider smoke。

因此，P0 通过只说明当前活动 Manifest、当前支持环境和当前检出的本地工程基线满足上述检查，不代表这些延后范围已经通过。
