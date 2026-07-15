# P0 历史测试资产分类

## 目的与边界

本文档记录任务 1.2 实施时本机可见的全部历史测试，并为每项给出明确的迁移、选择性重写或 P0 排除决定，满足 Requirements 1.1、1.2、1.3、1.5、5.6 和 10.3。

只有 `tests/p0/**` 是 P0 必需测试资产并解除 Git 忽略。下表中的历史测试继续被忽略，不构成干净检出的验收前提；其中有价值的当前行为证据由后续 5.x 任务重写到 P0 目录。`temp/`、凭证、缓存、模型原文日志和任务运行输出仍属于不得提交的本机运行时资产。

## 逐项分类

| 本机历史测试 | 决定 | P0 目标 | 理由 |
| --- | --- | --- | --- |
| `tests/test_agent_paths.py` | 重写并迁移 | `tests/p0/behavior/test_cli_module_paths.py` | 保留 CLI help、核心模块加载和项目路径锚点证据；删除对不存在的 `agent.agentmain`、`core.llmcore` 的断言。 |
| `tests/test_session.py` | 选择性重写 | `tests/p0/behavior/test_model_responses.py` 与 `tests/p0/behavior/test_transport_errors.py` | 只保留当前模型响应、多工具调用和错误类别；文本工具协议证据必须标记为 `transitional`，不得固化为长期产品承诺。 |
| `tests/test_llm_client.py` | 选择性重写 | `tests/p0/behavior/test_model_responses.py` | 去除个人配置名和已删除模块依赖，只迁移 P0 范围内的响应与选择语义证据。 |
| `tests/test_repo_handler_tools.py` | 选择性迁移 | `tests/p0/behavior/test_tool_dispatch.py` | 仅迁移有效请求、参数错误和未知工具请求的可判定分发结果，不扩展工具能力。 |
| `tests/test_repo_tools.py` | P0 排除 | 无 | 具体 repo 工具能力不属于 P0 受保护行为；恢复为必需检查会扩大批准范围。 |
| `tests/test_evals.py` | P0 排除 | 无 | 当前修订缺少 `evals` 包且用例涉及在线数据集，不属于默认离线 P0 门。 |
| `test_client.py` | P0 排除 | 无 | 根目录历史/手工测试不是受控测试资产，不作为 P0 必需验收前提。 |

## Git 治理结论

- `tests/p0/**` 及其必要父目录可被 Git 变更检测识别。
- `tests/p0/` 之外的历史 `tests/*` 继续忽略，等待上表指定的后续迁移或重写，而不是静默成为 P0 检查。
- `temp/` 继续忽略，权威报告等运行时证据不得提交。
- `mykey.py`、`mykey.json`、`.env` 等个人凭证规则继续生效。
- `plugins/`、`docs/`、`sche_tasks/` 等现有非 P0 忽略边界保持不变。
