# LocalPilot 仓库分析

## 概览

LocalPilot 是一个面向个人工作站和本地项目目录的本地命令行 Agent 运行时。它的目标是把自然语言任务转换成一个闭环的本地执行流程：LLM 会话可以读取和修改文件、运行 Python 或 shell 片段、更新记忆、向用户提问、执行计划中的多步骤任务，以及触发定时或自主的后台任务。

这个项目刻意坚持本地优先。README 将它定位为“本地通用 Agent”，而不是云端聊天服务、浏览器自动化产品或多设备平台。实现也支持这种定位：主运行时位于 `agent/`，模型和会话适配器位于 `core/`，可执行工具位于 `tools/`，SOP 和长期记忆材料位于 `memory/`，定时反射脚本位于 `reflect/`。

最有代表性的架构描述是：LocalPilot 是一个轻量级的 Plan-and-Execute 加上 Multi-Agent 风格的任务编排运行时。主 Agent 负责规划、分发工具、保留任务状态并收敛结果；配套的 SOP 和子 Agent 约定则指导探索、验证、记忆沉淀和批处理执行。

## 架构

LocalPilot 围绕单一运行循环组织：

1. `runagent.py` 启动 `agent/agentmain.py`。
2. `MyAgent` 加载模型配置，初始化 LLM 客户端，准备系统提示词和记忆上下文，并从交互式 CLI、`--task` 或 `--reflect` 接收任务。
3. `agent/agent_loop.py` 反复调用所选模型会话，解析工具调用，通过 `tools.handler.AgentHandler` 分发工具，把工具结果注入下一轮模型输出，并在工具结果或无工具结果标记任务完成时停止。
4. `core/session.py` 将多个 LLM 后端归一化为共享的内部内容块形态：文本、思考、工具使用和工具结果。它支持 OpenAI-compatible chat completions、OpenAI Responses 风格事件、Claude 风格消息、流式输出、回退解析以及工具调用归一化。
5. `tools/` 提供运行时的动作面：代码执行、文件读取、补丁应用、文件写入、用户提问、短期工作检查点和长期记忆更新提示。
6. `memory/` 存放供系统提示词和计划流程使用的 SOP 与持久化上下文。
7. `reflect/` 可以周期性地把提示词投递到同一个 Agent 运行时中，让定时任务或自主任务使用与交互式任务相同的执行循环。
8. `core/observability.py` 在 `temp/logs/agent-YYYY-MM-DD.jsonl` 下记录紧凑的 JSONL 事件，并用 `run_id` 关联任务、LLM 轮次、工具调用、重试、异常和完成事件。

这个运行时刻意以文件系统为中心。`config/paths.py` 集中管理稳定锚点，例如 `PROJECT_ROOT`、`TEMP_DIR`、`TOOLS_DIR`、`MEMORY_DIR`、`SCHE_TASKS_DIR`、`MODEL_RESPONSES_DIR` 和 `REFLECT_LOG_DIR`，从而减少早期提交已经开始暴露的路径漂移问题。

## 关键组件

- **CLI 和任务入口（`runagent.py`、`agent/agentmain.py`）**：启动 Agent，从 `mykey.py` 或 `core/mykey.json` 加载模型会话，处理交互式提示、一次性任务目录、后台模式、reflect 脚本、停止 / 干预文件，以及 `/resume` 和 `/session.<key>=<value>` 之类的斜杠命令。
- **Agent 执行循环（`agent/agent_loop.py`）**：负责逐轮执行。它调用模型，检测原生工具调用或回退的无工具行为，分发工具，收集工具结果，处理完成钩子，并记录每一轮。
- **LLM 会话层（`core/session.py`、`core/client.py`）**：把 OpenAI-compatible、Claude-compatible、原生工具调用、文本工具协议回退以及 mixin / fallback 会话行为适配为统一的内部响应模型。
- **配置层（`core/config.py`、`config/paths.py`）**：加载本地密钥 / 配置文件，按修改时间热重载模型配置，启用可选的 Langfuse tracing，并提供规范化的路径常量。
- **上下文管理（`core/context.py`）**：对历史记录做上下文预算裁剪，修复有问题的消息序列，插入缺失的工具结果，并在模型调用前清理相邻的用户消息。
- **工具协议与分发（`tools/base.py`、`tools/handler.py`、`tools/schemas.py`）**：把模型工具调用转换成 `StepOutcome` 对象，处理未知工具或 JSON 错误工具，记录工具生命周期事件，并强制执行 `data`、`next_prompt` 和 `should_exit` 的控制契约。
- **文件工具（`tools/file_tools.py`）**：按行号和截断方式读取文件，展开 `{{file:path:start:end}}` 引用，安全地补丁唯一文本块，写入文件，并消费任务控制文件。
- **代码工具（`tools/code_tools.py`）**：在受控工作目录中执行 Python 或 shell 片段，输出轻量级进度日志，强制超时，并传播停止信号。
- **记忆工具（`tools/memory_tools.py`）**：把全局记忆组装进系统提示词，跟踪记忆文件访问次数，更新短期工作检查点，并使用 `memory/memory_management_sop.md` 启动长期记忆沉淀。
- **计划辅助（`tools/plan_tools.py`、`memory/plan_sop.md`、`memory/verify_sop.md`、`memory/subagent.md`）**：为计划模式、验证模式和子 Agent 风格的委派工作提供状态标记和 SOP 材料。
- **反射与调度（`reflect/scheduler.py`、`reflect/autonomous.py`、`sche_tasks/`）**：轮询任务 JSON 文件，执行重复 / 冷却窗口规则，在 `sche_tasks/done/` 下写报告，每 12 小时运行一次 L4 会话压缩，并在空闲后可选地发出自主提示。
- **可观测性（`core/observability.py`、`core/mylogging.py`、`plugins/langfuse_tracing.py`）**：为控制流调试写入紧凑、去敏的 JSONL 事件，并在有配置时可选启用 Langfuse tracing。
- **文档和本地测试（`README.md`、`docs/`、`tests/`）**：README 是最权威的用户侧说明。工作区里包含针对路径常量、会话解析、LLM 配置加载、仓库工具行为和启动帮助的测试，但在最新仓库快照里，`docs/` 和 `tests/` 目前仍被 `.gitignore` 忽略而未纳入跟踪。

## 使用技术

- **语言**：README 推荐 Python 3.11+；本地工作区中 `.venv` 使用的是 Python 3.12。
- **运行时依赖**：`requests>=2.31.0`、`urllib3>=2.0.0`。
- **可选集成**：`plugins/langfuse_tracing.py` 通过 `langfuse>=2.0.0` 集成；README 安装说明中还提到可选的 `yara-python`。
- **LLM 协议**：OpenAI-compatible chat completions、OpenAI Responses 风格事件解析、Claude 风格消息、原生工具调用，以及文本工具调用回退解析。
- **交互方式**：命令行交互模式、任务目录文件 I/O 模式、后台任务模式和 reflect 脚本模式。
- **存储**：`memory/`、`temp/`、`sche_tasks/` 和 `temp/model_responses/` 下的本地文件。
- **测试方式**：工作区中存在针对路径、会话、仓库工具和启动行为的 Python `unittest` 测试。

## 数据流

交互式流程：

1. 用户运行 `python runagent.py`。
2. `agent/agentmain.py` 加载模型配置、记忆提示词、工具 schema 和选定的 LLM 客户端。
3. 用户输入被包装成任务并放入 `MyAgent.task_queue`。
4. `agent_runner_loop` 将系统提示词和用户输入发送给 LLM 会话。
5. 模型要么直接回复，要么发出工具调用。
6. `AgentHandler.dispatch` 调用对应的 `do_*` 工具方法。
7. 工具输出会变成一个 `StepOutcome`；其 `next_prompt` 会被送回下一轮模型输出。
8. 当没有下一轮提示词、工具退出，或无工具完成结果通过校验后，最终回复会返回到终端。
9. JSONL 可观测性记录任务开始 / 结束、LLM 轮次、工具调用、用量、重试和异常。

任务目录流程：

1. 用户运行 `python runagent.py --task <name> --input "<prompt>"`。
2. 输入被写入 `temp/<name>/input.txt`。
3. 中间结果和最终输出被写入 `output.txt`、`output1.txt` 以及后续编号文件。
4. 外部进程可以添加 `reply.txt`、`_stop`、`_intervene` 或 `_keyinfo` 来引导或停止运行中的任务。

Reflect 流程：

1. 用户运行 `python runagent.py --reflect reflect/scheduler.py` 或其他 reflect 脚本。
2. 当调度或触发条件满足时，reflect 脚本的 `check()` 函数返回一个任务提示词。
3. 同一个 `MyAgent` 运行时处理该提示词。
4. 结果会写入 reflect 日志；对于定时任务，还会写入 `sche_tasks/done/` 下的报告文件。

记忆流程：

1. `get_system_prompt()` 读取提示词资源并附加全局记忆材料。
2. 记忆工具可以更新短期的 `handler.working` 检查点，或启动长期记忆沉淀。
3. 读取记忆 / SOP 文件会增加 `memory/file_access_stats.json` 的访问计数，使记忆使用变得可观测。
4. `memory/L4_raw_sessions/compress_session.py` 可以把模型响应历史归档为 L4 原始会话。

## 团队与所有权

过去一年的 git 历史中只有 17 个提交，全部作者都是 `sunny`。没有合并提交，因此这个仓库当前看起来像一个单维护者、线性开发风格的项目。

各领域的所有权可以从同一位作者在所有主要表面上的持续工作中看出：

- `core/session.py`、`core/client.py` 和 `core/context.py`：模型协议和上下文所有权。
- `tools/handler.py`、`tools/base.py` 及相关工具文件：工具执行和控制流所有权。
- `agent/agentmain.py` 和 `agent/agent_loop.py`：运行时编排所有权。
- `memory/` 和 `reflect/`：自主运行、规划、调度和记忆生命周期所有权。
- `README.md`：产品定位和面向用户的操作指南。

当前仓库状态是干净的，但一些有用的本地文件被刻意忽略，包括 `docs/`、`tests/`、`temp/`、`.venv/`、`sche_tasks/` 和本地密钥文件。这种划分说明：被跟踪的仓库代表运行时核心，而实验、评测产物和机器本地的运行状态则保留在版本控制之外。