

## message

**一、项目内部最常见的 message 字段构成**

项目内部最常见的 message 是一个 dict，常见字段有：

```python
{  "role": "system" | "user" | "assistant" | "tool" | "developer",  
 		"content": str | list[block], 
 		"tool_results": list[dict],      
 # 仅部分 user message 会带  "tool_calls": list[dict],        
 # 仅 assistant/native message 可能带 
} 
```

其中最关键的是：

- role
- content

------

**二、content 的两种主要形态**

### 1. 纯文本字符串

最简单的是：

```python
{"role": "system", "content": "你是一个执行型Agent"} 
{"role": "user", "content": "帮我读一下这个文件"} 
```

这种形式主要出现在：

- ToolClient 路线
- 传统 prompt 拼接流程
- 一些 system / user 输入场景

------

### 2. block 列表

另一种是 Claude 风格 block：

```python
{  "role": "user",  
 "content": [    {"type": "text", "text": "帮我分析这个页面"},
             		{"type": "image_url", "image_url": {"url": "..."}}  
            ] 
} 
```

或者：

```python
{  "role": "assistant",  
 "content": [    {"type": "thinking", "thinking": "...", "signature": "..."},    
             {"type": "text", "text": "..."},    
             {"type": "tool_use", 
              "id": "call_xxx", 
              "name": "file_read", 
              "input": {...}}  
            ] 
} 
```

这种形式主要出现在：

- NativeClaudeSession
- NativeOAISession
- Claude 风格内部历史
- tool_result 回填后的多 block message

------

**三、项目内部实际使用过的 block 字段**

从 llmcore.py 通读下来，block 常见类型有：

### 文本块

```
{"type": "text", "text": "..."} 
```

### thinking 块

```
{"type": "thinking", "thinking": "...", "signature": "..."} 
```

有些地方也兼容没有 signature 的 thinking，但 Claude 原生路径会清理掉未签名的。

### tool_use 块

```
{"type": "tool_use", "id": "...", "name": "tool_name", "input": {...}} 
```

### tool_result 块

```
{"type": "tool_result", "tool_use_id": "...", "content": "..."} 
```

content 也可能不是字符串，而是 text block 列表。

### image 块

Claude 风格 base64 图像：

```
{  "type": "image",  "source": {    "type": "base64",    "media_type": "image/jpeg",    "data": "..."  } } 
```

### image_url 块

OpenAI 风格图像：

```
{  "type": "image_url",  "image_url": {"url": "..."} } 
```

------

**四、项目内部“标准 message”更偏哪一种**
严格说，这个项目内部**更偏向 Claude block 风格**。

证据有几处：

1. BaseSession.ask() 里，history append 用的是：

```
{"role": "user", "content": [{"type": "text", "text": prompt}]} 
```

1. _msgs_claude2oai() 是从 Claude 风格转 OpenAI 风格，不是反过来命名。
2. NativeToolClient.chat() 合并消息时，优先假设 content 可能是 block list。

所以可以理解为：

- **内部“理想标准格式”是 block-based**
- 但为了兼容 ToolClient，项目也广泛接受纯文本字符串

## memory

`memory/` 可以分成 5 类来看：长期记忆、执行 SOP、可复用工具脚本、自主/子代理机制、L4 会话归档。下面按“文件 -> 主要功能 -> 执行时机”逐个说。

**长期记忆**
| 文件                                                         | 主要功能                                          | 执行时机                                             |
| ------------------------------------------------------------ | ------------------------------------------------- | ---------------------------------------------------- |
| [memory/global_mem_insight.txt](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/global_mem_insight.txt:1) | L1 极简索引，告诉 Agent “有哪些能力/SOP/规则存在” | 几乎每次任务启动都会被注入系统上下文                 |
| [memory/global_mem.txt](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/global_mem.txt:1) | L2 全局事实库，存环境事实、路径、配置等稳定信息   | 需要查长期环境事实，或任务完成后沉淀长期事实时       |
| [memory/memory_management_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/memory_management_sop.md:1) | 记忆写入总规范，定义 L1-L4 分层和“只记已验证信息” | 调用 `start_long_term_update` 后，或任何要修改记忆前 |
| [memory/memory_cleanup_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/memory_cleanup_sop.md:1) | L1 索引压缩和整理规则，防止记忆膨胀失真           | 整理 `global_mem_insight.txt`、做记忆瘦身时          |

**执行与规划 SOP**
| 文件                                                         | 主要功能                                      | 执行时机                                     |
| ------------------------------------------------------------ | --------------------------------------------- | -------------------------------------------- |
| [memory/plan_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/plan_sop.md:1) | 复杂任务的规划模式：探索、写 plan、执行、验证 | 任务超过 3 步、有依赖、并行或多文件协同时    |
| [memory/verify_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/verify_sop.md:1) | 独立验证标准，强调必须运行、必须有工具证据    | 计划任务收尾，或需要独立验收交付物时         |
| [memory/subagent.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/subagent.md:1) | 子代理启动、通信、Map 模式、干预文件协议      | 需要委托探索、并行处理、长任务分拆时         |
| [memory/supervisor_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/supervisor_sop.md:1) | 监察者模式，只监控和纠偏，不亲自干活          | 一个 agent 负责监督另一个 agent 时           |
| [memory/scheduled_task_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/scheduled_task_sop.md:1) | 定时任务 JSON 格式、触发条件、报告约定        | `reflect/scheduler.py` 驱动定时任务时        |
| [memory/autonomous_operation_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/autonomous_operation_sop.md:1) | 自主行动总流程：选题、执行、写报告、改 TODO   | 用户离开后触发 autonomous/reflect 自主任务时 |
| [memory/github_contribution_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/github_contribution_sop.md:1) | 给开源项目提 PR 的标准流程                    | 需要 fork、改代码、跑测试、提 PR 时          |

**Web / GUI / Vision / Mobile 能力**
| 文件                                                         | 主要功能                                             | 执行时机                                                     |
| ------------------------------------------------------------ | ---------------------------------------------------- | ------------------------------------------------------------ |
| [memory/tmwebdriver_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/tmwebdriver_sop.md:1) | 真实浏览器控制的高级特性和坑，尤其 CDP 桥            | `web_scan`/`web_execute_js` 遇到复杂页面、上传、跨 iframe、cookie、autofill 时 |
| [memory/web_setup_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/web_setup_sop.md:1) | Web 工具链初始化，安装 `tmwd_cdp_bridge` 扩展        | 首次配置浏览器控制能力、web 工具还不可用时                   |
| [memory/vision_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/vision_sop.md:1) | Vision API 使用规范，强调先 OCR/窗口枚举、禁全屏截图 | 本地 OCR 不够用，需要视觉模型理解界面时                      |
| [memory/ljqCtrl_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ljqCtrl_sop.md:1) | 鼠标键盘物理坐标、DPI、窗口激活规则                  | 需要物理点击、模拟输入、图像定位时                           |
| [memory/ocr_utils.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ocr_utils.py:1) | 本地 OCR 工具，支持区域、窗口截图识别                | 先于 vision 使用，做低成本文字读取时                         |
| [memory/ui_detect.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ui_detect.py:1) | YOLO + OCR 检测 UI 元素位置                          | 需要从截图中找控件、按钮、图标时                             |
| [memory/vision_api.template.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/vision_api.template.py:1) | Vision API 模板，支持 Claude/OpenAI/ModelScope       | 首次搭建 `vision_api.py` 能力时                              |
| [memory/adb_ui.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/adb_ui.py:1) | Android UI dump、解析节点、ADB 点击                  | 控制手机 App、读取安卓界面结构时                             |

**系统与进程工具**
| 文件                                                         | 主要功能                                    | 执行时机                                         |
| ------------------------------------------------------------ | ------------------------------------------- | ------------------------------------------------ |
| [memory/procmem_scanner.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/procmem_scanner.py:1) | 进程内存扫描，支持 hex/string/YARA 风格匹配 | 需要在进程内定位特征码、结构体、动态字段时       |
| [memory/procmem_scanner_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/procmem_scanner_sop.md:1) | 内存扫描工具的使用说明和典型场景            | 使用 `procmem_scanner.py` 前，尤其是复杂定位任务 |
| [memory/keychain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/keychain.py:1) | 本地加密保存敏感 key，并以 masked 形式使用  | 需要读取或保存密钥，但又不想明文出现在日志里时   |
| [memory/ljqCtrl.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ljqCtrl.py:1) | 实际的桌面键鼠控制库                        | 物理级桌面自动化时，由 SOP 或脚本导入调用        |

**自主任务辅助与会话归档**
| 文件                                                         | 主要功能                                         | 执行时机                                |
| ------------------------------------------------------------ | ------------------------------------------------ | --------------------------------------- |
| [memory/autonomous_operation_sop/helper.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/autonomous_operation_sop/helper.py:1) | 自主任务 API，管理 `TODO.txt`、历史、报告归档    | 自主行动开始/结束时，由自主 SOP 调用    |
| [memory/autonomous_operation_sop/task_planning.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/autonomous_operation_sop/task_planning.md:1) | 自主模式的“选题与 TODO 规划”规则                 | 没有 TODO、需要为未来自主行动生成待办时 |
| [memory/L4_raw_sessions/compress_session.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/L4_raw_sessions/compress_session.py:1) | 压缩历史会话日志，提取 `<history>`，形成 L4 归档 | 需要归档长会话、保留长期可追溯上下文时  |

**技能检索模块**
| 文件                                                         | 主要功能                                       | 执行时机                      |
| ------------------------------------------------------------ | ---------------------------------------------- | ----------------------------- |
| [memory/skill_search/SKILL.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/skill_search/SKILL.md:1) | 105K 技能卡检索的用法说明                      | 想从外部技能库找现成 skill 时 |
| [memory/skill_search/skill_search/engine.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/skill_search/skill_search/engine.py:1) | 技能搜索客户端核心，含环境检测和 API 调用      | 程序化检索 skill 时           |
| [memory/skill_search/skill_search/__main__.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/skill_search/skill_search/__main__.py:1) | CLI 入口，支持 `python -m skill_search`        | 命令行直接查技能时            |
| [memory/skill_search/skill_search/__init__.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/skill_search/skill_search/__init__.py:1) | 对外导出 `search/get_stats/detect_environment` | 被其他脚本 import 时          |

如果你想，我下一步可以把这些再整理成一张“memory 模块地图”，按 `工具调用 / 记忆 / 上下文 / agent loop / 自主执行` 五大能力重新分组，做成更适合分享的版本。

## 日志信息

这个项目里，用户发起一次对话，并不是靠数据库里的 `conversation_id` 或 `message_id` 来区分的，而是靠一组更轻量的工程约定来区分：

- **窗口/进程级别**：用当前前端进程的 `PID`
- **同一窗口中的多轮会话级别**：用同一个 `model_responses_<pid>.txt` 日志文件持续追加
- **同一窗口中的单次用户查询级别**：用日志里的 `=== Prompt ===` / `=== Response ===` 配对，以及 Prompt 内部的 `=== USER ===` / `=== ASSISTANT ===` 边界来切分

下面分几部分详细讲。

**1. 用户发起一次对话，用什么 ID 区分**
最外层的“会话窗口”标识是 **当前 Python 进程的 PID**。

日志文件写入位置在 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:852)：

```python
log_path = os.path.join(log_dir, f'model_responses_{os.getpid()}.txt')
```

这意味着：

- 每启动一个前端实例，通常就是一个新的进程
- 这个进程下所有聊天内容，默认都写进同一个日志文件
- 所以“窗口 / 前端实例 / 会话容器”的 ID，本质上就是 `pid`

例如你现在打开的这些日志：

- `model_responses_21891.txt`
- `model_responses_21741.txt`
- `model_responses_21263.txt`
- `model_responses_85603.txt`

它们分别对应不同进程，也通常对应不同窗口、不同启动实例，或者历史上不同时间启动过的前端。

**结论**：
- **多窗口区分**：靠 `PID`
- **日志文件名就是窗口级会话 ID**

**2. 当前窗口中用户发起多次查询，如何区分**
在同一个窗口里，多个查询**不会生成新的 pid，也不会生成新的单独日志文件**。它们会继续追加到当前 `model_responses_<pid>.txt` 文件里。

区分方式靠两层。

第一层：**LLM 调用轮次边界**
每次 LLM 调用都会写两段日志：

- `=== Prompt === 时间`
- `=== Response === 时间`

写入时机在 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:741) 和 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:745)：

- 发起 LLM 请求前写 `Prompt`
- 收到完整模型输出后写 `Response`

所以日志文件实际上是很多组：

```text
=== Prompt === 2026-05-05 10:00:00
...

=== Response === 2026-05-05 10:00:12
...

=== Prompt === 2026-05-05 10:00:13
...

=== Response === 2026-05-05 10:00:20
...
```

`continue_cmd.py` 里 `_pairs()` 就是按这个结构切分的，见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:19)。

第二层：**用户查询边界**
对于 `ToolClient` 路线，Prompt 本身会被拼成这样的文本结构，见 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:782)：

```text
=== USER ===
用户本轮输入1

=== ASSISTANT ===
上一轮模型输出 / 工具协议补充

=== USER ===
用户本轮输入2

=== ASSISTANT ===
...
```

所以在同一个 PID 文件里：

- 一次用户新提问，会体现在一个新的 `=== USER ===`
- 若该查询引发多轮 agent loop，则会出现多组 `Prompt/Response`
- 这些连续多轮会被视为“围绕同一个用户问题的自动续跑”

`extract_ui_messages()` 在恢复 UI 时，就是通过 `_user_text()` 判断某个 Prompt 是否包含新的真实用户输入；如果没有，就把它看成同一问题下的自动续轮，见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:242)。

**结论**：
同一窗口中多次查询，不靠新 id 区分，而靠：
- 新的 `=== USER ===` 代表一次新的用户发问
- 围绕这个发问产生的多组 `Prompt/Response` 代表这个问题的执行过程

**3. `continue_cmd.py` 的恢复功能是怎么工作的**
它做三件事：

- 找历史日志文件
- 从日志里提取可恢复会话
- 把会话恢复到 Agent backend 或前端 UI

先看“找哪些日志”。

`list_sessions(exclude_pid=None)` 会扫描：

- `temp/model_responses/model_responses_*.txt`

见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:82)。

如果传了 `exclude_pid`，会把当前窗口自己的日志排除掉：

```python
tag = f'model_responses_{exclude_pid}.txt'
files = [f for f in files if not f.endswith(tag)]
```

这就是为什么 `/continue` 默认列的是“其他窗口 / 其他历史实例”的会话，不会把自己当前正在写的日志也列进去。

然后看“怎么识别一个可恢复会话”。

每个日志文件里，`_pairs()` 先把它拆成 `(prompt, response)` 列表。然后：

- `_last_summary()` 尝试提取最近 `<summary>`，作为会话预览
- 提取不到再用 `_first_user()` 找第一条用户消息作为预览

所以 `/continue` 列表看到的是：
- 相对时间
- 轮数
- 摘要或首条用户问题

见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:167)。

**4. 会话日志中的写入内容和写入时机**
这部分很关键。

日志写入函数是 `_write_llm_log(label, content)`，见 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:852)。

写入格式固定是：

```text
=== Prompt === 2026-05-05 10:00:00
{prompt内容}

=== Response === 2026-05-05 10:00:12
{response内容}
```

写入时机：

- **Prompt 写入时机**：每次调用 `LLMClient.chat()` 前
- **Response 写入时机**：每次模型完整返回后

对于 `ToolClient.chat()`，见 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:736)：

- `_build_protocol_prompt()` 先组完整 prompt
- `_write_llm_log('Prompt', full_prompt)`
- 调模型
- `_write_llm_log('Response', raw_text)`

写入内容：

Prompt 里通常包含：

- system prompt
- tools schema 或工具状态
- 历史消息
- `=== USER ===`
- `=== ASSISTANT ===`
- tool_results
- working memory 注入内容

Response 里通常包含：

- 模型文本回复
- `<thinking>`
- `<summary>`
- `<tool_use>`
- 或最终回答

也就是说，日志里存的不是“纯聊天文本”，而是**相当接近模型真实上下文和输出的原始轨迹**。

**5. 恢复时恢复了什么内容**
`restore(agent, path)` 有两种恢复模式，见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:175)。

第一种：**完整恢复**
如果日志能被 `_parse_native_history()` 解析成标准消息结构：

- prompt 能 parse 成 JSON user message
- response 能 parse 成 assistant blocks

那么它会：

- `agent.abort()`
- `_replace_backend_history(agent, history)`

也就是直接把历史写回 `backend.history`

效果：
- 后续继续问时，LLM 真正继承原上下文
- tool 结果、assistant block 结构也能延续
- 这是最完整的恢复方式

第二种：**降级恢复**
如果日志格式不是 native，或不能完整 parse：

- 从 `chatapp_common._restore_text_pairs()` 或 `_restore_native_history()` 抽摘要
- 写入 `agent.history`

效果：
- 前端能看到“之前聊过什么”
- 但 LLM backend 不一定拿回完整原始上下文
- 更像“摘要续聊”

所以恢复内容分两层：

- **backend 级恢复**：完整结构化消息历史
- **UI/摘要级恢复**：只恢复 `[USER]: ... / [Agent] ...` 摘要线索

**6. `extract_ui_messages()` 恢复了什么**
这个函数不是给 backend 用的，而是给前端回放聊天气泡用的，见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:242)。

它会：

- 从日志里提取每次真实用户发问
- 把后续自动续轮的 assistant 输出合并成一个 assistant 气泡
- 中间插入 `LLM Running (Turn N)` 标记

所以它恢复的是：

- 用户看到的聊天记录 UI
- 而不是底层完整 prompt history

这也是 `stapp.py` 里 `/continue N` 恢复后，界面能直接重放历史对话的原因。

**7. 多窗口日志的 ID 如何区分**
多窗口区分逻辑非常直接：

- 每个窗口对应一个 Python 进程
- 每个进程写自己的 `model_responses_<pid>.txt`

因此：

- `21891`、`21741`、`21263`、`85603` 这些数字就是不同窗口/实例的日志 ID
- `continue_cmd.py` 列历史时，用 `exclude_pid=os.getpid()` 把当前窗口排除
- 所以恢复对象通常是“别的窗口”或“之前已经退出的实例”

另外还有一种“快照日志”：

见 `_snapshot_current_log()`，会生成：

```text
model_responses_snapshot_<pid>_<timestamp>_<suffix>.txt
```

用途是：

- 当你 `/new` 或切换恢复目标前
- 先把当前正在写的日志固化成一个独立可恢复文件
- 然后把当前 `model_responses_<pid>.txt` 清空

这样即使是“同一个窗口里的旧上下文”，也能变成一个独立历史会话重新被 `/continue` 找到。

**8. `/new` 和 `/continue N` 为什么能形成会话切换**
因为 `reset_conversation()` 做了完整切换动作，见 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:148)：

- 停止当前运行
- 快照当前日志
- 清空 `agent.history`
- 清空所有 backend.history
- 清空 tool cache
- 清空 handler

所以：

- `/new` = 当前窗口保留 PID，但逻辑上新开一段对话
- `/continue N` = 当前窗口仍然是这个 PID，但把上下文替换成别的历史会话

也就是说，**PID 是窗口 ID，不是单次对话 ID**。  
单次对话是靠日志内容边界和 reset/snapshot 机制来实现逻辑切换的。

**9. 一句话总结**
可以把这套机制理解成三层：

- **窗口 ID**：`PID`
- **当前窗口内的查询分段**：`=== USER ===` 边界
- **单次查询的执行轨迹**：多组 `=== Prompt === / === Response ===`

而 `continue_cmd.py` 的工作就是：

- 基于 `PID` 级日志文件发现历史会话
- 基于 `Prompt/Response` 解析会话内容
- 在“完整 backend 恢复”和“摘要 UI 恢复”之间自动选择
- 通过快照机制让同一窗口里的旧上下文也能变成可恢复历史

如果你要，我下一步可以直接给你画一张 **“日志写入与恢复时序图”**，把 `User -> Frontend -> llmcore日志 -> continue_cmd恢复` 整条链串起来。

## 定时任务

[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:1) 是这个项目的**定时反射调度模块**。它属于 `reflect/` 体系，不直接提供聊天能力，而是给 `agentmain.py --reflect ...` 这种运行模式提供“定时触发任务”的能力。

它的核心作用有两件：

- 扫描 `sche_tasks/*.json` 里的定时任务定义，判断当前是否该触发某个任务
- 定时做一次 L4 会话归档，把 `temp/model_responses` 里的原始日志压缩沉淀到 L4

你可以把它理解成一个很轻量的 cron 调度器，专门负责把“什么时候该做任务”转换成一条 prompt，再交给 Agent 去执行。

**模块在系统里的位置**
闭环大概是这样：

```text
agentmain.py --reflect reflect/scheduler.py
 |
 v
定时调用 scheduler.check()
 |
 +--> 检查 sche_tasks/*.json 是否有到点任务
 |
 +--> 检查是否要做 L4 日志归档
 |
 v
如果命中，返回一条 prompt
 |
 v
GeneraticAgent.put_task(...)
 |
 v
正常进入 AgentLoop 执行
```

**文件级变量作用**
`_lock`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:4)  
作用：端口锁，防止调度器被重复启动。它通过绑定 `127.0.0.1:45762` 来保证同一时间只有一个 scheduler 实例存活。  
执行时机：模块 import 时立即执行一次。如果重复加载，保留旧 `_lock`，避免重复绑定。

`INTERVAL = 120`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:11)  
作用：告诉 `agentmain.py` 的 reflect 模式，这个脚本每 120 秒轮询一次。  
执行时机：被 `agentmain.py --reflect reflect/scheduler.py` 读取后生效。

`ONCE = False`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:12)  
作用：表示不是一次性运行，而是持续轮询。  
执行时机：reflect 模式主循环判断是否执行一次就退出时使用。

`TASKS / DONE / _LOG`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:14)  
作用：
- `TASKS`：定时任务 JSON 所在目录 `sche_tasks/`
- `DONE`：任务完成报告目录 `sche_tasks/done/`
- `_LOG`：scheduler 自己的日志文件 `sche_tasks/scheduler.log`  
执行时机：模块加载后供所有函数复用。

`DEFAULT_MAX_DELAY = 6`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:28)  
作用：默认最大触发延迟，超过计划时间 6 小时就不再补触发，避免“过期任务”被执行。  
执行时机：任务 JSON 没写 `max_delay_hours` 时使用。

`_l4_t = 0`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:30)  
作用：记录上次做 L4 归档的时间戳。  
执行时机：`check()` 每次轮询时先看它，决定是否触发日志归档。

**函数说明**

`_parse_cooldown(repeat)`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:32)  
作用：把任务的 `repeat` 字段解析成“冷却时间”。

支持这些类型：

- `once`
- `daily`
- `weekday`
- `weekly`
- `monthly`
- `every_Nh`
- `every_Nm`
- `every_Nd`

比如：
- `daily` 返回 20 小时
- `weekly` 返回 6 天
- `once` 返回极大值，相当于永不再触发

它这里不是严格按周期返回，而是故意“略短一点”，避免时间漂移导致任务越来越晚。

执行时机：
- `check()` 发现某个任务已经过了 schedule 时间后
- 在真正触发前，用它判断“距离上次运行是否已经过了冷却期”

`_last_run(tid, done_files)`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:51)  
作用：从 `sche_tasks/done/` 目录中找某个任务 `tid` 最近一次执行完成的时间。

它依赖 done 文件命名规则：

```text
YYYY-MM-DD_HHMM_<taskid>.md
```

然后从文件名前 15 位解析时间。

执行时机：
- `check()` 在判断任务是否需要重复执行时
- 和 `_parse_cooldown()` 配合，判断冷却是否结束

`check()`  
位置：[reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:62)  
作用：这是整个模块的核心函数，也是 reflect 模式唯一要求实现的入口。

它每次被调用时会做两大类检查。

第一类：**L4 日志归档 cron**
见 [reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:63)

逻辑：
- 如果距离上次归档超过 12 小时
- 动态导入 `memory/L4_raw_sessions/compress_session.py`
- 调 `batch_process(raw_dir, dry_run=False)`
- 压缩 `temp/model_responses/` 里的原始日志

这是一个“静默后台任务”，不返回给 Agent，不生成聊天 prompt，只在 scheduler 自己的控制流里做。

执行时机：
- 每次 `check()` 被 reflect 主循环调用时先检查
- 满足 12 小时间隔时执行

第二类：**定时任务扫描与触发**
见 [reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:76)

流程是：

1. 检查 `sche_tasks/` 目录是否存在
2. 遍历所有 `*.json`
3. 解析任务配置
4. 跳过 `enabled != true` 的任务
5. 解析 `repeat` 和 `schedule`
6. `weekday` 任务在周末跳过
7. 当前时间没到 schedule 则跳过
8. 超过 `max_delay_hours` 则跳过
9. 检查 done 目录，若冷却未结束则跳过
10. 命中后，生成报告路径 `sche_tasks/done/<timestamp>_<tid>.md`
11. 拼装一条 prompt 返回给 Agent

返回 prompt 的格式大概是：

```text
[定时任务] <tid>
[报告路径] <rpt>

先读 scheduled_task_sop 了解执行流程，然后执行以下任务：

<prompt内容>

完成后将执行报告写入 <rpt>。
```

执行时机：
- 每 120 秒被 reflect 主循环调用一次
- 只要发现第一个满足条件的任务，就立即返回 prompt
- 一次 `check()` 最多触发一个任务

**这个模块什么时候运行**
它不是普通 import 后自动跑的，而是通常通过下面这种方式运行：

```bash
python agentmain.py --reflect reflect/scheduler.py
```

然后 `agentmain.py` 会：

- 动态加载这个文件
- 每隔 `INTERVAL` 秒调用一次 `check()`
- 如果 `check()` 返回字符串，就把这个字符串当作一个新任务交给 Agent 执行

所以 `scheduler.py` 的执行时机，不是“用户发消息时”，而是：

- Agent 作为后台反射进程运行时
- 定时轮询触发时
- 不依赖前端交互

**和 `reflect/autonomous.py` 的区别**
[reflect/autonomous.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/autonomous.py:1) 更像一个固定条件触发器：

- 每 1800 秒轮询一次
- 到点就返回固定 prompt：用户离开 30 分钟，执行自主任务

而 `scheduler.py` 更像一个“任务表驱动”的调度器：

- 从 `sche_tasks/*.json` 动态读取任务
- 每个任务有自己的时间、频率、延迟窗口
- 还会自动生成报告路径和完成记录

所以：

- `autonomous.py`：固定策略触发
- `scheduler.py`：配置化定时任务调度

**和 `scheduled_task_sop.md` 的关系**
[memory/scheduled_task_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/scheduled_task_sop.md:1) 是给 Agent 执行定时任务时看的 SOP。

`scheduler.py` 负责：
- 决定“该不该触发”
- 生成 prompt
- 指定报告路径

`schedule_task_sop.md` 负责：
- 告诉 Agent 收到任务后先做什么
- 如何记住报告路径
- 如何写执行报告
- done 文件为什么重要

也就是说：

- `scheduler.py` 是调度层
- `scheduled_task_sop.md` 是执行规范层

**当前文件里没有但 SOP 提到的点**
SOP 里写了 `scheduler.health_check()`，但我查看当前 [reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:1) 代码，**这个函数现在并不存在**。  
所以这里要注意：

- 文档里提到了健康检查接口
- 但当前版本代码里还没有实现，或者已被删掉

这点如果你要对外讲，建议说成“设计上预留了健康检查概念，但当前文件只实现了 `check()` 主调度入口和日志记录”。

**一句话总结**
`reflect/scheduler.py` 是 GenericAgent 的**后台定时调度模块**。它不负责聊天，不负责推理，只负责在合适的时间把 `sche_tasks/*.json` 里的任务转成 prompt 交给 Agent，并顺手维护 L4 历史归档。

如果你愿意，我可以下一步把这个文件也整理成你前面那种格式：`模块定位 -> 输入 -> 核心函数 -> 输出 -> 执行闭环图`。

## ga模块--执行适配层

[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:1) 是这个项目的**Agent 执行适配层**。它一头接 `agent_loop.py` 的循环协议，一头接具体工具、工作记忆和长期记忆，所以可以把它理解成：

- 工具实现层
- Handler/调度适配层
- 工作记忆注入层
- 长期记忆入口层

它不是入口文件，但它决定了 Agent “调用一个工具后会发生什么”。

**模块作用**
`ga.py` 主要负责四件事：

- 实现 Agent 可调用的本地工具：代码执行、文件读写、浏览器扫描、JS 执行、人工中断
- 定义 `GenericAgentHandler`，把 LLM 产生的 tool call 映射成实际 Python 行为
- 维护短期工作记忆 `working`，并在每轮后把 `<history>`、`key_info` 等重新注入下一轮
- 提供长期记忆入口 `get_global_memory()`，把 L1 索引注入系统 prompt

**一、顶层工具函数**
这些函数是“底层能力”，通常由 `GenericAgentHandler.do_xxx()` 包一层后给 Agent 用。

`code_run()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:12)  
作用：执行 Python 或 shell 代码。
- Python 代码写到临时 `.ai.py` 文件再跑
- shell 在 Windows 用 PowerShell，在 macOS/Linux 用 bash
- 支持超时终止和外部停止信号
- 流式收集 stdout，并生成简化结果返回  
执行时机：
- LLM 调用 `code_run` 工具时
- Handler 内部通过 `do_code_run()` 进入
- 长任务里大量“探测环境 / 写脚本 / 运行脚本”都依赖它

`ask_user()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:93)  
作用：构造一个标准的人工中断对象。  
执行时机：
- LLM 调用 `ask_user` 工具时
- 一般用于缺信息、需要决策、或连续失败后升级到人工

`first_init_driver()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:100)  
作用：初始化 `TMWebDriver` 浏览器控制对象，并等待可用标签页出现。  
执行时机：
- 首次调用 `web_scan()` 或 `web_execute_js()` 时，且全局 `driver is None`

`web_scan()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:113)  
作用：获取当前浏览器 tab 列表和简化 HTML 内容。
- 可只读 tab，不取页面 HTML
- 可切换 tab
- 可 text-only 模式降低 token 消耗  
执行时机：
- LLM 调用 `web_scan` 工具时
- 页面感知、列 tab、切 tab、快速确认 DOM 状态时

`format_error()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:144)  
作用：把异常格式化成 `异常类型 + 文件名 + 行号 + 代码行`。  
执行时机：
- `web_scan()`、`web_execute_js()` 等捕获异常时
- 给 LLM 更可定位的错误信息

`log_memory_access()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:153)  
作用：记录 `memory/` 目录下文件的访问统计，写到 `memory/file_access_stats.json`。  
执行时机：
- `file_read()` 读取 `memory/` 或 SOP 文件后

`web_execute_js()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:163)  
作用：在真实浏览器里执行 JS，并返回结果。  
执行时机：
- LLM 调用 `web_execute_js` 工具时
- Web 操作、页面交互、DOM 精准读取时

`expand_file_refs()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:174)  
作用：把 `{{file:path:start:end}}` 这种占位符展开成真实文件内容。  
执行时机：
- `file_patch`、`file_write` 写文件前
- 让模型不用在 arguments 里塞大段文本，而是引用已有文件片段

`file_patch()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:188)  
作用：在文件中精确替换唯一的 `old_content` 块。  
执行时机：
- LLM 调用 `file_patch` 工具时
- 精细修改文件时，优先于整体覆写

`_scan_files()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:204)  
作用：递归扫描目录里的文件，供找相似文件名用。  
执行时机：
- `file_read()` 发生文件不存在错误时，用于给“你是不是想找这个文件”建议

`file_read()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:210)  
作用：读取文件片段。
- 支持起始行
- 支持关键词定位
- 支持行号
- 支持超长行截断
- 支持找不到文件时给近似候选  
执行时机：
- LLM 调用 `file_read` 工具时
- 任何读源码、读 SOP、读报告、读配置场景

`smart_format()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:250)  
作用：把超长字符串压成头尾保留的短预览。  
执行时机：
- 多个工具函数输出内容过长时
- 控制返回给模型或 UI 的文本体积

`consume_file()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:255)  
作用：读取某个文件并立刻删除。  
执行时机：
- 子代理/反射任务中消费 `_stop`、`_keyinfo`、`_intervene` 等控制文件
- `turn_end_callback()` 注入外部干预时

**二、`GenericAgentHandler` 的作用**
类位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:263)

这是 `ga.py` 的核心。它继承自 `BaseHandler`，负责：

- 实现工具调用方法 `do_xxx`
- 管理短期工作记忆 `working`
- 控制 plan mode
- 在每轮后生成下轮 anchor prompt
- 把 `<summary>` 沉淀到 `history_info`

它和 `agent_loop.py` 是直接配合的：
- `agent_loop.agent_runner_loop()` 负责跑循环
- `GenericAgentHandler.dispatch()` 负责把工具名派发到 `do_file_read`、`do_code_run` 等

**三、Handler 内部函数和执行时机**

`__init__()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:265)  
作用：初始化 handler 状态：
- `parent` 指向 `GeneraticAgent`
- `working` 保存短期工作记忆
- `history_info` 保存摘要历史
- `code_stop_signal` 给代码执行中断用
- `_done_hooks` 存收尾钩子  
执行时机：
- 每次 `agentmain.py` 收到新任务时，都会新建一个 `GenericAgentHandler`

`_get_abs_path()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:273)  
作用：把相对路径解析到当前任务工作目录。  
执行时机：
- 几乎所有文件类工具执行前

`_extract_code_block()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:277)  
作用：从模型回复正文里提取 fenced code block。  
执行时机：
- 模型没把脚本放到 arguments，而是放在回复正文里时
- `do_code_run()`、`do_web_execute_js()` 会用到

`do_code_run()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:282)  
作用：执行 `code_run` 工具。
- 支持 `inline_eval`
- 否则调用顶层 `code_run()` 真正跑脚本
- 完成后构造 `StepOutcome`  
执行时机：
- LLM 发出 `code_run` tool call 时

`do_ask_user()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:307)  
作用：执行 `ask_user` 工具，返回 `should_exit=True`。  
执行时机：
- 需要中断当前自动执行，等待用户回答时

`do_web_scan()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:314)  
作用：执行 `web_scan` 工具，并把页面内容/元信息打包成 `StepOutcome`。  
执行时机：
- 浏览器感知、切 tab、页面读取时

`do_web_execute_js()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:328)  
作用：执行 `web_execute_js` 工具。
- 支持从文件读 JS
- 支持把 `js_return` 保存到文件
- 返回可供下一轮继续推理的结果  
执行时机：
- 浏览器精细交互场景优先使用

`do_file_patch()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:356)  
作用：执行 `file_patch` 工具。  
执行时机：
- 局部修改代码/文本文件时

`do_file_write()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:370)  
作用：执行 `file_write` 工具。
- 从 `<file_content>` 或代码块中提取要写入的正文
- 支持 `overwrite/append/prepend`  
执行时机：
- 新建文件、整体重写文件、大块内容落盘时

`do_file_read()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:403)  
作用：执行 `file_read` 工具，并附带 SOP/记忆读取提示。  
执行时机：
- 读取代码、记忆、SOP、计划文件时

`_in_plan_mode()` / `_exit_plan_mode()` / `enter_plan_mode()` / `_check_plan_completion()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:422)  
作用：管理 plan mode 状态。  
执行时机：
- 复杂任务进入计划模式时
- plan 执行过程中定期检查是否还有 `[ ]`

`do_update_working_checkpoint()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:432)  
作用：更新短期工作记忆：
- `key_info`
- `related_sop`
- 重置 `passed_sessions`  
执行时机：
- 任务开始、中途切子任务、读完 SOP、连续失败后保存关键上下文时

`do_no_tool()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:444)  
作用：处理“这一轮模型没调工具”的情况，这是个特殊兜底工具。
它会做很多守卫：
- 空响应重试
- 流式异常重试
- `max_tokens` 超限提示拆小步
- plan mode 下拦截“未验证就宣称完成”
- 拦截“只贴大代码块但没真正调用工具”
- 在 plan 已全部打勾时自动退出 plan mode  
执行时机：
- `agent_loop.py` 发现本轮没有显式 tool call 时，自动注入 `no_tool`

`do_start_long_term_update()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:496)  
作用：开启长期记忆结算流程。
- 生成记忆提炼 prompt
- 自动把 `memory_management_sop.md` 内容读进来
- 要求模型只写“已验证、长期有效”的信息  
执行时机：
- 任务完成后，模型判断“这次有值得记忆的内容”时

`_get_anchor_prompt()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:513)  
作用：构造每轮工具执行后的“锚点 prompt”。
内容包括：
- 最近 40 条 `history_info`
- 当前 turn 编号
- `key_info`
- `related_sop` 提示  
执行时机：
- 大多数 `do_xxx()` 结束后
- 它是下一轮继续推理的短期记忆注入入口

`turn_end_callback()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:525)  
作用：每轮结束时做全局收尾控制。
它会：
- 提取 `<summary>`，写入 `history_info`
- 缺少 `<summary>` 时生成警告
- 每 7/10/65 轮注入不同级别的危险提示
- 在长轮次时强制切换策略或 ask_user
- 在 plan mode 下定期要求重读 `plan.md`
- 读取 `_keyinfo` 和 `_intervene` 外部干预文件
- 触发 `_turn_end_hooks`  
执行时机：
- `agent_loop.py` 每轮结束后必调
- 是“执行闭环 -> 下一轮闭环”的关键接口

**四、长期记忆入口**

`get_global_memory()`  
位置：[ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:554)  
作用：读取全局记忆索引并拼成 prompt 片段。
它会注入：
- `cwd`
- `memory` 目录提示
- `assets/insight_fixed_structure*.txt`
- `memory/global_mem_insight.txt`  
执行时机：
- `agentmain.py` 里 `get_system_prompt()` 启动任务时调用一次
- `turn_end_callback()` 每 10 轮再次注入一次，防止长任务遗忘全局记忆

**五、`ga.py` 和其他模块的交互**

和 [agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:1) 的交互：
- `ga.py` 提供 `GenericAgentHandler`
- `agent_loop.py` 提供循环骨架 `agent_runner_loop()`
- loop 负责调度，handler 负责具体执行
- `StepOutcome` 是两者之间的标准协议

和 [agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:1) 的交互：
- `agentmain.py` 在每个任务开始时创建 `GenericAgentHandler`
- `agentmain.py` 调 `get_global_memory()` 把全局记忆注入 system prompt
- `agentmain.py` 把上一个任务遗留的 `key_info` 迁移到新 handler
- `agentmain.py` 负责把 `ga.py` 的输出通过 `display_queue` 推给前端

和 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:1) 的交互：
- `llmcore.py` 负责与模型 API 通信、日志写入、history 管理
- `ga.py` 不直接管模型，只消费 `response` 和 `tool_calls`
- `ga.py` 的 `turn_end_callback()` 产生的 anchor prompt，会变成下一轮 LLM 输入的一部分

和 [simphtml.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/simphtml.py:1)、[TMWebDriver.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/TMWebDriver.py:1) 的交互：
- `web_scan()` 用 `simphtml.get_html()`
- `web_execute_js()` 用 `simphtml.execute_js_rich()`
- 浏览器连接靠 `TMWebDriver`

和 `memory/` 的交互：
- `do_file_read()` 读 SOP/记忆时会打访问统计
- `do_start_long_term_update()` 把 `memory_management_sop.md` 拉入上下文
- `get_global_memory()` 读取 `global_mem_insight.txt`
- 模型后续可通过 `file_patch` 修改 L1/L2/L3 记忆文件

和前端/子代理控制文件的交互：
- `consume_file()` 在 `turn_end_callback()` 里消费 `_keyinfo`、`_intervene`
- 这使得 supervisor/subagent/外部控制者可以在任务运行中动态注入约束

**一句话总结**
如果说：

- `agentmain.py` 是运行时入口
- `llmcore.py` 是模型通信层
- `agent_loop.py` 是最小循环骨架

那么 `ga.py` 就是整个 GenericAgent 的**执行内核适配层**：它把“模型意图”翻译成“真实工具行为”，再把结果重新包装成“下一轮可继续推理的上下文”。

如果你要，我下一步可以把 `ga.py` 再整理成一张“模块结构图”，分成：
`底层工具函数 -> GenericAgentHandler -> Working Memory -> Long-term Memory -> 与外部模块交互`。

## agentmain模块

[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:1) 是这个项目的**运行时入口模块**。如果说：

- `llmcore.py` 负责模型通信
- `agent_loop.py` 负责最小执行循环
- `ga.py` 负责工具执行和工作记忆

那 `agentmain.py` 负责把它们真正“跑起来”，并统一管理：

- Agent 实例生命周期
- 多模型切换
- 任务队列
- 前台/后台执行
- 反射模式 `--reflect`
- 一次性任务模式 `--task`
- 命令行交互模式

它是整个系统最像 runtime / orchestrator 的模块。

**模块作用**
`agentmain.py` 主要负责五件事：

- 初始化全局运行环境：语言、工具 schema、memory 目录、CDP bridge 配置
- 创建 `GeneraticAgent` 运行时对象
- 管理 LLM session 列表和多模型切换
- 接收外部任务并送入 `agent_runner_loop()`
- 提供三种运行模式：
  - 普通交互模式
  - 文件任务模式 `--task`
  - 反射模式 `--reflect`

**一、模块级初始化内容**

`load_tool_schema(suffix='')`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:15)  
作用：读取 `assets/tools_schema*.json`，加载当前 Agent 可调用的工具定义。  
执行时机：
- 模块 import 时先执行一次 `load_tool_schema()`
- 切换到中文模型时，`next_llm()` 可能改用 `tools_schema_cn.json`

`lang_suffix / mem_dir / mem_txt / mem_insight / cdp_cfg` 这段初始化  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:21)  
作用：
- 确保 `memory/` 目录存在
- 确保 `global_mem.txt` 存在
- 确保 `global_mem_insight.txt` 存在
- 初始化 CDP bridge 的 `config.js`，生成唯一 TID  
执行时机：
- 模块加载时立即执行
- 属于 runtime 启动前的环境准备

`get_system_prompt()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:38)  
作用：组装系统提示词：
- 读取 `assets/sys_prompt*.txt`
- 加入今天日期
- 加入 `get_global_memory()` 返回的全局记忆  
执行时机：
- 每次新任务开始前，在 `run()` 里构造系统 prompt 时调用

**二、`GeneraticAgent` 类的作用**
类位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:44)

这是项目的核心运行时对象，负责：

- 管理任务队列
- 管理当前 handler
- 管理历史摘要
- 管理多个 LLM client
- 驱动 `agent_runner_loop()`
- 接前端，吐 `display_queue`

你可以把它看成一个“单 Agent runtime 实例”。

**三、类内函数说明**

`__init__()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:45)  
作用：初始化运行时状态：
- `task_dir`
- `history`
- `task_queue`
- `is_running / stop_sig`
- `llm_no`
- `handler`
- `verbose`
- 加载 LLM sessions  
执行时机：
- 前端启动时
- 命令行启动时
- `init()` 或 `agent = GeneraticAgent()` 时

`load_llm_sessions()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:56)  
作用：从 `mykey.py` 或 `mykey.json` 中读取模型配置，创建所有可用的 LLM session。
支持：
- `ToolClient(ClaudeSession)`
- `ToolClient(LLMSession)`
- `NativeToolClient(NativeClaudeSession)`
- `NativeToolClient(NativeOAISession)`
- `MixinSession` 混合回退链路  
执行时机：
- 初始化时调用
- `next_llm()`、`list_llms()` 等也会再次触发热加载
- `mykey` 文件变化时会重新加载

`next_llm(n=-1)`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:80)  
作用：切换当前使用的 LLM client。
同时会：
- 继承旧 backend 的 history
- 清空工具缓存 `last_tools`
- 根据模型名切换中英文工具 schema  
执行时机：
- 前端用户切模型时
- 命令行或聊天命令切换模型时
- 运行时需要手动换链路时

`list_llms()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:92)  
作用：返回所有已加载的 LLM 列表和当前激活项。  
执行时机：
- 前端侧边栏展示可切换模型时

`get_llm_name()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:95)  
作用：获取当前或指定 backend 的展示名称。  
执行时机：
- 前端展示当前模型
- 切换模型时提示名称

`abort()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:100)  
作用：中止当前任务。
它会：
- 设置 `stop_sig = True`
- 给当前 handler 的 `code_stop_signal` 注入停止标记  
执行时机：
- 用户点击停止
- 前端关闭任务
- `/new`
- `/continue`
- 外部 `_stop` 文件触发中止

`put_task(query, source="user", images=None)`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:106)  
作用：把一个任务放进 `task_queue`，并为它创建一个 `display_queue` 返回给调用方。  
执行时机：
- 前端发送新消息时
- reflect 模式触发任务时
- `--task` 文件任务模式提交任务时

这是前后端连接的关键接口：
- 输入：用户 query
- 输出：流式结果队列

`_handle_slash_cmd(raw_query, display_queue)`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:112)  
作用：处理内部 slash 命令。
当前内置两类：
- `/session.xxx=...`：动态改 backend 参数
- `/resume`：生成恢复历史会话的分析 prompt  
执行时机：
- `run()` 从队列中取到任务后，真正送给 Agent 前
- 如果其他模块 monkey patch 了它，比如 `continue_cmd.install()`，也会先经过扩展命令逻辑

`run()`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:129)  
作用：这是 `GeneraticAgent` 的主执行循环，也是整个 runtime 最核心的方法。

它做的事：

1. 从 `task_queue` 取任务
2. 处理 slash command
3. 设置 `is_running`
4. 更新 `history`
5. 组装 `sys_prompt`
6. 创建新的 `GenericAgentHandler`
7. 继承上一个 handler 的 `working key_info`
8. 调用 `agent_runner_loop(...)`
9. 持续消费生成器输出
10. 把中间和最终结果塞进 `display_queue`
11. 更新 `self.history = handler.history_info`
12. 收尾，重置状态

执行时机：
- 一般由 `threading.Thread(target=agent.run, daemon=True).start()` 后常驻运行
- 前端和反射任务都依赖它消费队列

这是整个模块最重要的执行闭环入口。

**四、`run()` 内部的关键行为**

系统 prompt 构造  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:142)  
作用：`get_system_prompt()` + backend 额外 prompt。  
时机：每个任务开始时

Handler 迁移旧 working memory  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:145)  
作用：如果上一个 handler 有 `key_info`，迁移到新 handler，并标记这是跨会话遗留信息。  
时机：用户在同一窗口连续聊多个任务时

执行 agent loop  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:154)  
作用：真正进入 `agent_runner_loop()`。  
时机：每个任务的主处理阶段

流式输出到前端  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:157)  
作用：
- 增量收集 `full_resp`
- 定期通过 `display_queue.put({'next': ...})` 推送前端
- 完成后再发 `{'done': ...}`  
时机：任务执行全过程

任务中断检测  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:159)  
作用：如果 `task_dir/_stop` 文件存在，自动中止任务。  
时机：
- 子代理模式
- 文件任务模式
- supervisor/外部控制写入 `_stop`

异常处理  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:169)  
作用：把 backend 错误转成可显示文本发回前端。  
时机：`agent_runner_loop()` 或 handler 执行异常时

最终收尾  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:173)  
作用：
- 重置 `is_running`
- 清理 `stop_sig`
- `task_done()`
- 给 code_run 再补一个 stop signal，确保子进程停干净  
时机：每个任务结束后

**五、命令行主程序部分**

`if __name__ == '__main__':`  
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:182)

这里定义了三种启动模式。

**1. 后台模式 `--bg`**
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:192)  
作用：
- 用 `subprocess.Popen()` 把当前 agentmain 再启动成后台进程
- stdout/stderr 重定向到任务目录日志文件  
执行时机：
- 子代理启动时
- 需要后台长期运行时

**2. 文件任务模式 `--task`**
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:207)  
作用：把 Agent 作为一个“文件 IO 驱动任务机”运行。
流程：
- 读取 `temp/<task>/input.txt`
- 执行任务
- 把输出写入 `output.txt`
- 等待 `reply.txt`
- 如果收到 reply 再继续下一轮  
执行时机：
- subagent 模式
- 外部脚本通过文件驱动 Agent 时
- plan/subagent/supervisor 流程里很常用

**3. 反射模式 `--reflect`**
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:227)  
作用：加载一个 reflect 脚本，如 `reflect/autonomous.py`、`reflect/scheduler.py`，周期性调用它的 `check()`。
流程：
- 动态 import reflect 脚本
- 按 `INTERVAL` 轮询
- `check()` 返回任务就 `put_task()`
- 可调用 `on_done(result)` 收尾  
执行时机：
- 后台自主行动
- 定时任务调度
- watchdog 类自动触发任务

**4. 普通命令行模式**
位置：[agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:264)  
作用：直接在终端输入问题，与 Agent 对话。  
执行时机：
- 用户直接运行 `python agentmain.py`

**六、`agentmain.py` 和其他模块的交互**

和 [agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:1) 的交互：
- `agentmain.py` 调 `agent_runner_loop()`
- `agent_loop.py` 负责 LLM/tool 的最小循环
- `agentmain.py` 负责给 loop 提供 client、system_prompt、handler、tools_schema

和 [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:1) 的交互：
- `agentmain.py` 创建 `GenericAgentHandler`
- 调 `get_global_memory()` 拼系统 prompt
- 把 `handler.history_info` 回写到 `self.history`
- 接收 handler 的 `code_stop_signal` 实现停止执行

和 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:1) 的交互：
- 加载和热更新模型配置 `reload_mykeys()`
- 创建 `ToolClient` / `NativeToolClient` / `MixinSession`
- 通过 `self.llmclient.chat()` 驱动模型调用
- 继承和切换 backend.history

和前端模块的交互：
- 前端通过 `put_task()` 投递任务
- 前端从 `display_queue` 读取 `next/done`
- 前端通过 `abort()` 停止当前任务
- 前端通过 `list_llms()`、`next_llm()` 控制模型切换

和 `reflect/` 模块的交互：
- `--reflect` 会动态加载 `reflect/autonomous.py`、`reflect/scheduler.py`
- reflect 脚本只负责提供 `INTERVAL` 和 `check()`
- 真正执行任务还是交给 `GeneraticAgent.run()`

和 `temp/` 目录的交互：
- `--task` 模式依赖 `input.txt / output.txt / reply.txt / _stop`
- 普通会话日志落在 `temp/model_responses/`
- 子代理和监督机制大量依赖这个文件协议

**一句话总结**
`agentmain.py` 是 GenericAgent 的**运行时总控模块**。  
它不直接实现工具，也不直接实现推理循环，而是负责把：

- 模型层 `llmcore.py`
- 循环层 `agent_loop.py`
- 执行层 `ga.py`
- 前端/反射/子代理输入

统一组织成一个可长期运行、可流式输出、可切模型、可中断、可后台触发的 Agent runtime。

如果你要，我下一步可以把 `agentmain.py` 也画成一张“运行时架构图”，按 `输入源 -> GeneraticAgent -> agent_runner_loop -> display_queue -> 前端/文件/reflect` 的方式展开。

## agentcore模块

[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:1) 是这个项目的**模型通信与会话协议核心模块**。它负责把 Agent 的上下文、工具协议、历史消息，转换成不同模型厂商能吃的请求格式；再把模型返回的流式文本、thinking、tool call 统一解析回 GenericAgent 内部格式。

那 `llmcore.py` 就是这三者和 LLM 之间的“协议转换器 + 会话管理器 + 日志记录器”。

**模块作用**
它主要承担六类职责：

- 读取并热更新模型配置
- 管理消息历史和上下文裁剪
- 兼容 Anthropic / OpenAI / Responses API / Native Claude Code 风格接口
- 
- 统一解析 text / thinking / tool_use
- 封装两类客户端：文本协议式 `ToolClient` 和原生工具式 `NativeToolClient`
- 记录 `Prompt/Response` 日志，供 `/continue`、L4 归档和调试使用

**一、配置与热更新相关函数**

`_load_mykeys()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:6)  
作用：从 `mykey.py` 或 `mykey.json` 读取所有模型配置。  
执行时机：

- 首次加载模型配置时
- `reload_mykeys()` 检测到配置变化后会调用它

`reload_mykeys()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:17)  
作用：按文件修改时间热更新配置，并在有 `langfuse_config` 时自动激活 tracing。  
执行时机：
- `agentmain.py -> load_llm_sessions()` 每次准备 LLM session 时
- 用户修改 `mykey.py` 后，下一次 reload 会生效

`__getattr__(name)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:29)  
作用：实现 `llmcore.mykeys` 的懒加载访问。  
执行时机：
- 外部代码访问 `llmcore.mykeys` 时

**二、上下文压缩与历史管理**

`compress_history_tags(messages, keep_recent=10, max_len=800, force=False)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:33)  
作用：压缩旧消息中的 `<thinking>`、`<tool_use>`、`<tool_result>`、`<history>`、`<key_info>`，减少 token 消耗。  
执行时机：

- `trim_messages_history()` 调用时
- 长对话中每隔几次自动生效

`_sanitize_leading_user_msg(msg)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:66)  
作用：把被截断历史开头的 `tool_result` 改写成纯文本，防止出现“孤立工具结果”破坏协议。  
执行时机：
- `trim_messages_history()` 在删前文后修复新的首条 user 消息时

`safeprint(*argv)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:85)  
作用：包装 `print`，避免 stdout 关闭导致异常。  
执行时机：
- 模块加载后替换全局 `print`

`trim_messages_history(history, context_win)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:90)  
作用：根据 `context_win` 控制历史长度。
流程是：
- 先压缩旧标签
- 如果消息总长度过大，就裁掉最旧的 user/assistant 对
- 保证上下文不会无限膨胀  
执行时机：
-   

这部分是**记忆闭环和长任务闭环里非常关键的一层**，因为它决定了长任务能不能持续跑而不把模型窗口撑爆。

**三、厂商协议解析与统一输出**

`auto_make_url(base, path)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:104)  
作用：根据基础地址自动拼 API URL，兼容不同厂商和中转站。  
执行时机：
- 每次发 OpenAI / Claude 请求前

`_parse_claude_json(data)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:110)  
作用：解析 Claude 非流式 JSON 响应，抽出 text/thinking/content blocks。  
执行时机：
- `ClaudeSession` 非流式模式

`_parse_claude_sse(resp_lines)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:118)  
作用：解析 Claude SSE 流式响应，统一生成：
- text block
- thinking block
- tool_use block  
执行时机：
- `ClaudeSession.raw_ask()`、`NativeClaudeSession.raw_ask()` 走流式模式时

`_try_parse_tool_args(raw)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:186)  
作用：解析工具参数 JSON，兼容 `{...}{...}` 这种被拼接的异常输出。  
执行时机：
- OpenAI / Responses API 解析 function arguments 时

`_parse_openai_sse(resp_lines, api_mode="chat_completions")`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:201)  
作用：解析 OpenAI 流式返回，兼容两种模式：
- `chat_completions`
- `responses`  
并统一产出 text / thinking / tool_use block。  
执行时机：
- `LLMSession`、`NativeOAISession` 流式调用时

`_record_usage(usage, api_mode)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:295)  
作用：打印 token usage 和缓存命中信息。  
执行时机：
- 解析任意厂商响应时，拿到 usage 后

`_parse_openai_json(data, api_mode="chat_completions")`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:309)  
作用：解析 OpenAI 非流式响应。  
执行时机：
- 非流式模式下的 OpenAI / Responses API 请求

**四、请求发送与协议转换**

`_stamp_oai_cache_markers(messages, model)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:339)  
作用：给 Anthropic-through-OAI relay 的最近两条 user 消息打 `cache_control`。  
执行时机：
- `_openai_stream()` 发送 chat_completions 前

`_stream_with_retry(sess, url, headers, payload, parse_fn)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:352)  
作用：统一处理 HTTP 请求、流式返回、重试、超时、连接错误。  
执行时机：
- 所有真正对 LLM 发请求的路径都会经过它

这是**执行闭环里 LLM 通道的核心稳定性保障**。

`_openai_stream(sess, messages)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:387)  
作用：把内部消息发到 OpenAI 风格接口，兼容：
- `chat/completions`
- `responses`  
执行时机：
- `LLMSession.raw_ask()`
- `NativeOAISession.raw_ask()`

`_prepare_oai_tools(tools, api_mode="chat_completions")`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:415)  
作用：把内部工具 schema 转成 OpenAI 所需的格式。  
执行时机：
- `_openai_stream()` 发请求前

`_to_responses_input(messages)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:426)  
作用：把内部消息格式转换成 OpenAI Responses API 的 `input` 格式。  
执行时机：
- `_openai_stream()` 走 `responses` 模式时

`_msgs_claude2oai(messages)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:462)  
作用：把项目内部偏 Claude block 风格的消息，转成 OpenAI 风格消息。  
执行时机：
- `LLMSession.make_messages()`
- `NativeOAISession.raw_ask()`

**五、Session 类层次**
这一层是 `llmcore.py` 的主干。

`BaseSession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:509)  
作用：所有 LLM session 的基类。负责：
- 存放配置
- 维护 `history`
- 控制超时、重试、stream、proxy
- 在 `ask()` 里统一做 history 追加、trim、raw_ask 调用  
执行时机：
- 被各具体 Session 继承
- 每次模型请求都会走 `BaseSession.ask()` 或其重写版本

`_drop_unsigned_thinking(messages)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:570)  
作用：移除没有 signature 的 thinking block，适配 Claude API。  
执行时机：
- Claude 类请求前

`_ensure_thinking_blocks(messages, model)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:576)  
作用：给 DeepSeek 之类模型补 thinking block。  
执行时机：
- Native Claude / Native OAI 调用前

`ClaudeSession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:587)  
作用：标准 Anthropic Messages API session。  
执行时机：
- `agentmain.py` 加载 `claude` 配置但非 native 时创建

`LLMSession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:605)  
作用：标准 OpenAI-compatible session。  
执行时机：
- `agentmain.py` 加载 `oai` 配置但非 native 时创建

`_fix_messages(messages)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:609)  
作用：修复 Claude 原生 API 需要的消息结构：
- 保证 role 交替
- 保证 tool_use / tool_result 配对
- 修复 orphan tool_result  
执行时机：
- `NativeClaudeSession.raw_ask()`
- `NativeOAISession.raw_ask()`

`NativeClaudeSession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:628)  
作用：模拟 Claude Code / Claude CLI 风格的 native 工具调用会话。它保留了：
- content blocks
- thinking
- tool_use
- 原生 tool ids  
执行时机：
- `agentmain.py` 加载 `native claude` 配置时

这是**长任务闭环里最强的一种 LLM 会话形式**，因为它更贴近原生工具调用能力。

`NativeOAISession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:697)  
作用：Native 工具调用风格，但底层走 OpenAI 接口。  
执行时机：
- `agentmain.py` 加载 `native oai` 配置时

`openai_tools_to_claude(tools)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:703)  
作用：把 OpenAI function schema 转成 Claude `input_schema`。  
执行时机：
- Native Claude 请求前
- MixinSession 广播 tools 时

`MockFunction / MockToolCall / MockResponse`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:713)  
作用：统一模拟 response/tool_call 结构，让上层 `agent_loop.py` 不用关心厂商差异。  
执行时机：
- 非原生文本协议解析后
- Native 响应包装后

**六、Client 层：给 AgentLoop 的统一接口**

`ToolClient`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:729)  
作用：把“无原生工具调用”的模型包装成可用的工具 Agent。
它做三件事：
- 拼出一段包含工具协议的超长 prompt
- 让模型用 `<tool_use>` 文本块调用工具
- 解析模型文本回复里的 tool call

关键函数：

`ToolClient.chat()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:737)  
作用：
- 构建协议 prompt
- 写 `Prompt` 日志
- 调 backend.ask()
- 收完整 raw_text
- 写 `Response` 日志
- 解析成 `MockResponse`  
执行时机：
- `agent_loop.py` 每轮调用 `client.chat(...)` 时

`_prepare_tool_instruction()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:748)  
作用：生成工具调用协议说明，并做“工具状态仍然有效”的 token 节省优化。  
执行时机：
- 每次 `ToolClient.chat()` 开头

`_build_protocol_prompt()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:776)  
作用：把 system prompt、工具协议、历史消息、tool_results 拼成一整段 prompt 文本。  
执行时机：
- `ToolClient.chat()` 中

`_parse_mixed_response()`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:793)  
作用：从模型纯文本输出里解析：
- `<thinking>`
- `<tool_use>`
- fallback JSON 工具调用  
执行时机：
- `ToolClient.chat()` 收到完整回复后

`_parse_text_tool_calls(content)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:830)  
作用：从文本里兜底提取工具调用。  
执行时机：
- `_parse_mixed_response()`
- `NativeClaudeSession.ask()` 在 native tool 不存在时也会回退到这里

`_write_llm_log(label, content)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:852)  
作用：把每轮 Prompt / Response 写到 `temp/model_responses/model_responses_<pid>.txt`。  
执行时机：
- `ToolClient.chat()`
- `NativeToolClient.chat()`

这是**记忆闭环和 `/continue` 恢复链的基础设施**。

`tryparse(json_str)`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:860)  
作用：宽松 JSON 解析，容忍代码块包裹和尾部截断。  
执行时机：
- 文本工具调用解析时

`MixinSession`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:871)  
作用：多模型回退与弹回机制。
- 主模型失败时自动切备用
- 一段时间后再弹回主模型  
执行时机：
- `agentmain.py` 配置了 `mixin` 时
- 每次底层模型请求时生效

`NativeToolClient`  
位置：[llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:943)  
作用：原生工具调用 client，直接让 backend 接受 content blocks 和 tool_results，而不是拼成长文本协议。
它负责：
- 设置固定 thinking/system prompt
- 合并 tool_results
- 写 Prompt/Response 日志
- 维护 pending tool ids  
执行时机：
- `agent_loop.py` 每轮调用 `client.chat(...)` 时，如果当前 client 是 native

**七、`llmcore.py` 和其他模块的交互**

和 [agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:1) 的交互：
- `agentmain.py` 调 `reload_mykeys()`
- 根据配置创建 `ToolClient` / `NativeToolClient`
- 通过 `backend.history` 在多模型切换时继承上下文

和 [agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:1) 的交互：
- `agent_loop.py` 只关心 `client.chat(messages, tools)`
- `llmcore.py` 保证无论底层是哪家模型，都返回统一的 response/tool_calls 结构

和 [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:1) 的交互：
- `ga.py` 执行工具后，会把 `tool_results` 放回下一轮 user message
- `llmcore.py` 负责把这些 `tool_results` 正确编码回模型协议
- `ga.py` 产生 working memory / summary，最终会出现在下一轮发送给 LLM 的 messages 中

和 [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:1) 的交互：
- `_write_llm_log()` 写出的 `model_responses_<pid>.txt`
- 是 `/continue` 列历史、恢复历史、UI 回放的直接数据源

和 L4 归档的交互：
- `memory/L4_raw_sessions/compress_session.py` 处理的输入，就是 `llmcore.py` 写出的原始模型日志

和 [plugins/langfuse_tracing.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/plugins/langfuse_tracing.py:1) 的交互：
- tracing 会 monkey patch `_write_llm_log`
- 也会包裹 SSE 解析器，提取 usage
- 所以 `llmcore.py` 是 observability 的关键挂载点

**八、在三个闭环中承担的作用**

**1. 执行闭环**
```text
AgentLoop.run()
 |
 v
LLMClient.chat()
(llmcore.py)
 |
 +--> 构造 messages / tools / system
 +--> 发请求给模型
 +--> 流式解析 text/thinking/tool_use
 +--> 统一返回 MockResponse / Native response
 |
 v
Tool dispatch
```

在执行闭环里，`llmcore.py` 是：
- **模型通信层**
- **工具调用协议层**
- **流式解析层**
- **失败重试与多模型回退层**

没有它，AgentLoop 拿不到统一的 tool call。

**2. 记忆闭环**
```text
Task result
 |
 v
tool_results / summary / history
 |
 v
llmcore.py
 |
 +--> backend.history 维护
 +--> trim_messages_history 裁剪
 +--> _write_llm_log 落盘
 |
 v
continue_cmd / L4 archive / memory distillation
```

在记忆闭环里，`llmcore.py` 是：
- **短期上下文记忆容器**：`history`
- **上下文压缩器**：`compress_history_tags` / `trim_messages_history`
- **会话日志记录器**：`_write_llm_log`
- **历史恢复的数据源提供者**

它不直接写 L1/L2/L3 记忆，但它负责保住“会话级记忆”和“恢复级记忆”。

**3. 长任务闭环**
```text
Long Task
 |
 v
many turns / many tool_results / large context
 |
 v
llmcore.py
 |
 +--> trim old history
 +--> compress old tool/thinking tags
 +--> keep protocol/tool state
 +--> native tool ids continuity
 +--> retry / fallback / spring-back
 |
 v
task can continue without context explosion
```

在长任务闭环里，`llmcore.py` 是：
- **上下文容量控制器**
- **多轮协议连续性维护者**
- **工具结果回填者**
- **链路稳定性保障者**

特别是：
- `trim_messages_history()`
- `NativeToolClient` 的 pending tool ids
- `MixinSession`
- `_stream_with_retry()`

这几块都是长任务能不能稳定跑下去的关键。

**一句话总结**
`llmcore.py` 是 GenericAgent 的**LLM 协议中枢**。  
它把不同模型接口、不同消息格式、不同工具调用方式，全部收敛成 `agent_loop.py` 能直接消费的统一会话协议；同时又通过历史裁剪、日志落盘和回退重试，支撑了执行闭环、记忆闭环和长任务闭环的稳定运行。

如果你要，我下一步可以把 `llmcore.py` 单独画成一张“协议转换图”，把 `ToolClient / NativeToolClient / Session / Parser / Logger` 五层关系展开。

## agentloop模块

[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:1) 是这个项目的**最小 Agent 执行循环模块**。它不负责模型通信，不负责具体工具实现，也不负责前端，而是专门负责把一次任务变成稳定的多轮闭环：

- 发模型请求
- 解析工具调用
- 分发工具执行
- 收集结果
- 生成下一轮 prompt
- 决定继续、结束或中断

如果说：

- `agentmain.py` 是 runtime 入口
- `llmcore.py` 是模型协议层
- `ga.py` 是工具执行层

那 `agent_loop.py` 就是三者之间的**调度心脏**。

**模块作用**
它主要负责四件事：

- 定义 Agent 单步执行结果的数据结构 `StepOutcome`
- 定义工具处理器基类 `BaseHandler`
- 提供通用生成器兼容逻辑，让工具和 hook 可以是普通函数也可以是生成器
- 实现核心循环 `agent_runner_loop()`

这个文件最关键的一点是：它把复杂 Agent 系统压成了一个非常小的控制协议。

**一、内部函数与类型**

`StepOutcome`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:4)  
作用：表示一次工具执行后的标准返回结构，字段有：

- `data`：工具结果数据
- `next_prompt`：下一轮要发给模型的 prompt
- `should_exit`：是否立即退出整个任务

执行时机：
- 每个 `do_xxx()` 工具函数执行完后返回
- `agent_runner_loop()` 根据它决定继续还是结束

这是整个 loop 的状态传递核心。

`try_call_generator(func, *args, **kwargs)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:9)  
作用：兼容普通函数和生成器函数。
如果返回值是生成器，就 `yield from` 跑完；否则直接返回。  
执行时机：
- `BaseHandler.dispatch()` 调用 `tool_before_callback`、`tool_after_callback`、`do_xxx()` 时

这个设计让 handler hook 和工具实现都能灵活支持流式输出。

`BaseHandler`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:14)  
作用：所有具体 handler 的基类，定义了三类 hook：

- `tool_before_callback()`
- `tool_after_callback()`
- `turn_end_callback()`

以及最重要的：

- `dispatch(tool_name, args, response, index=0)`

执行时机：
- `ga.py` 的 `GenericAgentHandler` 继承它
- 每轮模型产生 tool call 后，loop 会通过它分发执行

`BaseHandler.dispatch()`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:18)  
作用：把工具名映射到 handler 的 `do_<tool_name>()` 方法。
逻辑是：

- 先执行 `tool_before_callback`
- 再执行具体 `do_xxx`
- 再执行 `tool_after_callback`
- 如果工具不存在：
  - `bad_json` 走特殊处理
  - 其他未知工具返回“未知工具”提示

执行时机：
- `agent_runner_loop()` 每次处理一个 tool call 时

这是 loop 和具体工具层之间的正式调度接口。

`json_default(o)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:30)  
作用：JSON 序列化兜底，支持 `set -> list`。  
执行时机：
- 工具结果写回 `tool_results` 时

`exhaust(g)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:31)  
作用：把一个生成器跑到结束，并取最终返回值。  
执行时机：
- 非 verbose 模式下处理 `client.chat()` 或工具生成器时

`get_pretty_json(data)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:36)  
作用：把工具参数格式化成更易读的 JSON。  
执行时机：
- verbose 模式下打印工具调用参数时

**二、核心循环函数**

`agent_runner_loop(client, system_prompt, user_input, handler, tools_schema, max_turns=40, verbose=True, initial_user_content=None)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:41)

这是整个文件的核心，也是 GenericAgent 的最小闭环实现。

它的完整职责是：

1. 初始化 messages
2. 在最大轮数内循环
3. 每轮调用 `client.chat()`
4. 解析 `response.tool_calls`
5. 逐个分发工具执行
6. 收集 `StepOutcome`
7. 汇总出下一轮 prompt
8. 决定结束或继续

可以拆成几个阶段来看。

**1. 初始化消息**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:42)

作用：
- 组装第一轮消息：
  - system
  - user

执行时机：
- 每个任务刚启动时，仅执行一次

**2. 轮次控制**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:49)

作用：
- `while turn < max_turns`
- 每轮 turn + 1
- 每 10 轮重置一次 `client.last_tools`，避免工具描述长期缓存导致上下文膨胀

执行时机：
- 整个任务生命周期内

这个“每 10 轮重置工具描述”对长任务非常关键，是长任务闭环里的一个防膨胀措施。

**3. 调模型**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:57)

作用：
- 调 `client.chat(messages=messages, tools=tools_schema)`
- verbose 模式流式输出
- 非 verbose 模式一次性收完整结果

执行时机：
- 每轮开始时

这里的 `client` 实际来自 `llmcore.py`：
- `ToolClient`
- `NativeToolClient`

**4. 解析工具调用**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:69)

作用：
- 如果模型没调工具，构造一个虚拟工具 `no_tool`
- 如果调了工具，把每个 `tool_call` 解析成：
  - `tool_name`
  - `args`
  - `id`

执行时机：
- 每轮拿到模型回复后

这里非常重要，因为它把“没调工具”也纳入统一分发流程，不会分叉出另一套代码路径。

**5. 分发执行工具**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:77)

作用：
- 逐个 tool call 执行
- 调 `handler.dispatch(...)`
- 收到 `StepOutcome`
- 根据结果判断：
  - 是否 `should_exit`
  - 是否结束当前任务
  - 是否继续下一轮
- 收集 tool_results，供下一轮回传给模型

执行时机：
- 每轮模型发出 tool call 之后

这是 loop 的执行核心。

**6. 终止与继续判断**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:101)

作用：
- 如果没有新的 `next_prompt`，或出现 `exit_reason`，则尝试结束
- 如果 handler 还有 `_done_hooks`，会把 hook 注入成下一轮 prompt，继续执行收尾步骤

执行时机：
- 每轮所有工具执行完后

这个 `_done_hooks` 机制是比较巧妙的，允许工具结束后再插入“收尾检查轮”。

**7. 回调并构造下一轮消息**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:106)

作用：
- 调 `handler.turn_end_callback(...)`
- 把它返回的 `next_prompt` 作为下一轮唯一 user message
- 同时附带 `tool_results`

执行时机：
- 每轮结束时

这里是 loop 和工作记忆系统真正衔接的地方，因为 `turn_end_callback()` 通常会把：

- `<history>`
- `key_info`
- plan hint
- 风险提示

注入到下一轮 prompt 中。

**8. 最大轮数退出**
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:110)

作用：
- 如果没有正常退出原因，就返回 `MAX_TURNS_EXCEEDED`

执行时机：
- 超过 `max_turns` 后

这是整个执行闭环的最后安全阀。

**三、辅助清洗函数**

`_clean_content(text)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:114)  
作用：清洗输出文本，避免展示过长代码块、冗余标签和大量空行。  
执行时机：
- 非 verbose 模式下展示模型文本回复时

`_compact_tool_args(name, args)`  
位置：[agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:127)  
作用：把工具参数压缩成简短可读的日志格式。  
执行时机：
- 非 verbose 模式打印工具调用时

**四、`agent_loop.py` 和其他模块的交互**

和 [agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:1) 的交互：
- `agentmain.py` 创建 client、handler、system_prompt
- `agentmain.py` 调 `agent_runner_loop(...)`
- `agentmain.py` 消费 loop 的流式输出并转发给前端

所以：
- `agentmain.py` 是外层 runtime
- `agent_loop.py` 是内层任务循环

和 [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:1) 的交互：
- `ga.py` 提供 `GenericAgentHandler(BaseHandler)`
- `agent_loop.py` 通过 `handler.dispatch()` 调具体工具
- `ga.py` 的 `turn_end_callback()` 负责构造下一轮工作记忆 prompt

所以：
- `agent_loop.py` 负责调度
- `ga.py` 负责执行和记忆注入

和 [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:1) 的交互：
- `agent_loop.py` 每轮调用 `client.chat(...)`
- `llmcore.py` 保证返回统一的 `response.content / response.tool_calls`
- `tool_results` 由 loop 传回 llmcore 下一轮请求

所以：
- `llmcore.py` 负责模型协议
- `agent_loop.py` 负责工具闭环

和前端模块的交互：
- `agent_loop.py` 自己不接前端
- 它通过 `yield` 输出中间文本
- `agentmain.py` 再把这些输出推到 `display_queue`
- 前端再渲染

**五、在整体架构中的位置**
可以把它理解成：

```text
Frontend / CLI
 |
 v
agentmain.py
 |
 v
agent_runner_loop()   <- agent_loop.py
 |
 +--> llmcore.py : client.chat()
 |
 +--> ga.py      : handler.dispatch()
 |
 v
StepOutcome
 |
 v
turn_end_callback()
 |
 v
next_prompt / exit
```

**六、它在三个闭环中的作用**

**1. 执行闭环**
这是它最核心的职责。

```text
User Task
 |
 v
LLM 回复
 |
 v
tool_calls
 |
 v
handler.dispatch()
 |
 v
StepOutcome
 |
 v
next_prompt
 |
 v
下一轮 LLM
```

它在执行闭环里是：
- **主调度器**
- **工具调用编排器**
- **终止条件控制器**

**2. 记忆闭环**
它本身不存记忆，但它决定了记忆何时注入、何时更新。

```text
tool result
 |
 v
StepOutcome.next_prompt
 |
 v
turn_end_callback()
 |
 v
history/key_info 注入下一轮
```

所以它在记忆闭环里是：
- **短期工作记忆流转器**
- **summary 进入历史的承接层**

**3. 长任务闭环**
长任务能不能跑得住，很大程度看 loop 的轮次控制和续跑策略。

它负责：
- 最大轮数限制
- 每 10 轮重置工具描述
- 支持 `_done_hooks` 收尾
- 支持 `no_tool` 兜底
- 把 plan mode 的检查逻辑留给 handler 接管

所以它在长任务闭环里是：
- **轮次稳定器**
- **上下文续跑骨架**
- **收尾与退出控制层**

**一句话总结**
`agent_loop.py` 是 GenericAgent 的**最小闭环调度引擎**。  
它不关心具体模型是哪家，也不关心工具到底怎么实现，而是把“模型思考 -> 工具执行 -> 结果反馈 -> 下一轮继续”这件事变成一个统一、稳定、可扩展的循环。

如果你要，我下一步可以把 `agent_loop.py` 再压成一张“单轮执行时序图”，把一轮里 `client.chat -> tool dispatch -> StepOutcome -> next_prompt` 画出来。
