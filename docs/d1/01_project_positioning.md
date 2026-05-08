GenericAgent 是一个面向本地真实环境的通用执行型 Agent 框架，它已经完成了执行闭环、记忆闭环和长任务闭环三条主链路，目标不是做一次性问答，而是做一个可持续成长、可恢复、可自主运行的个人 Agent 系统。

### **一、项目定位**

GenericAgent 不是一个普通聊天机器人，而是一个面向本地真实环境的通用执行型 Agent 框架。它的目标不是“回答问题”，而是让大模型真正接管电脑和数字环境，完成浏览器操作、文件处理、脚本执行、桌面交互、移动端控制，以及长期记忆沉淀。

从产品定位上看，它更像一个“可长期演化的个人 Agent 内核”：
- 能执行
- 能记忆
- 能恢复
- 能规划
- 能自主运行

### **二、项目面向的核心场景**

这个项目主要面向以下几类场景：

1. 本地自动化助手  
    用户希望 Agent 直接帮自己改文件、跑脚本、整理数据，而不是只给建议。
2.  ~~浏览器与网页执行助手~~ 
    用户希望 Agent 直接操作自己已经登录的真实浏览器，完成网页读取、表单填写、跨标签处理等任务。
3. 长任务处理助手  
    很多任务不是一轮完成的，而是多步骤、多文件、多轮迭代，这就需要任务规划、状态保持和中断恢复。
4. 个人长期记忆助手  
    Agent 不只是一次性工作，而是能记住用户环境、配置、偏好和 SOP，下次继续复用。
5. 自主与定时任务助手  
    当用户不在线时，Agent 可以根据定时计划执行任务，或者在空闲时自主行动、写报告、积累经验。
6. 多终端统一 Agent 能力  
    同一个 Agent 内核，可以接不同前端，比如 Web UI、CLI、聊天前端，而不是每个入口重新实现一套逻辑。

### 三. 需求分析

**功能性需求（FR）**

- FR1：用户输入一句自然语言即可启动任务，任务可跨多轮自我纠错直到完成（需要 Turn 循环与退出条件）。agent_loop.py
- FR2：必须能“真的在本机做事”，而不是只写计划：至少覆盖文件系统、代码执行、浏览器控制、（可选）ADB 等执行面。ga.py README.md
- FR3：必须支持多入口（CLI/GUI/IM Bot），且命令体验一致（/new /stop /continue 等）。README.md chatapp_common.py
- FR4：必须可中止长任务并保持进程稳定（stop signal、后台线程、队列）。agentmain.py
- FR5：必须能恢复“上次聊到哪/做到哪”，包含会话列表、恢复完整对话或摘要、以及清空/新对话能力。continue_cmd.py
- FR6：必须把执行过程沉淀成可复用知识（summary/history 轨迹 + 分层记忆 + 会话归档）。ga.py scheduler.py
- FR7:   很多任务天然是长任务。  不是一次问答，而是几十轮、多子任务、带中断恢复的执行过程，所以必须有 planning、checkpoint 和 verify

**非功能性需求（NFR）**

- NFR1：低依赖、易启动、跨平台（macOS/Windows），新手也能跑起来（文档明确最小安装与配置）。GETTING_STARTED.md
- NFR2：Token/上下文成本可控：要求把“能复用的信息”压缩成 `<summary>`/`<history>`，并做工具描述的周期性重置，避免上下文爆炸。agent_loop.py llmcore.py
- NFR3：可观测与可追溯：每轮 Prompt/Response 都要落盘，便于调试、回放、恢复与归档。llmcore.py
- NFR4：可扩展的模型后端：同一框架支持不同 API 兼容形态（oai/claude/native 等），变量命名即路由策略。GETTING_STARTED.md

**约束与设计取舍（从实现倒推）**

- 约束1：会话日志以“进程 PID”为主键写入（model_responses_<pid>.txt），意味着一个进程天然对应一个连续会话流；跨进程/重启后的“会话级 id”主要靠文件粒度与 snapshot/归档，而不是数据库式会话表。llmcore.py continue_cmd.py
- 约束2：恢复优先走 native 格式（可重建 backend.history），否则必须保证至少能抽取 `<summary>` 做降级恢复（要求每轮都产出 summary）。continue_cmd.py ga.py
- 取舍：调度器不直接执行“工具级操作”，而是返回一段高层任务提示词，引导 Agent 按 SOP 执行并写报告（降低调度器复杂度，保持内核一致）。scheduler.py



### **三、项目已经实现的核心功能**

从当前代码和模块来看，这个项目已经完成了完整的 Agent 基础能力建设。

第一类，是执行能力：
- 多轮 Agent Loop
- 工具调用与工具分发
- 文件读写与精细 patch
- Python / shell 执行
- ~~浏览器扫描与 JS 控制~~
- ask_user 人工中断

第二类，是模型接入能力：
- 支持 Claude / OpenAI-compatible / Native tool calling
- 支持流式输出
- 支持多模型切换和 fallback
- 支持上下文裁剪和长对话控制

第三类，是记忆能力：
- L1 全局索引记忆
- L2 环境事实记忆
- L3 任务 SOP / 工具脚本记忆
- L4 历史会话归档
- 工作记忆 checkpoint
- 长期记忆结算入口

第四类，是长任务能力：
- plan mode
- subagent 委托
- verify 独立验证
- 计划文件驱动执行
- 长轮次防失控控制

第五类，是会话恢复能力：
- Prompt / Response 日志落盘
- `/continue` 恢复历史会话
- snapshot 快照当前上下文
- UI 回放恢复历史消息

第六类，是自主与定时运行能力：
- autonomous 空闲自主行动
- scheduler 配置化定时任务
- reflect 模式后台轮询触发

第七类，~~是多模态与真实环境扩展~~：
- OCR
- Vision API 模板
- UI 检测
- Android ADB UI 控制
- 桌面键鼠控制

### **四、项目的核心架构亮点**

这个项目最大的亮点，不是工具多，而是它把一个可持续运行的 Agent 闭环做得很完整。

1. 最小 Agent Loop  
项目把核心循环压缩得非常小。整体逻辑就是：
用户输入 -> LLM 推理 -> 工具调用 -> 工具结果 -> 下一轮 prompt -> 直到结束  
这个 loop 简洁，但足以支撑复杂任务。

2. 工具层与循环层解耦  
`agent_loop.py` 只负责调度，`ga.py` 只负责执行工具，这种分层让系统非常清晰，也更容易扩展。

3. LLM 协议统一  
`llmcore.py` 把不同模型的接口、thinking、tool_use、history 和日志统一成同一套内部结构，上层 loop 几乎不用==关心厂商差异==。

4. 分层记忆设计  
这个项目不是简单地把历史越堆越长，而是把记忆分成索引、事实、SOP、历史归档四层。这样既控制上下文成本，也能保证长期复用。

5. 长任务闭环完整  
复杂任务不是直接冲，而是支持探索、规划、执行、验证、修复，这让 Agent 从“能跑”提升到“能做复杂事”。

6. 会话恢复做得很工程化  
日志不是为了调试而已，而是直接服务于 `/continue` 恢复、UI 回放、L4 历史沉淀，这一点非常适合真实使用场景。

### **二、项目已经完成了哪些功能**

从现有实现反推，项目已经完成的核心功能可以概括成下面几类。

**1. Agent 基础执行能力**
- 多轮 Agent loop
- 工具调用解析与分发
- 工具结果回注下一轮
- 中断、退出、继续执行控制
- 最大轮数与失败重试控制

对应模块：
- [agent_loop.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agent_loop.py:1)
- [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:1)

**2. 模型接入与协议兼容**
- 支持 Claude / OpenAI-compatible / Native Claude / Native OAI
- 支持流式输出
- 支持 tool calling 与文本协议式 tool use
- 支持多模型切换与 fallback
- 支持上下文裁剪与日志落盘

对应模块：
- [llmcore.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/llmcore.py:1)
- [agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:1)

**3. 文件与代码自动化**
- 文件读取
- 文件局部 patch
- 整体写文件
- Python / shell 执行
- 代码输出和日志收集
- 子任务文件协议

对应模块：
- [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:12)
- [agentmain.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/agentmain.py:207)

**4. 浏览器自动化**
- 读取当前页面简化 HTML
- 获取 tab 列表
- 执行任意 JS
- 利用真实浏览器登录态
- CDP bridge 扩展能力
- 跨 tab、cookie、上传等复杂 Web 操作经验沉淀

对应模块：
- [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:113)
- [memory/tmwebdriver_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/tmwebdriver_sop.md:1)

**5. 记忆系统**
- L1 极简索引
- L2 全局事实
- L3 任务 SOP / 脚本
- L4 会话归档
- 长期记忆结算入口
- 工作记忆 checkpoint

对应模块：
- [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:432)
- [ga.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/ga.py:496)
- [memory/memory_management_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/memory_management_sop.md:1)

**6. 长任务 / 计划模式**
- 复杂任务进入 plan mode
- 探索、规划、执行、验证分阶段
- subagent 委托
- verify subagent 独立验收
- 计划文件驱动长任务

对应模块：
- [memory/plan_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/plan_sop.md:1)
- [memory/subagent.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/subagent.md:1)
- [memory/verify_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/verify_sop.md:1)

**7. 会话恢复与归档**
- `model_responses_<pid>.txt` 日志
- `/continue` 列出并恢复历史会话
- snapshot 快照当前日志
- UI 回放历史消息
- L4 历史压缩归档

对应模块：
- [frontends/continue_cmd.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/frontends/continue_cmd.py:1)
- [memory/L4_raw_sessions/compress_session.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/L4_raw_sessions/compress_session.py:1)

**8. 自主与定时运行**
- 空闲自主行动
- 定时任务 JSON 调度
- 后台反射式运行
- 执行报告落盘

对应模块：
- [reflect/autonomous.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/autonomous.py:1)
- [reflect/scheduler.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/reflect/scheduler.py:1)

**9. 多模态 / GUI / Mobile 扩展**
- 本地 OCR
- Vision API 模板
- UI 检测
- Android UI dump 与点击
- 桌面键鼠控制

对应模块：
- [memory/ocr_utils.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ocr_utils.py:1)
- [memory/ui_detect.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ui_detect.py:1)
- [memory/adb_ui.py](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/adb_ui.py:1)
- [memory/ljqCtrl_sop.md](/Users/suny/workspace/python_projects/generateAgent/GenericAgent/memory/ljqCtrl_sop.md:1)

