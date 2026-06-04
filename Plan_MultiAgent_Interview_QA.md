# LocalPilot 计划执行、验证与多 Agent 协作面试题

本文基于当前 LocalPilot 实现整理。回答时应明确区分：

- **已经由 Runtime 实现的能力**：进程启动、文件通信、任务队列、计划标志、部分完成拦截。
- **主要由 SOP 约束的行为**：复杂任务识别、四阶段流转、主动监察、独立验证和失败修复。
- **尚未实现的能力**：完整状态机、文件 watcher、可靠消息队列和严格验证证据校验。

---

## 1. 请介绍 Plan-and-Execute 与多 Agent 协作闭环
面对多步骤、有依赖的长任务，单 Agent 容易跳步、遗漏，也容易被大量探索日志污染上下文。因此我设计了 SOP 驱动、Runtime 辅助约束的 Plan-and-Execute + Multi-Agent 轻量编排机制。流程分为探索、规划、执行、验证四个阶段：探索和最终验证委托给独立 Sub Agent，主 Agent 负责制定计划、推进执行和收口。计划持久化到 plan.md，用 checkbox 保存进度；Sub Agent 通过 --task --bg 启动独立进程，主从通过 task 目录下的文件协议通信。当前 Runtime 已实现计划标志、剩余步骤统计、进程启动和部分提前完成拦截，但四阶段严格流转及验证纪律仍依赖 SOP，因此它是轻量级编排 MVP，还不是完整工作流引擎。

### STAR 答题思路

**S（背景）**

复杂任务通常包含环境探测、多步执行和结果验证。直接让一个 Agent 在长上下文中完成全部工作，容易遗漏步骤，也会让探测日志挤占上下文。

**T（目标）**

我希望将复杂任务拆成可持久化的计划，并在探索和验证阶段引入独立 Sub Agent，降低上下文污染。

**A（行动）**

模型根据 `memory/plan_sop.md` 判断是否进入计划模式，然后调用：

```python
handler.enter_plan_mode("./plan_xxx/plan.md")
```

计划以 `plan.md` 保存，使用 Markdown checkbox 记录步骤状态。流程分为四个阶段：

1. 探索：启动只读 Sub Agent 收集环境信息。
2. 规划：根据探索结果生成 `plan.md`，并等待用户确认。
3. 执行：逐项完成任务，每步做 Mini 验证并更新 checkbox。
4. 验证：启动新的验证 Sub Agent，进行对抗性检查。

Sub Agent 通过：

```bash
python runagent.py --task <name> --bg --verbose
```

以独立进程运行。主从 Agent 使用 `temp/<task>/` 下的文件通信：

| 文件 | 作用 |
|---|---|
| `input.txt` | Sub Agent 初始任务 |
| `output.txt` | 当前 round 的进度快照和最终输出 |
| `reply.txt` | 外部追加下一轮输入 |
| `_intervene` | 追加纠偏提示 |
| `_keyinfo` | 注入关键上下文 |
| `_stop` | 请求停止当前任务 |

**R（结果）**

项目形成了一个轻量级 Plan-and-Execute + Multi-Agent MVP：长任务可以落盘、分阶段执行、委托探测并独立验证。需要诚实说明，它目前不是完整工作流引擎，部分流程仍依赖 SOP 引导模型执行。

### 代码锚点

- `tools/handler.py::enter_plan_mode()`
- `agent/agentmain.py` 的 `--bg` 和 `--task` 分支
- `memory/plan_sop.md`
- `memory/subagent.md`

---

## 2. 如果模型不遵循 SOP，Runtime 能否阻止它提前结束？
模型没有调用工具时，Agent Loop 会构造一个 no_tool 调用。do_no_tool() 检查当前是否处于 Plan 模式，再通过关键词判断模型是否提前声称完成。如果命中完成关键词，但回复中没有 VERDICT、[VERIFY] 或“验证subagent”，Runtime 会生成续轮 prompt，要求进入验证态。
但它只是弱约束：模型可以更换完成措辞；可以仅输出验证关键词而不真正验证；也可以提前把 checkbox 全部标记完成，使 Runtime 在剩余 [ ] 为 0 时退出 Plan 模式。更关键的是，Runtime 没有解析验证证据，也没有校验 Sub Agent 是否真实启动。因此当前实现是关键词拦截，不是状态机级验证门禁。

### STAR 答题思路

**S（背景）**

提示词可以指导模型按计划执行，但模型仍可能跳过步骤或提前声称任务完成。

**T（目标）**

在 Runtime 层增加最低限度的完成检查，减少模型提前退出的概率。

**A（行动）**

进入计划模式后，Runtime 保存计划文件路径：

```python
working["in_plan_mode"] = plan_path
```

`tools/plan_tools.py::_check_plan_completion()` 会读取 `plan.md`，统计剩余未完成项：

```python
len(re.findall(r"\[ \]", handle.read()))
```

当模型没有调用工具，进入 `tools/handler.py::do_no_tool()`。如果模型在计划模式中使用“任务完成”“全部完成”“已完成所有”或 `🏁` 等措辞，却没有出现 `VERDICT`、`[VERIFY]` 或“验证subagent”，Runtime 会生成续轮提示，要求先做验证。

**R（结果）**

这是一层弱约束，不是严格状态机。当前仍有绕过路径：

- 模型换一种完成措辞，可能避开关键词匹配。
- 回复中只要出现 `VERDICT` 字样，就可能绕过拦截。
- 剩余 `[ ]` 数量大于 `0` 时，代码不会强制续轮，只会保留 plan mode。
- 模型可能错误修改或提前删除 checkbox。

因此面试时应表述为：

> Runtime 已实现计划标志、checkbox 统计和部分完成拦截，但严格执行纪律仍主要依赖 SOP。

### 代码锚点

- `tools/plan_tools.py::_check_plan_completion()`
- `tools/handler.py::do_no_tool()`

---

## 3. 为什么最终验证要启动新的 Sub Agent？
主 Agent 执行任务后积累了大量调试上下文，也容易倾向于证明自己的实现正确。因此最终验证交给新的 Sub Agent，只传原始需求、计划路径、交付物和必做检查，不传完整执行过程。这样可以降低确认偏误和上下文污染。
但独立运行不等于结果可信。验证 Agent 仍可能跳过真实执行或只覆盖 happy path。目前 SOP 要求每项 PASS 都附带工具证据，并至少做一次对抗性探测；但 Runtime 尚未解析证据，也无法确认 VERDICT: PASS 背后真的运行了测试。这是后续需要补齐的验证门禁。
### STAR 答题思路

**S（背景）**

主 Agent 完成实现后，已经积累了大量调试上下文，也容易倾向于证明自己的方案正确。

**T（目标）**

让验证过程尽量独立，减少确认偏误和上下文过长导致的注意力衰减。

**A（行动）**

执行结束后，主 Agent 创建 `verify_context.json`，只传递：

- 原始任务描述
- `plan.md` 路径
- 交付物列表
- 必做检查列表
- 任务类型

不传完整调试过程，避免验证 Agent 被实现过程锚定。

验证 Sub Agent 按 `memory/verify_sop.md` 执行真实检查：运行命令、观察输出、测试边界情况，并在 `result.md` 最后一行写：

```text
VERDICT: PASS
VERDICT: FAIL
VERDICT: PARTIAL
```

**R（结果）**

这种做法提升的是**验证独立性**，不是绝对可信度。验证 Sub Agent 仍然共享文件系统和模型能力，也可能漏测、只检查 happy path，甚至只描述而不实际执行。

因此 `verify_sop.md` 要求每项 PASS 都有工具证据，并至少执行一个对抗性探测。但这些要求目前主要仍由 SOP 约束，Runtime 尚未逐项解析和校验证据。

### 代码锚点

- `memory/plan_sop.md` 的验证态
- `memory/verify_sop.md`

---

## 4. 为什么选择文件协议？它有哪些可靠性问题？

### STAR 答题思路

**S（背景）**

主 Agent 和 Sub Agent 是独立进程，需要一种简单的本地跨进程通信方式。

**T（目标）**

优先实现可观察、可调试、进程退出后仍可复盘的协作机制。

**A（行动）**

项目使用 task 目录作为通信边界。人、脚本和 Agent 都可以读取 `input.txt`、`output.txt`、`stdout.log` 和 `stderr.log`，也可以通过控制文件介入任务。

这适合 MVP，但存在边界：

1. `output.txt` 当前使用 `w` 模式覆盖写入，不是 append。
2. 主 Agent 在写入过程中读取，可能看到不完整快照。
3. 文件变化不会自动唤醒主 Agent，主 Agent 需要主动读取。
4. 多个 Agent 如果复用同一个 task 目录，可能竞争写入文件。
5. `_intervene` 等控制文件没有消息 ID、版本号和消费确认。
6. 进程崩溃后，没有结构化状态文件明确区分 `running`、`failed` 和 `completed`。

**R（结果）**

文件协议让系统快速具备本地协作能力，但它不是可靠消息队列。

后续可以演进为：

1. 使用唯一 `task_id` 和 `round_id` 隔离目录。
2. 使用临时文件写入后 `rename`，保证原子替换。
3. 增加 `status.json`，记录状态、PID、时间戳和错误。
4. 增加 watcher 或事件队列，主动通知主 Agent。
5. 为控制消息增加序号和 ACK。

### 代码锚点

- `agent/agentmain.py` 中 `output{nround}.txt` 的写入逻辑
- `config/paths.py::task_dir()`
- `tools/handler.py::turn_end_callback()`

---

## 5. task 模式中的两个超时分别是什么意思？

### STAR 答题思路

**S（背景）**

Sub Agent 既要持续输出执行进度，也要允许外部在 round 结束后追加下一轮任务。

**T（目标）**

避免任务进程永久卡住，同时保留多轮文件交互能力。

**A（行动）**

第一个超时是：

```python
dq.get(timeout=120)
```

它等待 Agent 工作线程向 `display_queue` 推送下一条事件：

```python
{"next": "..."}  # 中间进度
{"done": "..."}  # 当前 round 完成
```

收到 `next` 后，主线程覆盖更新 `output.txt`。收到 `done` 后，写入最终输出和：

```text
[ROUND END]
```

如果连续 `120` 秒没有任何事件，`queue.Empty` 可能导致 task 进程异常退出，并将错误写入 `stderr.log`。

第二个超时是 round 完成后等待 `reply.txt`：

```python
for _ in range(300):
    time.sleep(2)
    if (raw := consume_file(d, "reply.txt")):
        break
```

它每 `2` 秒检查一次，最多等待 `10` 分钟。如果没有下一轮输入，Sub Agent 自然退出。

**R（结果）**

这两个超时分别解决“执行期间没有进度事件”和“完成后没有下一轮输入”的问题。无论哪一种退出，当前都不会主动通知主 Agent；主 Agent 仍需读取 `output.txt`、`stderr.log` 或检查 PID。

### 代码锚点

- `agent/agentmain.py` 的 task 分支

---

## 6. 如何诚实评价当前 Plan-and-Execute 的成熟度？

### STAR 答题思路

**S（背景）**

如果将当前项目描述为完整的工作流引擎，面试官很容易从状态流转和故障恢复角度追问出缺口。

**T（目标）**

准确表达已实现能力，同时给出清晰的演进方向。

**A（行动）**

当前项目属于 SOP 驱动、Runtime 辅助约束的轻量实现。

已经落地的 Runtime 能力：

- `enter_plan_mode()` 保存计划路径，并提高最大执行轮数。
- `plan.md` 使用 checkbox 持久化任务步骤。
- Runtime 统计剩余 `[ ]`，并对部分提前完成行为做拦截。
- `--task --bg` 启动独立 Sub Agent 进程。
- task 目录承载输入、输出、日志和控制文件。
- Agent 工具结果通过续轮 prompt 继续驱动模型执行。

主要依赖 SOP 的部分：

- 是否应进入 plan mode。
- 探索、规划、执行、验证四阶段的严格流转。
- 主 Agent 主动监察 `output.txt`。
- 验证 Agent 是否实际执行了每项检查。
- FAIL 后是否正确进入修复循环。

**R（结果）**

当前系统已经可以支撑本地长任务的轻量编排，但还不是严格状态机。

下一步最值得补齐的是结构化任务状态，而不是继续增加提示词：

```json
{
  "task_id": "uuid",
  "state": "executing",
  "current_step": "step_3",
  "round": 1,
  "pid": 12345,
  "updated_at": "2026-06-02T10:00:00+08:00",
  "result": null
}
```

由 Runtime 校验合法流转：

```text
exploring → planning → waiting_approval → executing → verifying → completed
                                            ↘ failed
```

只有任务步骤全部完成，并且验证 Agent 产生有效 `VERDICT: PASS`，才能进入 `completed`。

### 代码锚点

- `tools/handler.py::enter_plan_mode()`
- `tools/handler.py::do_no_tool()`
- `tools/plan_tools.py`
- `agent/agent_loop.py`

---

## 7. 如何将验证流程从 SOP 软约束升级为 Runtime 硬约束？

### 问题拆解

回答这个问题时，可以按照五层展开：

1. **验证目标**：主 Agent 提出了哪些必做检查？
2. **证据采集**：如何证明验证 Agent 真的执行过检查？
3. **证据校验**：如何判断验证动作覆盖完整且结果有效？
4. **状态转换**：满足哪些条件才能进入完成态？
5. **失败恢复**：缺少验证动作和交付物真实失败应如何分别处理？

### 标准答案

我会将验证流程升级为 Runtime 管理的状态机，而不是继续依赖模型记住 SOP。

首先，为每个任务创建结构化状态文件 `status.json`：

```json
{
  "task_id": "uuid",
  "state": "verifying",
  "verify_attempt": 1,
  "plan_file": ".../plan.md",
  "verifier_task_id": "verify_uuid",
  "verdict": null,
  "failed_checks": []
}
```

合法状态转换为：

```text
exploring → planning → waiting_approval → executing → verifying → completed
                                                   ↘ repairing → verifying
                                                   ↘ failed
```

验证开始前，主 Agent 在 `verify_context.json` 中声明交付物和必做检查。Runtime 还应根据任务类型补充最低验证要求，避免主 Agent 自己遗漏检查项：

```json
{
  "required_checks": [
    {"id": "cli_normal", "type": "run_command"},
    {"id": "cli_empty_input", "type": "adversarial"}
  ]
}
```

验证 Agent 调用 `code_run`、`file_read` 等工具时，由 Runtime 在工具执行层自动记录 `evidence.jsonl`：

```json
{
  "task_id": "uuid",
  "verify_attempt": 1,
  "check_id": "cli_empty_input",
  "tool": "code_run",
  "command": "python app.py --input ''",
  "exit_code": 0,
  "stdout_summary": "...",
  "timestamp": "..."
}
```

关键点是：`evidence.jsonl` 必须由 Runtime 根据真实工具调用自动生成，不能让验证 Agent 自己填写，否则证据仍然可以被伪造。`result.md` 只作为方便人工阅读的报告，不作为唯一可信来源。

验证结束后，Runtime 对照 `required_checks` 校验：

- 每个检查项是否存在对应证据。
- 实际工具类型是否匹配。
- 命令是否真实执行，并记录退出码和关键输出。
- 是否至少完成一个边界值、异常输入、幂等性或缺失依赖等对抗性探测。
- 证据是否来自当前 `task_id`、当前验证轮次和当前验证进程。
- 不能只检查“命令调用过”，还要检查断言是否成立。

只有满足以下条件，Runtime 才允许进入完成状态：

```text
执行步骤全部完成
+ [VERIFY] 步骤存在
+ 验证 Sub Agent 已真实启动
+ required_checks 均有有效证据
+ 至少执行一个对抗性检查
+ verdict == PASS
→ completed
```

如果验证 Agent 只输出 `VERDICT: PASS`，但证据不完整，Runtime 应要求补充验证，而不是直接完成任务。

### 失败恢复

需要区分两类失败：

| 失败类型 | Runtime 动作 |
|---|---|
| 验证动作缺失 | 保持 `verifying`，要求验证 Agent 补测缺失项 |
| 交付物真实失败 | 记录 `failed_checks`，进入 `repairing` |

交付物真实失败时：

```text
VERDICT: FAIL
→ 提取 failed_checks
→ plan.md 追加 [FIX] 步骤
→ state = repairing
→ 主 Agent 只修复失败项
→ verify_attempt += 1
→ 启动新的验证 Sub Agent
→ state = verifying
```

最多自动重试两轮。仍然失败则进入 `failed` 或 `waiting_user`，请求人工介入。

### 面试收口

> 核心改进不是让 Agent 将验证过程写入 JSON，而是让 Runtime 在工具执行层自动沉淀不可跳过的结构化证据。验证结束后，Runtime 将证据与必做检查清单对齐：证据不完整就要求补测，交付物失败就进入修复循环，只有检查覆盖完整且结果为 PASS 才允许进入完成状态。SOP 继续负责指导模型如何验证，Runtime 负责决定验证结果能否被信任。

### 当前实现边界

上述设计是演进方案，当前代码尚未实现 `status.json`、`evidence.jsonl` 和 Runtime 级合法状态转换校验。现阶段的验证纪律仍主要由 `memory/plan_sop.md` 和 `memory/verify_sop.md` 约束。

---

## 60 秒综合回答

> LocalPilot 当前实现的是一个 SOP 驱动、Runtime 辅助约束的轻量级 Plan-and-Execute + Multi-Agent 编排机制。复杂任务进入 plan mode 后，会将步骤持久化到 `plan.md`，通过 checkbox 记录进度；探索和最终验证可以使用独立 Sub Agent，降低长上下文污染和确认偏误。Sub Agent 通过 `--task --bg` 作为独立进程启动，主从 Agent 使用 task 目录中的输入、输出和控制文件通信。Runtime 已经实现进程管理、任务队列、文件协议、计划标志、剩余步骤统计和部分完成拦截，但四阶段流转、主动监察和验证纪律目前仍主要依赖 SOP。下一步会补充结构化状态文件、合法状态转换校验和主动事件通知。

## 高频避坑

- 不要说“主 Agent 有后台线程定时轮询 Sub Agent 输出”。当前没有 watcher。
- 不要说“`[ROUND END]` 表示 Sub Agent 进程立即退出”。它还会等待 `reply.txt`。
- 不要说“验证 Agent 独立运行，所以验证结果可信”。独立性不等于可信度。
- 不要说“Runtime 已经实现四阶段状态机”。当前只保存 `in_plan_mode`。
- 不要说“`output.txt` 是 append 日志”。当前代码使用 `w` 模式覆盖写入。
