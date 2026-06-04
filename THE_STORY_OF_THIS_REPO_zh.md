# LocalPilot 的故事

## 编年史：一年里的数字

LocalPilot 可见的 git 历史非常紧凑，但密度很高：

- **总提交数**：17。
- **过去一年的提交数**：17。
- **活跃月份**：仅 2026 年 5 月。
- **第一个可见提交**：`1f35beb`，2026-05-04，"🎉 Initial commit: Setup project and venv"。
- **最后一个可见提交**：`39fd306`，2026-05-28，"update memory stats"。
- **贡献者数量**：可见作者只有一位，`sunny`。
- **合并提交**：没有。
- **最高活跃日期**：2026-05-27，共 6 个提交，其次是 2026-05-28，共 4 个提交。

这不是一段跨度很长的产品考古记录，而是一场持续三周半的冲刺：一个本地 Agent 运行时快速出现、迅速成长，随后又被整理成更清晰的架构。

按日期展开的节奏是这样的：

- 2026-05-04：1 个提交，仓库初始化。
- 2026-05-08：1 个提交，LLM 会话层和上下文裁剪出现。
- 2026-05-11：1 个提交，工具和 Agent loop 出现。
- 2026-05-17：2 个提交，计划模式、记忆、调度器、SOP 和 README 扩展出现。
- 2026-05-21：1 个提交，工具表面趋于成熟。
- 2026-05-22：1 个提交，小幅提升上下文可读性。
- 2026-05-27：6 个提交，重大重构和文档清理。
- 2026-05-28：4 个提交，重命名、README 修正、结构化可观测性和记忆统计更新。

## 角色群像

**sunny** 是这份可见历史中的全部角色：运行时设计者、工具作者、记忆系统作者、文档作者、测试作者，也是维护者。这里不是单点功能归属，而是整个系统的构建过程。

从提交历史里能看到的专长包括：

- **运行时编排**：`agent/agentmain.py` 和 `agent/agent_loop.py` 在 2026-05-27 的 `adb7742` 中被拆分并稳定下来，把早期根目录脚本整理成更清晰的包结构。
- **LLM 协议适配**：`core/session.py` 是体量最大、改动最频繁的文件之一。它从 `83c703d` 中的 LiteLLM 会话工作开始，在 `33a3189` 中扩展，随后在 `c7b0260` 中被大幅简化。
- **工具执行**：`tools/handler.py`、`tools/base.py`、`tools/file_tools.py`、`tools/code_tools.py` 以及 schema 文件，体现了从早期工具雏形到受控 `StepOutcome` 合约的演进。
- **记忆与自主运行**：`memory/plan_sop.md`、`memory/verify_sop.md`、`memory/subagent.md`、`memory/scheduled_task_sop.md`、`reflect/scheduler.py` 和 `reflect/autonomous.py` 展示了项目从一次性聊天走向可计划、可重复的本地运行。
- **运行可见性**：`a76fd2f` 添加了 `core/observability.py`，并把 JSONL 日志贯穿到 `agent/`、`core/` 和 `tools/`。

这是一位既像产品用户、又像基础设施工程师的维护者：先增加能力，再迅速补上让这些能力可调试的护栏。

## 季节性模式

这段历史里只有一个季节：2026 年 5 月。项目从 2026-05-04 开始，把通常会分散到多个阶段的原型过程压缩进了一个月。

5 月前半段是基础建设：

- `1f35beb` 创建初始仓库。
- `83c703d` 添加 LiteLLM 集成、日志记录和历史裁剪。
- `ae8b7e4` 添加第一版主要工具层和 Agent loop。

5 月中段是能力扩展：

- `33a3189` 添加计划模式和自主记忆沉淀。这是项目第一次明显从聊天包装器转向本地 Agent 运行时。
- 同一个提交还加入了大量 SOP 材料、调度器代码、记忆文件、提示词资源、测试材料和反射 / 自主脚本。
- `79928a0` 继续推进工具工作，尤其集中在 `tools/handler.py` 和文件 / 代码辅助函数上。

5 月后段是收敛整理：

- `adb7742` 重组 agent 模块并共享路径配置。
- `c7b0260` 重构 core 模块，移除旧的 `llmcore/schema/tool_protocol` 表面，新增 `core/client.py`，并明显缩减 `core/session.py`。
- `26fd9a7`、`b1fce01` 以及附近提交让 README 与新的入口点和当前架构保持一致。
- `a76fd2f` 在架构足够复杂之后加入结构化可观测性。

最能说明问题的节奏是：文档不是事后补充，而是和代码一起演进。`README.md` 在六个提交中被修改，通常紧跟在结构变化之后。这说明维护者把 README 当作系统的实时地图，而不只是用户手册。

## 主要主题

### 主题 1：从脚本到运行时

LocalPilot 最早看起来像一个脚本式 Agent。到 2026-05-11，`agent_loop.py`、`llmcore.py` 和完整的 `tools/` 包都已经存在。到 2026-05-27，根目录内容被收拢到 `agent/`、`core/`、`tools/` 和 `config/paths.py` 里。

关键转折是 `adb7742`："refactor: restructure agent module and update tools/config"。这个提交引入了 `agent/agentmain.py`，把 `agent_loop.py` 移入 `agent/`，并加入 `config/paths.py`。它让项目从“几个能工作的文件集合”变成“有模块边界的运行时”。

### 主题 2：工具调用就是产品核心

工具层不是附属品。`tools/handler.py` 先在 `ae8b7e4` 中增加了 376 行，随后随着 Agent loop 的成熟持续演进。当前工具包括：

- `code_run`
- `file_read`
- `file_patch`
- `file_write`
- `update_working_checkpoint`
- `ask_user`
- `start_long_term_update`

真正有意思的设计是 `StepOutcome`。工具返回的不只是数据，还返回控制流指令：是否继续、下一轮发送什么提示，以及任务是否应该退出。这让工具成为 Agent 状态机的一部分，而不只是简单的工具函数。

### 主题 3：记忆是运行时能力，不是装饰品

记忆系统采用本地文件加 SOP 的方式，而不是外部向量数据库。`memory/global_mem.txt`、`memory/global_mem_insight.txt`、`memory/file_access_stats.json` 以及多份 SOP Markdown 文件，会被读取进提示词或由工具使用。

`33a3189` 是记忆扩展最重要的提交。它加入了计划、验证、定时任务、监督者、自主运行和子 Agent SOP。后来的 `39fd306` 更新了记忆统计，这说明记忆使用本身也被当作运行时数据。

这里的故事很务实：项目选择了可检查的本地文本和 JSON，作为第一层持久记忆。

### 主题 4：上下文和协议兼容很早就成了难题

`core/session.py` 从一开始就是核心。`83c703d` 添加了 LiteLLM 集成和上下文裁剪。当前文件处理 OpenAI 兼容的流式响应、Claude 风格 SSE、Responses API 风格事件、reasoning/thinking 块、工具调用参数解析、用量记录以及回退形态。

`c7b0260` 的大重构清楚说明，最初的模型协议设计已经过宽或者过于纠缠。那个提交移除了 `core/llmcore.py`、`core/schema.py` 和 `core/tool_protocol.py`，新增 `core/client.py`，并用更小的表面重写了 `core/session.py`。

### 主题 5：可调试性是在复杂度之后到来的

提交 `a76fd2f`，"feat: add structured JSONL observability across the agent pipeline"，标志着运行可见性的成熟点。它新增了 `core/observability.py`，并修改了 `agent/agent_loop.py`、`agent/agentmain.py`、`core/session.py`、`tools/base.py` 和 `README.md`。

这个改动加入了任务级的 `run_id`，以及紧凑的事件记录：任务生命周期、LLM 轮次、模型请求、重试、用量、工具调用、异常和完成状态。

这说明仓库已经承认：一旦 Agent 能调用工具并运行长流程，单靠打印调试是不够的。

## 转折点与剧情反转

### 大扩张：2026-05-17

提交 `33a3189`，"新增plan模式和memory自主沉淀"，意味着项目开始变得更有野心。它新增了一个 282 行的 README、`core/session.py` 中 481 行的扩展、一个 262 行的 `memory/plan_sop.md`、调度器支持、记忆 SOP、提示词资源、测试材料，以及反射 / 自主脚本。

这一刻，LocalPilot 不再只是一个简单的 LLM 命令包装器，而是在尝试成为一个持久化的本地 Agent 系统。

### 工具层收敛：2026-05-21

提交 `79928a0`，标题只有简单的 "tools"，但意义很大。它修改了 README、`agent_loop.py`、`agentmain.py`、`tools/file_tools.py`、`tools/handler.py` 和其他工具模块。handler 在这个提交里增加了最多行数，说明维护者已经摸清了真正的复杂性：稳定的工具分发和任务续航。

### 架构重构：2026-05-27

这一天有两个决定性的提交：

- `adb7742`：重组 `agent/`，更新工具和配置，并引入共享路径常量。
- `c7b0260`：重构 `core/`，移除旧协议模块，新增 `core/client.py`，并简化 `core/session.py`。

这一天总共有 6 个提交。它读起来像是在系统已经证明自己有用之后，为它补上更好的边界的收尾冲刺。

### 重命名：2026-05-28

提交 `c3b3967`，"rename, 避免冲突"，把 `agentmain.py` 重命名为 `runagent.py`。紧接着的文档提交同步更新了 README 的引用。这个改动虽然小，但很重要：根入口变成了启动器，而实现入口留在 `agent/agentmain.py` 中。

### 可观测性层：2026-05-28

提交 `a76fd2f` 在运行时中加入了 427 行插入。这是项目开始把 Agent 执行视作需要可追踪操作的时刻：任务开始与结束、LLM 轮次耗时、工具异常、重试行为和 token 使用量。

这也是仓库故事变得更偏生产化的时刻。代码仍然面向本地个人 Agent，但现在已经有足够的仪表来诊断本地故障，而不是靠猜。

## 当前篇章

LocalPilot 目前是一个体量紧凑、偏本地优先的 Agent 运行时，架构也比较清晰：

- `agent/` 负责编排。
- `core/` 负责模型会话、配置、上下文、日志和可观测性。
- `tools/` 负责可执行动作面。
- `memory/` 保存 SOP 和持久化提示材料。
- `reflect/` 把同一套运行时变成调度器 / 自主工作器。
- `README.md` 记录预期操作模型。

这个仓库仍然很早期。它的可见历史只有 17 个提交，而且一些有价值的本地材料，比如 `tests/`、`docs/` 和 `temp/`，并没有被跟踪。因此，当前 git 快照更多代表的是运行时核心，而不是完整的工作环境。

下一个自然章节是加固：

- 决定哪些测试应该被纳入跟踪，并把测试命令变成日常开发的一部分。
- 明确运行时状态（`temp/`、`sche_tasks/`、记忆统计）和可复用项目代码之间的边界。
- 随着更多 provider 协议加入，保持 `core/session.py` 的边界足够窄。
- 围绕 task 目录和 reflect 工作流扩展可观测性。
- 保持当前的本地优先架构，不要漂移成一个通用的云端 Agent 平台。

人的故事很直接：一位维护者做了一个让本地机器通过 Agent loop 行动的工具，然后很快意识到，计划、记忆、路径、协议归一化和日志不是附加项，它们才是真正的运行时。