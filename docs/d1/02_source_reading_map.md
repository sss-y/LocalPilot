# 源头阅读地图

## 1. 原项目核心链路

后续可以:如果你要，我可以下一步把这三张图再整理成更适合汇报的“PPT版”，统一成一页一张的模块化样式。

**一：执行闭环**

```text
User
 |
 v
Frontend / CLI / ChatApp
(stapp.py / stapp2.py / tgapp.py / qqapp.py ...)
 |
 v
GeneraticAgent.put_task()
(agentmain.py)
 |
 v
GeneraticAgent.run()
- 取 task_queue
- 组装 system_prompt
- 创建 GenericAgentHandler
 |
 v
agent_runner_loop()
(agent_loop.py)
 |
 +--> LLMClient.chat(messages, tools)
 |    (llmcore.py)
 |
 +--> 解析 tool_calls
 |
 +--> GenericAgentHandler.dispatch()
 |    (ga.py)
 |      |
 |      +--> do_file_read()
 |      +--> do_file_patch()
 |      +--> do_file_write()
 |      +--> do_code_run()
 |      +--> do_web_scan()
 |      +--> do_web_execute_js()
 |      +--> do_ask_user()
 |      +--> do_update_working_checkpoint()
 |      +--> do_start_long_term_update()
 |
 v
StepOutcome
- data
- next_prompt
- should_exit
 |
 v
turn_end_callback()
- 写 summary
- 注入 working memory
- 注入危险提示 / 长轮次提示
 |
 v
Next Prompt / Continue Loop
 |
 v
Final Response / ask_user Interrupt / EXIT
 |
 v
display_queue -> Frontend Render
```

**二：记忆闭环**:长期能力的演绎来自工具执行的结果验证

```text
Task Execution
 |
 v
工具执行结果 / 验证结果
(file_read / code_run / web_scan / web_execute_js ...)
 |
 v
GenericAgentHandler
 |
 +--> update_working_checkpoint
 |    |
 |    v
 |    Working Memory
 |    - key_info
 |    - related_sop
 |    - passed_sessions
 |    (当前任务短期记忆)
 |
 +--> start_long_term_update
      |
      v
读取 memory_management_sop.md
 |
 v
Memory Classification
- L1: global_mem_insight.txt
- L2: global_mem.txt
- L3: memory/*.md / *.py
- L4: L4_raw_sessions/*
 |
 v
最小化 patch / 新建 SOP / 新建工具脚本
 |
 v
get_global_memory()
 |
 v
下次任务启动时注入 system_prompt
(agentmain.py -> get_system_prompt())
 |
 v
LLM 在新任务中优先命中记忆 / SOP / 工具脚本
 |
 v
新执行结果再次进入记忆判定
```

**三：长任务闭环**

```text
User Complex Task
 |
 v
Frontend / CLI
 |
 v
GeneraticAgent.run()
 |
 v
agent_runner_loop()
 |
 v
判断任务复杂度
- 多步骤
- 多文件
- 条件分支
- 长轮次
 |
 v
读取 plan_sop.md
 |
 v
进入 Plan Mode
handler.enter_plan_mode("./plan_xxx/plan.md")
 |
 v
探索阶段
 |
 +--> 启动 subagent
 |    (agentmain.py --task ...)
 |    |
 |    +--> 只读探测环境
 |    +--> 输出 exploration_findings.md
 |
 v
主 agent 读取 findings + SOP
 |
 v
生成 plan.md
- 步骤
- 依赖
- [D] 委托
- [VERIFY] 验证
 |
 v
执行阶段循环
 |
 +--> file_read(plan.md) 找第一个 [ ]
 |
 +--> 执行当前步骤
 |    |
 |    +--> 主 agent 自做
 |    +--> 或 subagent 委托
 |
 +--> Mini Verify
 |
 +--> file_patch(plan.md)
 |    [ ] -> [✓ 结果]
 |
 v
重复直到 plan.md 无残留 [ ]
 |
 v
验证阶段
 |
 +--> 启动 verify subagent
 |    |
 |    +--> 读 verify_sop.md
 |    +--> 独立验证交付物
 |    +--> 输出 VERDICT: PASS / FAIL / PARTIAL
 |
 v
主 agent 收取 verdict
 |
 +--> PASS -> 完成任务
 |
 +--> FAIL -> 回写 plan.md 追加 [FIX] -> 继续执行闭环
 |
 v
任务完成
 |
 +--> update_working_checkpoint(完成态)
 +--> start_long_term_update(必要时)
 |
 v
历史归档 / L4 沉淀 / 下次可恢复
```

## 2. 复刻功能

| 源码                      | 只看什么                                                     | 执行时机                                                     | 功能                                                         | 问题                     |
| ------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------ |
| agentmain.py              | GeneraticAgent 类、put_task()、run()、get_system_prompt()    | 用户发起一次query,将query视为任务,执行put_task()             |                                                              |                          |
| agent_loop.py             | agent_runner_loop()、StepOutcome 使用位置、工具结果如何回写  | 对一个task执行任务                                           |                                                              |                          |
| ga.py                     | GenericAgentHandler、dispatch()、do_file_read、do_file_patch、do_code_run、start_long_term_update | 工具调用                                                     | 四个功能,详见文档<br />  1. 实现 Agent 可调用的本地工具：代码执行、文件读写、浏览器扫描、JS 执行、人工中断 <br />2. 定义 GenericAgentHandler，把 LLM 产生的 tool call 映射成实际 Python 行为<br />3.  维护短期工作记忆 working，并在每轮后把 <history>、key_info 等重新注入下一轮 <br /> 4. 提供长期记忆入口 get_global_memory()，把 L1 索引注入系统 prompt |                          |
| llmcore.py                | trim_messages_history、消息裁剪、模型调用入口                |                                                              | 1. 日志信息的写入<br />2. 同一工具调用结果的格式;<br />3. 模型调用的接口和上下文压缩处理的位置 |                          |
| assets/tools_schema.json  | 工具 schema 的字段设计                                       |                                                              | 使用json结构介绍工具的描述和参数信息;                        |                          |
| memory/                   | SOP 文件类型、global memory 文件、L4 归档结构                | 1. l4归档通过定时任务执行<br />2. l2和l3的写入通过工具完成<br />3. l1具有初始化,后续通过工具只修改部分内容,不重写文件 | 详情见memory.md                                              |                          |
| frontends/continue_cmd.py | /continue 恢复思路                                           | 1. continue指令支持恢复全部的历史对话<br />2. continueN指令恢复指定条数的对话 | 列出历史会话：<br>handle() 或 handle_frontend_command() -> list_sessions() -> _pairs() + _preview_text() -> format_list()<br>恢复历史会话：<br>handle() 或 handle_frontend_command() -> reset_conversation() -> restore() -> _parse_native_history() / 摘要降级恢复<br>回放历史到前端：<br>extract_ui_messages() -> _pairs() + _user_text() + _assistant_text() | 用户query生成一个session |
| reflect/scheduler.py      | 只看任务 JSON 字段和触发逻辑                                 | 1. 创建定时任务,自动轮询执行<br />2. 定时12h内置的长期记忆归档 | 详见03/定时任务                                              |                          |