### 接口清单

下面是 `agent_loop.py` 的接口清单，按“核心数据结构 / 处理器接口 / 主流程接口 / 辅助接口”整理，忽略了实现细节和异常处理。

**Core Data Structures**

`@dataclass StepOutcome`
- `data: Any`
- `next_prompt: Optional[str] = None`
- `should_exit: bool = False`
- 数据流转：承载单步工具执行的结果数据、下一轮要发送给模型的提示词，以及是否终止循环的控制信号。

**Handler Interface**

`class BaseHandler`
- `tool_before_callback(self, tool_name, args, response) -> Any`
- 数据流转：输入当前工具名、工具参数和模型响应对象，输出前置钩子的执行结果（通常用于观测或预处理）。

- `tool_after_callback(self, tool_name, args, response, ret) -> Any`
- 数据流转：输入工具名、参数、模型响应和工具执行结果 `ret`，输出后置钩子的执行结果（通常用于记录或补充处理）。

- `turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason) -> str`
- 数据流转：输入本轮模型响应、工具调用列表、工具结果列表、轮次、候选下一提示词和退出原因，输出下一轮真正发送给模型的 prompt。

- `dispatch(self, tool_name, args, response, index=0) -> StepOutcome`
- 数据流转：输入工具名、参数、模型响应和工具序号，路由到对应的 `do_<tool_name>` 方法，并输出统一的 `StepOutcome`。

**Main Loop Interface**

`agent_runner_loop(client, system_prompt, user_input, handler, tools_schema, max_turns=40, verbose=True, initial_user_content=None) -> dict`
- 数据流转：输入模型客户端、系统提示词、用户输入、处理器、工具 schema 和循环控制参数，持续驱动“模型回复 -> 工具调用 -> 生成下一提示词”的多轮流程，最终输出结束原因字典。

**Supporting Interfaces**

`try_call_generator(func, *args, **kwargs) -> Any`
- 数据流转：输入一个普通函数或生成器函数及其参数，统一执行并输出其最终返回值。

`json_default(o) -> Any`
- 数据流转：输入一个不可直接 JSON 序列化的对象，输出可被 JSON 编码的替代表达。

`exhaust(g) -> Any`
- 数据流转：输入一个生成器，完整消费其迭代过程并输出生成器最终的返回值。

`get_pretty_json(data) -> str`
- 数据流转：输入任意数据对象，输出适合展示的格式化 JSON 字符串。

`_clean_content(text) -> str`
- 数据流转：输入模型生成的原始文本，输出压缩冗余后的精简文本。

`_compact_tool_args(name, args) -> str`
- 数据流转：输入工具名和参数字典，输出适合日志展示的紧凑参数字符串。

