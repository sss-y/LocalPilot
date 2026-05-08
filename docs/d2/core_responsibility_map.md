# Core 模块职责图

```text
config.py
  |
  +-- 读取 mykey.py / mykey.json
  +-- 输出模型配置 dict
  v
session.py
  |
  +-- 根据配置构造 Session
  +-- 用 LiteLLM 发起模型请求
  +-- 统一解析 text / thinking / tool_use
  +-- 提供 LLMSession / ClaudeSession / NativeClaudeSession / MixinSession
  v
logging.py
  |
  +-- 写 Prompt / Response / Usage 日志
  v
temp/model_responses/model_responses_<pid>.txt

context.py
  |
  +-- 压缩历史
  +-- 修复消息配对
  +-- 控制上下文长度
  |
  +-- 被 session.py 调用

tool_protocol.py
  |
  +-- 宽松 JSON 解析
  +-- 提取 <thinking>
  +-- 从纯文本中提取 <tool_use> / <tool_call>
  |
  +-- 被 session.py / ToolClient / NativeClaudeSession 调用

schema.py
  |
  +-- MockFunction
  +-- MockToolCall
  +-- MockResponse
  |
  +-- 作为 session.py 的统一输出结构

client.py
  |
  +-- 预留给更薄的一层上层封装
  +-- 当前主链路能力已主要落在 session.py
```

## 当前推荐调用链

1. `core.config.reload_mykeys()` 读取配置
2. 用配置创建 `core.session` 里的某个 Session
3. 通过 `ToolClient` 或 `NativeToolClient` 发起对话
4. `session.py` 内部调用 `context.py` 做历史裁剪
5. `session.py` 内部调用 `tool_protocol.py` 做工具协议解析
6. `logging.py` 记录 Prompt / Response / Usage

## 模块边界约定

- `config.py` 只负责配置加载，不负责请求。
- `context.py` 只负责消息历史和上下文整理，不负责网络请求。
- `tool_protocol.py` 只负责文本协议解析，不负责 Session 生命周期。
- `schema.py` 只放统一数据结构。
- `session.py` 是模型适配和会话主干。
- `logging.py` 只负责落日志。
