# LocalPilot Agent Runtime 面试题与标准答案

本文基于当前 LocalPilot 实现整理，重点覆盖 Agent Runtime 的控制协议、异常恢复、并发边界、上下文管理和 Provider 适配。

回答时优先讲清楚数据如何流转。不要把队列等同于并行，不要把 SOP 约束说成 Runtime 强制逻辑。

---

## 7. 为什么工具不直接返回字符串，而要返回 `StepOutcome`？

### 标准答案

LocalPilot 使用 `StepOutcome(data, next_prompt, should_exit)` 作为工具层和 Agent Loop 之间的控制协议。

```python
@dataclass
class StepOutcome:
    data: Any
    next_prompt: Optional[str] = None
    should_exit: bool = False
```

三个字段的职责分别是：

| 字段 | 作用 |
|---|---|
| `data` | 保存工具执行结果，例如文件内容、命令输出或错误信息 |
| `next_prompt` | 决定当前任务是否继续，并为下一轮模型调用提供工作记忆锚点 |
| `should_exit` | 显式提前退出自主执行流程，主要用于 `ask_user` |

以 `file_read` 为例：

```text
模型请求 file_read
→ Handler 执行工具
→ 文件内容放入 StepOutcome.data
→ agent_runner_loop 将 data 收集为 tool_result
→ next_prompt 放入 synthetic user message 的 content
→ Client 按底层协议格式化消息
→ 再次调用模型
```

`next_prompt` 不只是普通提示词。它会逐步合并：

- 最近的摘要历史
- 当前执行轮数
- `key_info`
- Plan 模式提示
- `_intervene` 和 `_keyinfo` 控制文件中的内容

如果 `next_prompt` 为空或 `None`，Agent Loop 将当前任务视为已完成。`should_exit=True` 则表示主动中断自主执行，例如模型调用 `ask_user`，把决策交还用户。

### 面试加分点

> `StepOutcome` 让工具不只是返回数据，还可以影响 Agent 的控制流，因此工具是 Agent 状态机的一部分，而不是简单的函数集合。

### 代码锚点

- `tools/base.py::StepOutcome`
- `tools/base.py::BaseHandler.dispatch()`
- `agent/agent_loop.py::agent_runner_loop()`
- `tools/handler.py::_get_anchor_prompt()`

---

## 8. 工具内部抛出异常后，Runtime 会直接崩溃吗？

### 标准答案

普通工具异常不会直接导致 Agent Runtime 崩溃。

`BaseHandler.dispatch()` 会捕获普通 `Exception`，记录日志，并降级为可恢复的 `StepOutcome`：

```python
return StepOutcome(
    {"status": "error", "msg": user_msg},
    next_prompt="\n"
)
```

因为 `next_prompt` 非空，Agent Loop 会继续运行。错误字典会作为 `tool_result` 回传模型，模型可以根据错误调整参数、换工具或请求用户协助。

链路如下：

```text
工具抛出普通异常
→ dispatch 捕获异常并记录 tool_exception
→ 返回错误 StepOutcome
→ 错误作为 tool_result 回流模型
→ 模型决定恢复策略
```

`KeyboardInterrupt` 和 `SystemExit` 不属于可恢复工具错误。代码会重新抛出，不会把它们包装成 `StepOutcome`：

```python
except (KeyboardInterrupt, SystemExit):
    raise
```

task 模式下写入 `_stop` 时，`agentmain.py` 会调用 `abort()`：

```python
self.stop_sig = True
self.handler.code_stop_signal.append(1)
```

如果 `code_run` 正在执行命令子进程，它会每秒检查停止信号，并调用：

```python
process.kill()
```

### 当前边界

中止链路不是完全实时的。如果模型请求正在阻塞，并且暂时没有生成新的 chunk，`agentmain.py` 可能无法立即消费 `_stop`。

### 代码锚点

- `tools/base.py::BaseHandler.dispatch()`
- `agent/agentmain.py::MyAgent.abort()`
- `tools/code_tools.py::code_run()`

---

## 9. `task_queue` 是否意味着同一个 Agent 可以并行处理多个任务？

### 标准答案

不能。`task_queue` 解决的是任务入口统一和串行消费，不等于并行执行。

`MyAgent.put_task()` 会将任务放入队列：

```python
self.task_queue.put({
    "query": query,
    "source": source,
    "metadata": metadata,
    "output": display_queue,
})
```

但 `MyAgent.run()` 只有一个工作线程：

```python
while True:
    task = self.task_queue.get()
    ...
    gen = agent_runner_loop(...)
```

当前任务结束后，才会调用 `task_done()` 并处理下一项。因此同一个 `MyAgent` 实例是串行执行的。

不能简单地为每个任务增加一个线程，因为实例中存在共享状态：

```python
self.handler
self.llmclient
self.llmclient.backend.history
self.stop_sig
self.task_dir
```

直接并发会导致：

- 不同任务污染同一会话历史
- 一个任务的 `_stop` 误杀另一个任务
- 后启动任务覆盖 `self.handler`
- task 输出无法稳定归属

当前 Multi-Agent 协作主要通过独立进程实现隔离。真正支持并发时，应以 `task_id` 作为边界：

```text
task_id
→ 独立 Agent 实例
→ 独立 Session 和 history
→ 独立 Handler
→ 独立工作目录
→ 独立停止信号
```

再由 Supervisor 统一收集状态和结果。

### 面试加分点

> 队列提供的是调度秩序，不是并行能力。并发的前提是状态隔离。

### 代码锚点

- `agent/agentmain.py::MyAgent.put_task()`
- `agent/agentmain.py::MyAgent.run()`

---

## 10. 连续执行几十轮工具调用后，如何控制上下文增长？

### 标准答案

LocalPilot 使用三层信息结构和两级压缩策略。

### 三层信息结构

**第一层：Session 完整消息历史**

`backend.history` 保存协议级用户消息、助手消息、工具调用和工具结果。它用于保持模型对话连续性。

**第二层：Handler 摘要历史**

每轮结束时，`turn_end_callback()` 从模型回复提取 `<summary>`。如果模型遗漏摘要，则根据本轮工具调用生成兜底摘要。

```python
summary = smart_format(summary, max_str_len=100)
self.history_info.append(f"[Agent] {summary}")
```

`_get_anchor_prompt()` 每轮注入最近 `40` 条摘要：

```python
history_text = "\n".join(self.history_info[-40:])
```

这是一种低成本工作记忆锚点，不是完整消息历史的替代品。

**第三层：`key_info` 短期便签**

`key_info` 保存长任务中的关键约束、路径、风险和下一步计划。它既可以由模型调用工具更新，也可以由外部通过 `_keyinfo` 注入。

### 两级压缩策略

请求模型前，Session 会调用：

```python
trim_messages_history(self.history, self.context_win)
```

**L1 轻量压缩**

每次都会尝试调用 `compress_history_tags()`，但函数内部有节流，实际每 `5` 次调用执行一次。默认保留最近 `10` 条消息不动，对较旧消息执行：

- `<thinking>`、`<tool_use>`、`<tool_result>` 内容保留首尾并截断
- `<history>`、`<key_info>` 替换为 `[...]`
- 结构化 `tool_result` 和工具参数中的长字符串截断

**L2 强压缩**

当估算成本超过：

```python
context_win * 3
```

Runtime 会强制压缩较旧消息，保留最近 `4` 条；如果仍然超限，则驱逐更早的消息，直到：

```python
cost <= context_win * 3 * 0.6
```

或者只剩最少 `5` 条消息。

裁剪后还会修复首条用户消息，避免出现孤立的 `tool_result`。

### 当前边界

压缩能够降低上下文成本，但必然存在信息损失：

- 旧工具输出中的关键细节可能被截断
- 摘要可能遗漏失败原因
- `key_info` 依赖模型主动维护
- 旧消息被驱逐后，无法仅靠摘要恢复完整证据

因此摘要和便签用于保护关键约束，但不能替代原始日志和产物文件。

### 代码锚点

- `core/context.py::compress_history_tags()`
- `core/context.py::trim_messages_history()`
- `core/context.py::_sanitize_leading_user_msg()`
- `tools/handler.py::_get_anchor_prompt()`
- `tools/handler.py::turn_end_callback()`

---

## 11. 为什么同时存在 `ToolClient`、`NativeToolClient` 和 Session？

### 标准答案

这三层用于隔离 Agent Runtime 的统一控制流与不同 Provider 的协议差异。

### 职责划分

| 层级 | 职责 |
|---|---|
| `agent_runner_loop()` | 统一控制模型轮次、工具派发和 `StepOutcome` 流转 |
| Client | 将统一的 Agent 消息转换为文本协议或原生工具协议 |
| Session | 维护历史、裁剪上下文、发起 HTTP 请求、处理流式响应、重试和 Provider 格式转换 |

### 文本工具协议：`ToolClient`

部分模型或接口没有接入原生工具调用。`ToolClient` 会把工具定义拼接进提示词，并要求模型输出：

```text
<tool_use>{"name": "file_read", "arguments": {...}}</tool_use>
```

工具结果也会序列化为：

```text
<tool_result>...</tool_result>
```

随后 Client 解析模型文本中的 `<tool_use>`，转换为统一的 `MockToolCall`，交给 Agent Loop。

### 原生工具协议：`NativeToolClient`

对于支持原生工具调用的接口，`NativeToolClient` 会直接传递结构化工具 schema。工具执行结果会转换为：

```python
{
    "type": "tool_result",
    "tool_use_id": "...",
    "content": "..."
}
```

并放入下一条 `role="user"` 的消息中。这符合原生工具调用协议。

`NativeToolClient` 还维护 `_pending_tool_ids`。如果某个工具调用缺少结果，会补充空 `tool_result`，降低消息协议错误风险。

### Session 层

Session 负责 Provider 细节，例如：

- Claude 与 OpenAI 兼容接口的请求格式
- streaming 解析
- Responses API 与 Chat Completions 差异
- retry
- history 管理
- 上下文裁剪
- 工具调用和 thinking block 的格式修复

### 为什么不全部塞进 Agent Loop？

如果把 Provider 差异写入 Agent Loop，主循环会被大量协议判断污染。当前设计让 Agent Loop 只处理统一抽象：

```text
模型回复
→ tool_calls
→ Handler.dispatch()
→ StepOutcome
→ 下一轮消息
```

这样新增 Provider 时，主要修改 Client 或 Session，不需要改动核心决策循环。

### 面试加分点

> Agent Loop 关注行为闭环，Client 关注工具协议，Session 关注模型通信。分层的价值是隔离变化。

### 代码锚点

- `core/client.py::ToolClient`
- `core/client.py::NativeToolClient`
- `core/session.py::BaseSession`
- `core/session.py::ClaudeSession`
- `core/session.py::LLMSession`
- `core/session.py::NativeClaudeSession`
- `core/session.py::NativeOAISession`

---

## 90 秒综合回答

> LocalPilot 的核心是一个工具调用驱动的 Agent Runtime。Agent Loop 不直接依赖某个模型 Provider，而是接收统一的模型回复和工具调用，再通过 Handler 分发工具。工具返回的不是单纯字符串，而是 `StepOutcome`：`data` 保存工具结果，`next_prompt` 决定是否继续执行，`should_exit` 用于显式中断自主流程。普通工具异常会降级为错误 `StepOutcome` 回流模型，使模型可以自恢复；键盘中断和停止信号则走控制路径。
>
> Runtime 内部使用 `task_queue` 统一接收用户、task 和 reflect 任务，但单个 Agent 实例仍然串行执行。多 Agent 隔离目前主要依赖独立进程。为了控制长任务上下文，Session 保存完整消息历史并进行分级压缩，Handler 额外注入最近摘要和 `key_info` 短期便签。Provider 差异被隔离在 Client 和 Session：不支持原生工具调用时使用文本标签模拟，支持时直接传结构化 `tool_use` 和 `tool_result`。因此 Agent Loop 可以保持稳定，新增 Provider 时主要修改适配层。

## 高频避坑

- 不要说 `data` 有固定三种类型。`data` 是任意工具结果。
- 不要说 `next_prompt=None` 表示等待用户。它表示当前任务正常结束。
- 不要说 `should_exit` 负责键盘中断。它主要用于 `ask_user`。
- 不要说队列天然支持并行。当前单个 `MyAgent` 实例串行消费任务。
- 不要把 `key_info` 称为长期记忆。它是短期工作便签。
- 不要说轻量压缩每轮都会实际改写历史。内部有每 `5` 次调用一次的节流。
- 不要把文本工具标签和原生结构化工具协议混为一谈。
