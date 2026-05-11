下面是 `ga.py` 的接口清单，已忽略具体实现细节和异常处理，只保留核心类、函数、方法签名，以及每个方法的一句话数据流说明。

### 接口清单

**模块级函数**
```python
def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=[])

def ask_user(question, candidates=None)

def first_init_driver()

def web_scan(tabs_only=False, switch_tab_id=None, text_only=False)

def format_error(e)

def log_memory_access(path)

def web_execute_js(script, switch_tab_id=None, no_monitor=False)

def expand_file_refs(text, base_dir=None)

def file_patch(path: str, old_content: str, new_content: str)

def _scan_files(base, depth=2)

def file_read(path, start=1, keyword=None, count=200, show_linenos=True)

def smart_format(data, max_str_len=100, omit_str=' ... ')

def consume_file(dr, file)

def get_global_memory()
```

- `code_run(...)`：输入代码文本、执行类型和运行参数，输出一个可流式产生执行日志并最终返回执行结果字典的生成器。
- `ask_user(...)`：输入问题和候选项，输出一个表示“需要人工介入”的结构化中断对象。
- `first_init_driver()`：输入无，输出浏览器驱动的初始化副作用。
- `web_scan(...)`：输入页面扫描选项和可选标签页切换参数，输出当前标签页元数据及可选的页面内容。
- `format_error(e)`：输入异常对象，输出一条格式化后的错误描述字符串。
- `log_memory_access(path)`：输入文件路径，输出对记忆访问统计的记录副作用。
- `web_execute_js(...)`：输入 JavaScript 脚本和浏览器上下文参数，输出脚本执行结果及页面变化信息。
- `expand_file_refs(...)`：输入含 `{{file:...}}` 引用的文本，输出将引用展开后的完整文本。
- `file_patch(...)`：输入目标文件路径、旧文本块和新文本块，输出一次局部替换操作的结果字典。
- `_scan_files(...)`：输入扫描根目录和深度，输出一个逐项产生文件名与路径的生成器。
- `file_read(...)`：输入文件路径和读取范围/关键词参数，输出格式化后的文件内容字符串。
- `smart_format(...)`：输入任意数据和长度限制，输出截断后的短字符串表示。
- `consume_file(...)`：输入目录和文件名，输出文件内容，并附带“读取后删除”的副作用。
- `get_global_memory()`：输入无，输出拼接好的全局记忆提示词文本。

**类**
```python
class GenericAgentHandler(BaseHandler):
    def __init__(self, parent, last_history=None, cwd='./temp')

    def _get_abs_path(self, path)

    def _extract_code_block(self, response, code_type)

    def do_code_run(self, args, response)

    def do_ask_user(self, args, response)

    def do_web_scan(self, args, response)

    def do_web_execute_js(self, args, response)

    def do_file_patch(self, args, response)

    def do_file_write(self, args, response)

    def do_file_read(self, args, response)

    def _in_plan_mode(self)

    def _exit_plan_mode(self)

    def enter_plan_mode(self, plan_path)

    def _check_plan_completion(self)

    def do_update_working_checkpoint(self, args, response)

    def do_no_tool(self, args, response)

    def do_start_long_term_update(self, args, response)

    def _get_anchor_prompt(self, skip=False)

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason)
```

- `__init__(...)`：输入父对象、历史信息和工作目录，输出一个带有运行时状态容器的处理器实例。
- `_get_abs_path(path)`：输入相对路径，输出相对于当前工作目录解析出的绝对路径。
- `_extract_code_block(response, code_type)`：输入模型响应对象和代码类型，输出响应文本中最后一个匹配的代码块内容。
- `do_code_run(args, response)`：输入工具参数和响应对象，输出一个 `StepOutcome`，其核心结果来自代码执行结果。
- `do_ask_user(args, response)`：输入提问参数和响应对象，输出一个要求暂停并等待用户输入的 `StepOutcome`。
- `do_web_scan(args, response)`：输入网页扫描参数和响应对象，输出一个封装页面扫描结果的 `StepOutcome`。
- `do_web_execute_js(args, response)`：输入 JS 执行参数和响应对象，输出一个封装浏览器脚本执行结果的 `StepOutcome`。
- `do_file_patch(args, response)`：输入文件 patch 参数和响应对象，输出一个封装局部文件修改结果的 `StepOutcome`。
- `do_file_write(args, response)`：输入文件写入参数和响应对象正文，输出一个封装整文件写入结果的 `StepOutcome`。
- `do_file_read(args, response)`：输入文件读取参数和响应对象，输出一个封装文件内容文本的 `StepOutcome`。
- `_in_plan_mode()`：输入无，输出当前是否处于 plan 模式及其关联路径。
- `_exit_plan_mode()`：输入无，输出退出 plan 模式的状态变更副作用。
- `enter_plan_mode(plan_path)`：输入计划文件路径，输出被记录下来的计划路径，并开启 plan 模式。
- `_check_plan_completion()`：输入无，输出当前计划文件中未完成事项的数量。
- `do_update_working_checkpoint(args, response)`：输入工作记忆更新参数和响应对象，输出一个封装记忆检查点更新结果的 `StepOutcome`。
- `do_no_tool(args, response)`：输入本轮响应上下文，输出一个决定继续、重试、拦截或直接结束的 `StepOutcome`。
- `do_start_long_term_update(args, response)`：输入当前响应上下文，输出一个用于启动长期记忆总结流程的 `StepOutcome`。
- `_get_anchor_prompt(skip=False)`：输入是否跳过拼接，输出包含历史、轮次和工作记忆的提示词字符串。
- `turn_end_callback(...)`：输入本轮响应、工具调用结果和回合状态，输出下一轮要注入的提示词字符串。

### prompt构成

这三个文件里，prompt 的组装可以理解成三层协作：

1. `agentmain.py` 负责“发起一次任务”时的初始 prompt 组装和任务分发。
2. `agent_loop.py` 负责“同一任务内每一轮”把上轮结果变成下一轮 prompt。
3. `ga.py` 负责“工具执行后”产出 `next_prompt`，并在回合结束时统一补充工作记忆、规则提醒和外部干预。

下面按这条链路展开。

**1. 在 `agentmain.py`：一次任务开始时如何组装首轮 prompt**

入口在 [`GeneraticAgent.run()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:140>)。

每当 `put_task()` 放入一个任务后，`run()` 会取出 `raw_query`，然后做三件和 prompt 直接相关的事：

- 生成 system prompt  
  来源是 [`get_system_prompt()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:36>)。
  它的内容由三部分拼起来：
  - `assets/sys_prompt{lang_suffix}.txt`：来自静态系统提示模板
  - `Today: ...`：来自 `time.strftime(...)` 生成的当天日期
  - [`get_global_memory()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:554>)：来自 `ga.py`，会继续读取
    - `memory/global_mem_insight.txt`
    - `assets/insight_fixed_structure{suffix}.txt`
    - 并写入 `cwd` / memory 区域说明

- 追加运行时额外 system prompt  
  在 [`run()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:151>) 中：
  `sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, 'extra_sys_prompt', '')`
  也就是说，如果底层 LLM backend 配了 `extra_sys_prompt`，它会直接拼到系统提示后面。
  这部分来源于 `llmcore` 初始化出的 backend 对象配置。

- 生成首轮 user prompt  
  首轮 user prompt 就是当前任务文本 `raw_query` 本身，在 [`agent_runner_loop(...)`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:42>) 初始化 `messages` 时放入：
  ```python
  messages = [
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": user_input}
  ]
  ```
  这里的 `user_input` 来自 `agentmain.py` 传入的 `raw_query`。

还有一层容易忽略：跨任务工作记忆继承。

在 [`run()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:154>) 里，如果上一个 `handler` 的 `working['key_info']` 存在，会被拷贝到新建的 `GenericAgentHandler` 中，并附加一条系统说明：
“这是前几次对话前设置的 key_info...”
这部分不会进入首轮 `system_prompt`，但会在之后 `ga.py` 生成 `next_prompt` 时进入工作记忆块。

所以，一次新任务的首轮 prompt 生成时机是：
- 任务被 `run()` 取出后
- 在调用 `agent_runner_loop(...)` 之前
- 由 `system_prompt + raw_query` 组成首轮消息

**2. 在 `agent_loop.py`：每轮 prompt 如何流转**

核心函数是 [`agent_runner_loop(...)`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:42>)。

它维护一个 `messages` 变量，控制每轮送给模型的输入。

**首轮**
初始化时：
```python
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input}
]
```
来源分别是：
- `system_prompt`：来自 `agentmain.get_system_prompt()` 和 backend 的 `extra_sys_prompt`
- `user_input`：来自本次任务文本 `raw_query`

**每轮调用模型**
在 while 循环中，每一轮都会执行：
```python
response_gen = client.chat(messages=messages, tools=tools_schema)
```
这里本轮 prompt 的来源是当前 `messages`。
`tools_schema` 则来自 `agentmain.py` 中载入的 `assets/tools_schema*.json`，它不是 prompt 正文，但会作为 tools 描述一起传给模型。

**模型返回后如何形成下一轮 prompt**
模型返回 `response` 后，loop 会：

- 解析 `response.tool_calls`
  - 如果没有工具调用，造一个伪工具 `no_tool`
  - 如果有，就把工具名和参数解出来

- 逐个调用 handler 分发工具  
  入口在 [`BaseHandler.dispatch(...)`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:18>)  
  它会去找 `ga.py` 里的 `do_xxx(...)` 方法，并拿到一个 [`StepOutcome`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:4>)。

`StepOutcome` 里最关键的两个字段是：
- `data`：本次工具结果，后续会变成 `tool_results`
- `next_prompt`：供下一轮模型继续推理的用户消息内容

**多工具结果如何汇总**
每个工具执行后：
- `outcome.data` 会被收集进 `tool_results`
- `outcome.next_prompt` 会被放进 `next_prompts` 集合

见 [`agent_runner_loop()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:75>) 到 [`102`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:102>)。

**回合结束时如何真正生成下一轮 prompt**
在所有工具跑完后，loop 执行：
```python
next_prompt = handler.turn_end_callback(
    response, tool_calls, tool_results, turn, '\n'.join(next_prompts), exit_reason
)
messages = [{"role": "user", "content": next_prompt, "tool_results": tool_results}]
```
这一步非常关键，说明从第二轮开始，`messages` 不再显式携带 `system` 消息和旧 `user` 消息，而是只放一个新的 `user` 消息。

但代码注释已经说明原因：
`history is kept in *Session`
也就是历史上下文由 `client` / `backend.history` 保持，当前轮只额外补一条新的 user prompt。

因此，在 `agent_loop.py` 中，每轮 prompt 的生成时机是：
- 模型完成本轮输出后
- 工具调用完成后
- `ga.py` 返回的各个 `next_prompt` 被合并后
- 再经过 `turn_end_callback()` 二次加工
- 最终成为下一轮唯一新增的 `user` 消息

**3. 在 `ga.py`：如何整合每次的 prompt**

`ga.py` 主要在两个层次参与 prompt 生成：

- 工具级：每个 `do_*` 方法直接产出一个基础 `next_prompt`
- 回合级：[`turn_end_callback(...)`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:525>) 统一补充和修正

**3.1 工具级 next_prompt：由各个 `do_*` 方法生成**

大多数工具方法在执行完后都会返回：
```python
return StepOutcome(result, next_prompt=...)
```

最常见的来源是 [`_get_anchor_prompt(skip=False)`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:513>)。

它生成的内容来源于：
- `self.history_info[-40:]`：最近 40 条摘要历史，来自前几轮 `turn_end_callback()` 写入的 `[Agent] ...`
- `self.current_turn`：当前轮次，来自 `agent_loop.py` 每轮设置的 `handler.current_turn = turn`
- `self.working['key_info']`：工作记忆重点，可能来自
  - `do_update_working_checkpoint(...)`
  - 上一个 handler 跨任务继承
  - `turn_end_callback()` 中读取 `_keyinfo`
- `self.working['related_sop']`：相关 SOP 路径，来自 `do_update_working_checkpoint(...)`

也就是说，`_get_anchor_prompt()` 产出的内容本质上是“工作记忆锚点 prompt”。

生成时机：
- 每次诸如 `do_code_run`、`do_file_patch`、`do_file_read`、`do_web_execute_js` 等工具执行结束时
- 作为这些工具返回的基础 `next_prompt`

特殊工具的 `next_prompt` 来源不同：

- [`do_web_scan`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:314>)  
  固定给 `"\n"`，等于只让模型看工具结果，不额外注入工作记忆。

- [`do_ask_user`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:307>)  
  返回空字符串并 `should_exit=True`，时机是需要人工介入时，此时不再生成下一轮 prompt。

- [`do_start_long_term_update`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:496>)  
  会构建一个很长的记忆总结提示，其内容来源于：
  - 方法内部固定的一大段“如何更新长期记忆”的说明文本
  - [`get_global_memory()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:554>) 产生的全局记忆结构
  - `./memory/memory_management_sop.md` 的读取结果  
  生成时机是 agent 判断“任务完成后值得沉淀长期记忆”并调用该工具时。

- [`do_no_tool`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:444>)  
  会根据本轮自然语言回复内容动态给出：
  - 重试提示
  - plan 模式拦截提示
  - 大代码块但没工具调用的纠偏提示
  - 或 `None` 表示任务结束  
  生成时机是模型本轮没有显式调用工具时。

**3.2 回合级整合：`turn_end_callback()` 统一改写下一轮 prompt**

这是 `ga.py` 对 prompt 影响最大的一层。

它接收：
- 本轮模型回复 `response`
- 工具列表 `tool_calls`
- 工具结果 `tool_results`
- 当前轮次 `turn`
- 已由工具阶段拼出来的 `next_prompt`
- `exit_reason`

然后继续加工。

主要追加来源有五类。

**第一类：摘要历史**
来源：
- 优先取 `response.content` 中的 `<summary>...</summary>`
- 如果没有，就根据本轮工具调用自动生成一句摘要

随后写入 `self.history_info`：
```python
self.history_info.append(f'[Agent] {summary}')
```
这会影响之后 `_get_anchor_prompt()` 中的 `<history>` 内容。

生成时机：
- 每一轮结束时都会发生

**第二类：轮次规则提示**
来源：
- `turn % 7 == 0` 时追加“禁止无效重试，必须换策略”
- `turn % 65 == 0` 时追加“必须 ask_user”
- `turn % 10 == 0` 时追加 [`get_global_memory()`](</Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:554>)

所以 `get_global_memory()` 不只在 system prompt 首轮出现一次，还会在任务进行中每 10 轮重新注入一次。

生成时机：
- 每轮结束时按 turn 条件触发

**第三类：Plan 模式提示**
来源：
- `self.working['in_plan_mode']`，由 `enter_plan_mode(plan_path)` 设置
- `_check_plan_completion()` 读取 plan 文件中的 `[ ]` 未完成项数量

会做两件事：
- 每 5 轮在前面强插 `[Plan Hint] ... 必须 file_read(plan)`
- 轮次过高时强制 ask_user

生成时机：
- 处于 plan 模式的回合结束时

**第四类：任务目录下的外部注入**
来源：
- `consume_file(self.parent.task_dir, '_keyinfo')`
- `consume_file(self.parent.task_dir, '_intervene')`

作用：
- `_keyinfo` 并入 `working['key_info']`
- `_intervene` 直接拼到 `next_prompt` 末尾

这说明 prompt 不只来自模型和代码内部，也可能来自外部文件投喂。

生成时机：
- 每轮结束时检查一次
- 只要对应文件存在就消费并注入

**第五类：done hooks**
`agent_loop.py` 中有一段：
```python
if len(next_prompts) == 0 or exit_reason:
    if len(handler._done_hooks) == 0 or exit_reason.get('result', '') == 'EXITED': break
    next_prompts.add(handler._done_hooks.pop(0))
```
这说明当本轮看似结束、没有正常 next_prompt 时，如果 `handler._done_hooks` 里还有内容，就会拿这个 hook 字符串当作新的 prompt 继续下一轮。

它的来源是 `handler._done_hooks` 这个列表。`ga.py` 里初始化了它，但当前文件中没看到填充逻辑，说明可能由别处动态注入。

生成时机：
- 没有常规 `next_prompt` 或已经进入退出流程，但仍存在 done hook 时

**4. 一条完整的 prompt 生命周期**

可以把一次任务里的 prompt 组装总结成下面这条链：

1. `agentmain.py` 收到任务文本 `raw_query`
2. `agentmain.get_system_prompt()` 读取系统模板、当天日期、全局记忆，形成首轮 system prompt
3. `agent_loop.py` 用
   - system prompt
   - 首轮 user prompt = `raw_query`
   初始化 `messages`
4. 模型返回回复和工具调用
5. `agent_loop.py` 分发到 `ga.py` 的 `do_*` 方法
6. 每个 `do_*` 方法产出自己的 `StepOutcome.next_prompt`
   - 常见来源是 `_get_anchor_prompt()`
   - 特殊场景来源于长期记忆模板、纠偏提示、空串等
7. `agent_loop.py` 汇总多个 `next_prompt`，拼成一个字符串
8. `ga.py.turn_end_callback()` 再追加
   - 摘要历史
   - 轮次规则
   - 每 10 轮的全局记忆
   - plan 模式提示
   - 外部 `_keyinfo` / `_intervene`
9. `agent_loop.py` 把最终结果写成下一轮的唯一 user message：
   ```python
   {"role": "user", "content": next_prompt, "tool_results": tool_results}
   ```
10. 进入下一轮 `client.chat(...)`

**5. 最关键的结论**

这个系统不是“每轮都重新拼一个完整 system+history+user prompt”，而是：

- 首轮由 `agentmain.py` 明确提供完整的 `system + user`
- 后续轮由 `agent_loop.py` 只补一个新的 user prompt
- 这个新的 user prompt 主要由 `ga.py` 生成
- 更早的完整历史不在 `messages` 数组里显式重复，而是保存在 `llmclient.backend.history` 这个 session 里

如果你想，我下一步可以继续给你画一张更具体的“时序图版”说明，把 `agentmain.run() -> agent_runner_loop() -> dispatch() -> do_*() -> turn_end_callback()` 串成逐步流程。

### 文件树和模块划分

```bash
evolving_agent/
  tools/
    __init__.py
    formatter.py
    schemas.py

    code_tools.py
    file_tools.py
    human_tools.py
    memory_tools.py
    plan_tools.py
    web_tools.py

    handler.py
```

在*_tools中包含1. 真实执行的函数 2. 将执行结果包装成stepoutcome的函数;

handler负责:派发工具,和prompt设置,以及和agentloop,mainagent对接;

```bash
tools/
  formatter.py   # 格式化和截断
  schemas.py     # 工具 schema
  *_tools.py     # 具体工具能力
  handler.py     # 把工具结果适配成 StepOutcome
```

#### 修改计划

| **文件**        | **职责**                                             | **对应原** ga.py **内容**                                    |
| --------------- | ---------------------------------------------------- | ------------------------------------------------------------ |
| __init__.py     | 工具包导出入口                                       | 新增                                                         |
| formatter.py    | 错误格式化、文本截断、对象格式化                     | format_error、smart_format                                   |
| schemas.py      | 工具 schema 定义                                     | 原 assets/tools_schema*.json 的 Python 化或加载入口          |
| code_tools.py   | 本地代码执行                                         | code_run                                                     |
| file_tools.py   | 文件读取、写入、patch、文件引用展开                  | file_read、file_patch、expand_file_refs、_scan_files、consume_file |
| human_tools.py  | 人工中断                                             | ask_user                                                     |
| memory_tools.py | 工作记忆、全局记忆、长期记忆候选                     | get_global_memory、log_memory_access、do_update_working_checkpoint、do_start_long_term_update |
| plan_tools.py   | 计划模式                                             | _in_plan_mode、_exit_plan_mode、enter_plan_mode、_check_plan_completion |
| web_tools.py    | Web 能力，占位或轻量实现                             | first_init_driver、web_scan、web_execute_js                  |
| handler.py      | 工具分发、上下文管理、StepOutcome 包装、回合结束处理 | GenericAgentHandler                                          |

### 问题

1. 缺 json_default 实现
   现状：

   - ga.py 依赖 from agent_loop import ... json_default
   - 当前仓库里没有 agent_loop.py
   - 全项目也没有 json_default 定义

   影响：

   - do_web_scan
   - do_web_execute_js
     这两个方法里序列化结果时会缺依赖。

2. 缺 agent_loop.py 模块
   现状：

   - ga.py 顶部显式依赖它
   - 当前仓库没有这个文件
   - 但 tools/handler.py (line 1) 已经自己放了 StepOutcome 和 BaseHandler

   影响：

   - 如果你打算继续保留 ga.py 可独立运行，当前会报导入错误
   - 如果只在 tools/handler.py 内完成迁移，则不是硬阻塞

3. 缺 assets/ 目录及其配套文件
   现状：

   - 当前仓库没有 assets/
   - 但 ga.py / 新拆出的 memory/code 逻辑都引用过：
     - assets/code_run_header.py
     - assets/insight_fixed_structure.txt
     - assets/insight_fixed_structure_en.txt

   影响：

   - code_run 还能运行，只是不会注入 header
   - get_global_memory 会降级为空 prompt
   - do_start_long_term_update 的上下文会变弱

4. 缺 memory 文本资源文件
   现状：

   - 当前 memory/ 下只有占位 python 模块
   - 没有：
     - memory/global_mem_insight.txt
     - memory/memory_management_sop.md

   影响：

   - get_global_memory() 基本无内容
   - do_start_long_term_update() 会走 “Memory Management SOP not found”

5. 缺外部 web 依赖
   现状：

   - web_tools.py 会尝试导入：
     - simphtml
     - TMWebDriver

   影响：

   - GenericAgentHandler 可以定义成功
   - 但真正调用 do_web_scan / do_web_execute_js 时，大概率会返回错误或初始化失败

6. parent 对象接口目前是隐式约定，未抽象
   GenericAgentHandler 默认要求 parent 至少可能有：

   - verbose
   - task_dir
   - _turn_end_hooks

   影响：

   - 类能实例化
   - 但如果上层 parent 没这些字段，turn_end_callback 的某些逻辑会退化或报错
   - 这部分建议在 handler 里统一用 getattr(parent, ..., default) 兜底

**不缺的部分**

这些已经具备，可以直接支持 handler：

- StepOutcome 和 BaseHandler
  在 tools/handler.py (line 1)
- 文件工具
  在 tools/file_tools.py (line 1)
- 代码执行工具
  在 tools/code_tools.py (line 1)
- memory / plan / web / formatter 基础函数
  都已经拆到 tools/ 里了