# Session / Client 结构化协议重构计划

## 1. 结论

优先把当前“双 Client + 双协议”收敛成一条结构化工具调用链：

```text
Agent Loop
  -> ModelClient（会话历史、工具结果配对、统一响应）
  -> Session adapter（provider 请求、流解析、重试）
  -> OpenAI Chat / Responses / Anthropic Messages
```

重构完成后，不再把工具定义、工具调用或工具结果编码进普通文本，也不再从模型正文中猜测工具调用。Provider 不支持原生工具调用时应返回明确的能力错误，不再降级为文本协议。

建议保留 `<summary>` 作为工作记忆约定，但把它从 `core/client.py` 移回系统提示词策略；本计划删除的是 `<tool_use>`、`<tool_call>`、`<tool_result>` 传输协议及松散 JSON 猜测逻辑。

## 2. 当前实现判断

### 2.1 文本协议实际分布

| 位置 | 当前职责 | 问题 |
| --- | --- | --- |
| `core/client.py:45-208` | `ToolClient` 构造 `=== USER ===` 文本、注入工具 JSON、解析 XML/松散 JSON | 整个模块接口与实现都围绕文本协议，删除后复杂度会直接消失 |
| `core/session.py:564-585` | `BaseSession.ask()` 接收字符串，并把结构化 `tool_use` 再序列化为 XML | 形成“结构化 → 文本”转换 |
| `core/session.py:687-699` | native 响应没有工具块时，再解析正文中的工具和 thinking 标签 | 让 native 链路仍隐式依赖文本协议 |
| `core/client.py:256-269` | 缺失 tool id 时，把结果包装成 `<tool_result>` 文本 | 破坏结构化历史的不变量 |
| `agent/agent_runtime.py:65-86` | 根据配置变量名选择 `ToolClient` 或 `NativeToolClient` | 配置命名决定协议，运行时存在两套行为 |
| `agent/agent_loop.py:35,135-136` | 操作文本协议专属的 `last_tools` 缓存 | Agent Loop 泄漏 Client 实现细节 |
| `agent/agent_loop.py:178-179` | 从输出中清理文本工具标签 | 上游协议泄漏到展示逻辑 |
| `core/context.py:27-31` | 压缩正文里的工具标签 | 历史模块同时维护结构化块和旧文本格式 |
| `tests/test_session.py:318-342,475-503` | 固化文本解析和 native 降级行为 | 删除协议时必须反向改写这些断言 |
| `README.md:20,249-255` | 把文本协议作为公开配置能力 | 需要给出迁移说明 |

### 2.2 关键架构问题

1. `ToolClient` 是浅模块：调用方必须理解工具提示词缓存、XML 格式、弱 JSON 解析和历史拼接；删除它不会把有价值的复杂度转移给调用方。
2. `NativeToolClient` 有应保留的深度：它负责 system prompt、工具结果配对、pending tool id 和统一响应；这些行为删除后会散落到 Agent Loop 与各 Session。
3. `core/session.py` 反向依赖 `core.client` 中的 `MockResponse` / `MockToolCall`，导致 transport 模块依赖调用侧实现。
4. Session 同时拥有 provider 适配、HTTP/SSE、历史、协议转换和 fallback。历史与请求参数通过可变属性广播，`MixinSession` 因而必须区分 native/non-native 两组。
5. `Mock*` 类型其实是生产协议对象，并非测试替身；`arguments` 先转 JSON 字符串、Agent Loop 再 `json.loads()`，制造了无意义的往返。

### 2.3 当前测试基线

仓库当前不能用测试证明此链路安全：

- `requirements.txt` 未声明 `pytest`。
- `python -m unittest discover -s tests -p 'test_session.py'` 在收集阶段失败：测试仍从 `core.session` 导入已经移到 `core.client` 的类型。
- `python -m unittest discover -s tests -p 'test_llm_client.py'` 在收集阶段失败：测试引用已不存在的 `core.llm_client`。
- `tests/test_session.py` 还保留旧 LiteLLM 行为，与当前直接 HTTP/SSE 实现不一致。

因此第一阶段必须先建立可运行的特征测试，不能直接删除旧分支。

## 3. 目标 Module 与 Interface

### 3.1 统一领域对象

新增无 provider 倾向的协议类型，例如 `core/model_types.py`：

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ModelResponse:
    text: str
    thinking: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str
    raw: Any

@dataclass(frozen=True)
class ModelRequest:
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...]
```

约束：

- `ToolCall.arguments` 在内部始终是字典，不再二次 JSON 编解码。
- 每个工具调用进入 Agent Loop 前必须有稳定 id。
- 正文只承载正文；工具调用和工具结果只能存在于结构化字段。
- provider 原始响应只允许保存在 `raw`，不能成为控制流输入。

### 3.2 单一 Client

把 `NativeToolClient` 深化并改名为 `ModelClient`（迁移期可保留别名）：

```python
chat(messages, tools) -> Generator[str, None, ModelResponse]
```

Client 负责：

- 维护规范化会话历史；
- 合并本轮 user 内容与结构化 tool result；
- 校验 pending tool id；
- 生成缺失 id 或返回明确协议错误；
- 更新历史并返回统一 `ModelResponse`；
- 记录规范化请求/响应日志。

Client 不负责：

- provider URL、headers、payload；
- SSE/JSON 事件解析；
- 文本标签或松散 JSON 解析；
- 根据模型名选择协议。

### 3.3 统一 Session seam

所有 Session adapter 实现同一个结构化接口：

```python
stream(request: ModelRequest) -> Generator[str, None, ModelResponse]
```

Session 负责：

- 把规范化消息和工具 schema 编码为 provider payload；
- HTTP、重试、usage 和流事件解析；
- 把 provider 响应规范化为 `ModelResponse`；
- provider 拒绝工具 schema 时返回明确错误。

建议保留的 adapter：

- `OpenAISession`：OpenAI-compatible Chat Completions / Responses；
- `AnthropicSession`：标准 Anthropic Messages；
- `ClaudeCodeSession`：仅封装 Claude Code 专用 headers、metadata 和 system 行为；
- `FallbackSession`：在相同 Session interface 上切换 adapter。

这样 `FallbackSession` 不再需要 native/non-native 分组，也不再广播 `system`、`tools`、`history` 等可变属性。

## 4. 分阶段实施计划

### 阶段 0：恢复测试基线

目标：先证明当前真正要保留的结构化行为。

1. 修复 `tests/test_session.py` 导入，删除 LiteLLM 时代的假对象。
2. 删除或重写 `tests/test_llm_client.py`，让测试指向当前 `core.config` / `core.client`。
3. 使用标准库 `unittest`，避免为本次重构额外引入测试框架。
4. 增加四组离线 fake transport 特征测试：
   - OpenAI Chat 流式与非流式；
   - OpenAI Responses 流式与非流式；
   - Anthropic Messages 流式与非流式；
   - 多工具调用、工具结果回灌、thinking、usage。
5. 将“native 拒绝 tools 后退回文本协议”的测试改为“返回明确 capability error”。

验收：相关测试可收集、可离线运行；旧文本协议测试被标记为待删除而非继续维护。

### 阶段 1：建立规范化类型

目标：切断 `session -> client` 的反向依赖。

1. 新增 `core/model_types.py`，定义 `ModelRequest`、`ModelResponse`、`ToolCall` 和消息块类型。
2. 把 `MockFunction`、`MockToolCall`、`MockResponse` 替换为生产类型。
3. 修改 Agent Loop 直接读取 `ToolCall.name` 与 `ToolCall.arguments`。
4. 把 provider 参数 JSON 的解析限制在 Session adapter 内；解析失败返回结构化协议错误。

验收：

- `core/session.py` 不再导入 `core.client`；
- Agent Loop 不再对工具参数执行 `json.loads()`；
- 单元测试覆盖错误参数与缺失 id。

### 阶段 2：统一结构化 Session interface

目标：让所有 provider 路径都原生携带 tools。

1. 把 `BaseSession.ask(prompt: str)` 改为结构化 `stream(ModelRequest)`。
2. 删除 `BaseSession.ask()` 中把 `tool_use` 重新输出为 XML 的代码。
3. 为标准 `ClaudeSession` 请求补齐原生 tools payload。
4. 让 `LLMSession`、`NativeOAISession` 共用 OpenAI Chat / Responses 编码与解析。
5. 保留 Claude Code 特殊认证/headers 为独立 adapter 行为，不再以“native”表示是否支持工具调用。
6. 删除 `NativeClaudeSession.ask()` 中正文 `<tool_use>` 和 `<thinking>` fallback。
7. provider 拒绝 tools 时抛出带 provider、model、mode 的 `ToolCapabilityError`。

验收：四种现有 Session 配置都通过同一结构化请求/响应测试；正文中的伪造 `<tool_use>` 被当作普通文本，不会触发工具。

### 阶段 3：合并 Client

目标：只保留一个对 Agent Loop 的 interface。

1. 以 `NativeToolClient` 为基础建立 `ModelClient`。
2. 将历史所有权从 Session 移到 Client，Session adapter 只接收本次完整 `ModelRequest`。
3. 只接受结构化 tool result；缺失 id 时生成稳定 id 或返回协议错误，禁止 `<tool_result>` 文本 fallback。
4. 删除 `ToolClient`、`_build_protocol_prompt()`、`_prepare_tool_instruction()`、`_parse_mixed_response()`。
5. 删除 `_parse_text_tool_calls()`、`tryparse()`、`last_tools`、`total_cd_tokens`。
6. 将 `<summary>` 提示约定留在 `assets/sys_prompt*.txt`，删除 Client 内重复的 `THINKING_PROMPT_*`。
7. 迁移期可以导出 `NativeToolClient = ModelClient`，一个版本后删除别名。

验收：`agent_runner_loop()` 只依赖 `ModelClient.chat()` 和 `ModelResponse`，不再读写任何 Client 私有缓存。

### 阶段 4：收口 runtime 与 fallback

目标：配置不再选择文本协议。

1. `agent/agent_runtime.py` 中所有 OpenAI/Claude 配置统一包装为 `ModelClient(session)`。
2. 第一轮保留现有配置变量名规则，避免同时破坏用户配置；`native` 只映射具体 transport profile，不再映射 Client 类型。
3. `MixinSession` 改为 `FallbackSession`，直接组合实现统一 interface 的 adapters。
4. 删除 native/non-native 同组断言和 `__setattr__` 广播。
5. `next_llm()` 只迁移 Client 的规范化历史，并删除 `last_tools` 重置。

验收：OpenAI 与 Anthropic adapter 可以在 fallback 中组合；切换模型后历史中的工具调用/结果配对保持合法。

### 阶段 5：删除外围兼容代码

目标：仓库不再承认文本工具协议。

1. 删除 `agent/agent_loop.py` 中 `last_tools` 操作和文本工具标签清理。
2. 删除 `core/context.py` 对正文 `<tool_use>/<tool_result>` 的专门压缩；保留结构化 block 压缩。
3. 更新 `README.md`：删除文本协议配置说明，补充原生工具能力要求和迁移错误。
4. 更新手工 smoke 脚本，只构造结构化请求。
5. 全仓搜索并清理文本工具标签、弱 JSON 解析和旧类名。

验收：

```bash
rg -n '<tool_(use|call|result)>|_parse_text_tool_calls|tryparse|last_tools|total_cd_tokens' \
  core agent tests README.md
```

除迁移说明或专门的“正文不应触发工具”负向测试外无命中。

### 阶段 6：完整验证

离线验证：

```bash
python -m unittest discover -s tests
python -m compileall core agent tools
```

协议矩阵：

| 维度 | 用例 |
| --- | --- |
| Provider | OpenAI Chat、OpenAI Responses、Anthropic Messages、Claude Code profile |
| 输出 | 纯文本、thinking + 文本、单工具、多工具 |
| 结果 | 完整 tool result、缺失 id、重复 id、工具异常 |
| 传输 | stream / non-stream、SSE 中断、重试后成功 |
| 能力 | provider 接受 tools、明确拒绝 tools |
| fallback | 同 provider、跨 provider、spring-back |
| 历史 | 裁剪前后 tool call/result 配对、模型切换 |

可选在线 smoke：

1. 每个已配置 provider 执行一次“两轮：调用只读工具 → 回灌结果 → 最终回答”。
2. 检查请求日志中 tools 是结构化字段。
3. 检查正文出现 `<tool_use>` 字样时不会执行工具。

## 5. 建议提交序列

1. `test: restore session and client characterization baseline`
2. `refactor: add canonical model request and response types`
3. `refactor: make all sessions use structured tool calls`
4. `refactor: collapse clients into ModelClient`
5. `refactor: unify runtime and fallback session selection`
6. `chore: remove text tool protocol compatibility code`
7. `docs: document native tool capability requirement`

每个提交都运行相关 `unittest`；第 3、4 个提交是核心迁移点，不建议合并为一个大提交。

## 6. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 某些 OpenAI-compatible 网关不支持原生 tools | 启动或首请求时明确报 capability error；不恢复文本 fallback |
| 流式工具参数被拆成多个 delta | adapter 内按 call index/id 聚合，并以离线 SSE fixture 覆盖 |
| 工具调用 id 缺失导致结果无法配对 | 规范化入口生成稳定 id，并测试多工具顺序 |
| 迁移历史时出现孤立 tool result | Client 统一校验；`core.context.fix_messages()` 只处理结构化块 |
| Mixin 跨 provider 时消息格式不同 | fallback 始终接收 canonical `ModelRequest`，各 adapter 独立编码 |
| 重构同时改配置造成范围失控 | 第一轮保留变量名规则，仅移除协议分叉；显式 provider 配置另立后续计划 |

## 7. 完成定义

- 生产链路只有一个 Client interface、一个结构化工具协议。
- `core/session.py` 与 `core/client.py` 不包含文本工具标签的生成或解析。
- Session 不依赖 Client 的响应实现。
- Agent Loop 不知道 provider、文本协议缓存或参数 JSON 格式。
- Provider 不支持 tools 时可诊断地失败。
- 离线测试覆盖四种 transport 模式和完整两轮工具闭环。
- README 不再把文本协议列为能力或配置路径。

