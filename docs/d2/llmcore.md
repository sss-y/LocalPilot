下面是一份面向阅读源码的 `llmcore.py` 接口清单，只保留核心类、函数和方法签名，并用一句话说明每个接口的数据流转。

## **模块级函数**

### 配置加载

```python
def _load_mykeys() -> dict
```
读取 `mykey.py` 或 `mykey.json`，输出模型配置字典。

```python
def reload_mykeys() -> tuple[dict, bool]
```
重新加载配置并返回 `(配置字典, 是否发生变化)`。

```python
def __getattr__(name: str)
```
按需暴露 `mykeys`，输入属性名，输出延迟加载后的配置对象。

### context工程:压缩上下文信息

```python
def compress_history_tags(messages: list, keep_recent: int = 10, max_len: int = 800, force: bool = False) -> list
```
输入历史消息列表，压缩旧消息中的大块标签内容，输出裁剪后的消息列表。

```python
def _sanitize_leading_user_msg(msg: dict) -> dict
```
输入一条 user 消息，规整其中的 `tool_result` 块，输出可安全保留在历史开头的消息。

```python
def safeprint(*argv) -> None
```
输入任意打印参数，输出安全的标准输出副作用。

```python
def trim_messages_history(history: list, context_win: int) -> None
```
输入历史消息和上下文窗口大小，原地裁剪历史以控制上下文长度。

### 

```python
def auto_make_url(base: str, path: str) -> str
```
输入 API 基地址和路径，输出规范化后的完整请求 URL。

```python
def _parse_claude_json(data: dict)
```
输入 Claude 非流式 JSON 响应，流式产出文本片段，最终返回 content blocks。

```python
def _parse_claude_sse(resp_lines)
```
输入 Claude SSE 行流，流式产出文本片段，最终返回统一的 content blocks。

```python
def _parse_openai_sse(resp_lines, api_mode: str = "chat_completions")
```
输入 OpenAI/Responses SSE 行流，流式产出文本片段，最终返回统一的 content blocks。

```python
def _parse_openai_json(data: dict, api_mode: str = "chat_completions")
```

输入 OpenAI/Responses 非流式 JSON，流式产出文本片段，最终返回统一的 content blocks。





```python
def _try_parse_tool_args(raw: str) -> list[dict]
```

输入工具参数原始字符串，输出解析后的参数字典列表。

```python
def _record_usage(usage: dict, api_mode: str) -> None
```
输入 usage 数据和 API 模式，输出 token/cache 使用统计副作用。

```python
def _stamp_oai_cache_markers(messages: list, model: str) -> None
```
输入消息列表和模型名，原地给最近 user 消息补充缓存标记。

```python
def _stream_with_retry(sess, url: str, headers: dict, payload: dict, parse_fn)
```
输入会话对象、请求参数和解析器，负责请求重试并流式输出模型结果块。

```python
def _openai_stream(sess, messages: list)
```
输入会话对象和内部消息列表，输出 OpenAI 兼容接口的流式解析结果。

```python
def _prepare_oai_tools(tools: list, api_mode: str = "chat_completions") -> list
```
输入内部工具 schema，输出适配 OpenAI/Responses API 的工具定义。

```python
def _to_responses_input(messages: list) -> list
```
输入内部消息列表，输出 OpenAI Responses API 的 `input` 结构。

```python
def _msgs_claude2oai(messages: list) -> list
```
输入内部 Claude-block 风格消息，输出 OpenAI 风格消息列表。

```python
def _keep_claude_block(b) -> bool
```
输入单个 block，输出该 block 是否应保留。

### 

```python
def _drop_unsigned_thinking(messages: list) -> list
```
输入消息列表，去掉无签名 thinking block，输出清洗后的消息列表。

```python
def _ensure_thinking_blocks(messages: list, model: str) -> list
```
输入消息列表和模型名，为特定模型补齐 thinking block，输出修正后的消息列表。

```python
def _fix_messages(messages: list) -> list
```
输入消息列表，修复 role 交替和 tool_use/tool_result 配对，输出兼容 Claude 的消息列表。

```python
def openai_tools_to_claude(tools: list) -> list
```
输入 OpenAI function tool schema，输出 Claude `input_schema` 风格工具定义。

```python
def _parse_text_tool_calls(content: str) -> tuple[list, str]
```
输入纯文本回复，提取文本中的工具调用并返回 `(tool_calls, 剩余文本)`。

```python
def _write_llm_log(label: str, content: str) -> None
```
输入日志标签和内容，输出写入 `model_responses_<pid>.txt` 的副作用。

```python
def tryparse(json_str: str) -> dict
```
输入宽松 JSON 字符串，输出尽可能修复后的解析结果。

---

**类：`BaseSession`**

```python
class BaseSession:
    def __init__(self, cfg: dict)
```
输入单个模型配置字典，初始化会话级参数和历史状态。

```python
def _apply_claude_thinking(self, payload: dict) -> None
```
输入请求 payload，原地补充 Claude 的 thinking/reasoning 配置。

```python
def ask(self, prompt: str)
```
输入纯文本 prompt，写入 session history，调用底层模型并流式输出文本，最终把响应追加回历史。

---

**类：`ClaudeSession(BaseSession)`**

```python
class ClaudeSession(BaseSession):
    def raw_ask(self, messages: list)
```
输入内部消息列表，输出 Claude Messages API 的流式响应块。

```python
def make_messages(self, raw_list: list) -> list
```
输入内部历史消息，输出适配 Claude API 的消息列表。

---

**类：`LLMSession(BaseSession)`**

```python
class LLMSession(BaseSession):
    def raw_ask(self, messages: list)
```
输入内部消息列表，输出 OpenAI 兼容接口的流式响应块。

```python
def make_messages(self, raw_list: list) -> list
```
输入内部历史消息，输出适配 OpenAI 的消息列表。

---

**类：`NativeClaudeSession(BaseSession)`**

```python
class NativeClaudeSession(BaseSession):
    def __init__(self, cfg: dict)
```
输入模型配置字典，初始化原生 Claude 会话及设备/会话标识。

```python
def raw_ask(self, messages: list)
```
输入 block 风格消息列表，输出原生 Claude tool-calling 响应块。

```python
def ask(self, msg: dict)
```
输入单条 block 风格消息，写入历史并调用原生 Claude，输出统一的 `MockResponse`。

---

**类：`NativeOAISession(NativeClaudeSession)`**

```python
class NativeOAISession(NativeClaudeSession):
    def raw_ask(self, messages: list)
```
输入内部 block 风格消息，输出基于 OpenAI 接口的原生工具调用响应块。

---

**类：`MockFunction`**

```python
class MockFunction:
    def __init__(self, name: str, arguments: str)
```
输入函数名和参数字符串，封装成统一的函数调用对象。

---

**类：`MockToolCall`**

```python
class MockToolCall:
    def __init__(self, name: str, args, id: str = '')
```
输入工具名、参数对象和可选 id，输出统一的工具调用对象。

---

**类：`MockResponse`**

```python
class MockResponse:
    def __init__(self, thinking: str, content: str, tool_calls: list, raw: str, stop_reason: str = 'end_turn')
```
输入 thinking、文本内容、工具调用和原始响应，输出统一的响应对象。

```python
def __repr__(self) -> str
```
输入当前对象状态，输出简化调试字符串。

---

**类：`ToolClient`**

```python
class ToolClient:
    def __init__(self, backend, auto_save_tokens: bool = True)
```
输入底层 backend session，初始化文本协议式工具调用客户端。

```python
def chat(self, messages: list, tools: list | None = None)
```
输入内部消息列表和工具 schema，构造完整文本协议 prompt，输出统一的 `MockResponse`。

```python
def _prepare_tool_instruction(self, tools: list | None) -> str
```
输入工具 schema，输出插入 prompt 的工具调用协议说明文本。

```python
def _build_protocol_prompt(self, messages: list, tools: list | None) -> str
```
输入消息列表和工具 schema，输出完整拼接后的文本 prompt。

```python
def _parse_mixed_response(self, text: str) -> MockResponse
```
输入模型返回的纯文本，输出解析后的统一响应对象。

---

**类：`MixinSession`**

```python
class MixinSession:
    def __init__(self, all_sessions: list, cfg: dict)
```
输入候选 session 列表和混合配置，初始化多模型回退会话。

```python
def __getattr__(self, name: str)
```
输入属性名，代理访问当前主 session 的同名属性。

```python
def __setattr__(self, name: str, value) -> None
```
输入属性和值，把关键配置广播到所有子 session。

```python
@property
def primary(self)
```
输出当前主 session。

```python
def _pick(self) -> int
```
输出当前应优先使用的 session 索引。

```python
def _raw_ask(self, *args, **kwargs)
```
输入底层请求参数，按回退策略调用多个 session，输出成功的流式响应。

---

**类：`NativeToolClient`**

```python
class NativeToolClient:
    @staticmethod
    def _thinking_prompt() -> str
```
输出当前语言下的统一 thinking/system prompt 模板。

```python
def __init__(self, backend)
```
输入 native backend，会自动设置系统提示并初始化 pending tool ids。

```python
def set_system(self, extra_system: str) -> None
```
输入额外 system prompt，更新 backend 的最终系统提示。

```python
def chat(self, messages: list, tools: list | None = None)
```
输入内部消息列表和工具 schema，构造 block 风格请求并输出原生响应对象。

如果你愿意，我还可以继续给你补一版“**最小阅读路径**”，也就是只保留真正值得优先读的 8 到 10 个接口。

## 待处理函数

| **原源码内容**             | **新文件**              | **处理方式**                       |
| -------------------------- | ----------------------- | ---------------------------------- |
| _load_mykeys               | config.py               | 保留并简化                         |
| reload_mykeys              | config.py               | 保留                               |
| __getattr__                | 可不保留                | 用显式配置加载替代                 |
| compress_history_tags      | history.py              | 重点仿写                           |
| _sanitize_leading_user_msg | history.py              | 保留                               |
| trim_messages_history      | history.py              | 重点仿写                           |
| _fix_messages              | history.py              | 保留                               |
| _drop_unsigned_thinking    | history.py 或后置       | 第一版可后置                       |
| _ensure_thinking_blocks    | history.py 或后置       | 第一版可后置                       |
| MockFunction               | schema.py               | 保留                               |
| MockToolCall               | schema.py               | 保留                               |
| MockResponse               | schema.py               | 保留                               |
| _parse_text_tool_calls     | tool_protocol.py        | 必须保留                           |
| tryparse                   | tool_protocol.py        | 必须保留                           |
| ToolClient                 | sessions/tool_client.py | 保留并简化                         |
| NativeToolClient           | 后置                    | 第一版可不做                       |
| _write_llm_log             | logging.py              | 必须保留                           |
| _record_usage              | logging.py              | 改为消费 LiteLLM usage             |
| BaseSession                | sessions/base.py        | 保留抽象接口                       |
| LLMSession                 | litellm_session.py      | 用 LiteLLM 重写                    |
| ClaudeSession              | litellm_session.py      | 合并到 LiteLLMSession              |
| NativeClaudeSession        | 后置                    | 第一版不做                         |
| NativeOAISession           | 后置                    | 第一版不做                         |
| MixinSession               | fallback_session.py     | 极简 fallback                      |
| auto_make_url              | 删除                    | LiteLLM 接管                       |
| _parse_claude_json         | 删除                    | LiteLLM 接管                       |
| _parse_claude_sse          | 删除                    | LiteLLM 接管                       |
| _parse_openai_json         | 删除                    | LiteLLM 接管                       |
| _parse_openai_sse          | 删除                    | LiteLLM 接管                       |
| _stream_with_retry         | 删除                    | LiteLLM 接管                       |
| _openai_stream             | 删除                    | LiteLLM 接管                       |
| _to_responses_input        | 删除                    | LiteLLM 接管                       |
| _msgs_claude2oai           | 后置                    | 第一版统一 OpenAI messages         |
| openai_tools_to_claude     | 后置                    | LiteLLM + OpenAI schema 时暂不需要 |

