# P0 可验证工程基线需求 Spec

## 文档信息

| 字段 | 内容 |
| --- | --- |
| 项目 | LocalPilot |
| 阶段 | P0 — 可验证工程基线 |
| 文档类型 | Requirements Spec |
| 状态 | Requirements Generated / 待用户确认 |
| 语言 | 中文 |
| 主要用途 | 作为后续 Design、任务拆分、AI 生成代码和验收判定的输入 |

## 1. 目标

P0 的目标是为 LocalPilot 建立一条可信、可重复、默认离线的工程验收基线，使维护者、验收者或 AI 编码代理能够在干净检出中判断一个修订是否保持了当前受保护行为。

P0 完成后，验收者应能够获得无歧义证据并回答：

1. 当前修订是否包含完成验收所需的全部工程资产？
2. 当前修订能否在声明的受支持环境中完成一致的验证准备？
3. 全部必需检查是否被发现并实际执行？
4. 默认验证是否完全离线且不依赖个人凭证？
5. 当前用户可见入口和关键行为是否仍然可用？
6. 验收结论是成功、失败还是未完成？

## 2. 问题陈述

当前仓库存在以下工程基线风险：

- 部分测试引用已经不存在或已经迁移的模块、符号和入口。
- 完整测试集合不能稳定完成发现、收集和执行。
- 环境准备尚未形成可重复验证的仓库契约。
- 文档中的部分启动和测试描述可能与当前仓库状态不一致。
- 当前及后续架构重构缺少一个能够证明“没有意外改变现有行为”的统一验收门。
- 本机缓存、未提交文件或个人配置可能造成无法在干净检出中复现的通过结果。

P0 只解决工程基线问题，不借此重写 LocalPilot 的产品行为或核心架构。

## 3. 角色与用户价值

| 角色 | 用户价值 |
| --- | --- |
| 维护者 | 在提交或重构前后获得可信、可重复的验证结论 |
| AI 编码代理 | 根据明确 Requirement 实施变更，并用机器可判定证据证明完成 |
| 验收者 | 在干净检出中独立复现结果，不依赖实现者本机状态 |
| LocalPilot 用户 | P0 完成后，现有受保护入口和工作流不发生非预期变化 |
| P0 批准者 | 根据完整、可追踪的证据决定 P0 是否可以成为后续重构起点 |

## 4. 范围边界

### 4.1 In scope

P0 包含：

- 形成受版本控制的验收资产单一事实来源。
- 从干净检出建立可重复验证环境的能力。
- 一个可被人和自动化调用的统一 P0 基线验收入口。
- 默认离线且不需要真实模型凭证的验证过程。
- 全部必需测试的无错误发现、收集和执行。
- 当前 CLI 启动、核心模块加载、项目路径、上下文历史、模型响应归一化和工具分发等关键现有行为的特征验收。
- 对失败、跳过、未完成和成功状态给出明确、可机器判断的结果。
- 验收证据与本 Spec Requirement 的可追踪映射。
- 与 P0 真实状态一致的启动、验证和开发状态文档。
- 继续排除个人凭证、运行时输出、缓存和本机私有状态。

### 4.2 Out of scope

P0 不包含：

- Session / Client 的结构化协议重构。
- 合并现有 Client 或删除文本工具协议。
- 修改模型工具调用、Provider 请求、fallback 或配置选择语义。
- 重构 Agent Loop、Tool Runtime、Memory、Scheduler 或 Observability 架构。
- 改变交互式 CLI、一次性 task、reflect 或 scheduler 的产品能力与用户工作流。
- 引入新的模型 Provider、工具、存储、网络能力或用户界面。
- 决定依赖管理器、构建工具、测试框架、静态检查器、CI 提供方或包目录布局。
- 全量异步化、并行执行、性能优化或容量扩展。
- 要求真实 Provider 在线调用通过才能接受 P0。
- 修复与 P0 验收链无关的全部历史缺陷。

### 4.3 相邻阶段约束

- P0 为后续 Model I/O、Agent Engine 和 Tool Runtime 重构提供可信起点。
- 后续阶段可以替换 P0 所保护行为的内部实现，但必须继续满足本 Spec，或由新的已批准 Spec 明确修订。
- 已计划在后续阶段删除的文本工具协议只能作为迁移期事实被记录，不得由 P0 固化为长期产品承诺。

## 5. 术语

| 术语 | 定义 |
| --- | --- |
| 工程基线 | 用于判断仓库修订是否可以继续安全重构的一组必需资产、约束、检查和证据 |
| 干净检出 | 仅包含指定仓库修订所记录内容，不依赖未提交文件、旧缓存或相邻项目文件的工作区 |
| 受支持环境 | 仓库明确声明可用于运行 P0 验收的运行时和操作系统组合 |
| 必需检查 | 决定 P0 总体结论、不得静默跳过的检查 |
| 默认离线验证 | 未显式选择在线验证时，不产生任何外部网络请求的验证过程 |
| 受保护行为 | P0 范围内必须保持的当前用户可见行为和关键工程行为 |
| 验收证据 | 能够标识修订、环境、已执行检查、检查结果和总体结论的记录 |
| 未完成 | 验证没有执行完全部必需检查，不能被解释为成功 |

## 6. EARS 标记法

本 Spec 的所有 Acceptance Criteria 使用以下 EARS 句式：

| 类型 | 标记句式 | 用途 |
| --- | --- | --- |
| 普遍性 | **THE LOCALPILOT P0 BASELINE SHALL** ... | 始终成立的要求 |
| 事件驱动 | **WHEN** ...，**THE LOCALPILOT P0 BASELINE SHALL** ... | 某事件发生后的行为 |
| 状态驱动 | **WHILE** ...，**THE LOCALPILOT P0 BASELINE SHALL** ... | 某状态持续期间的行为 |
| 可选特性 | **WHERE** ...，**THE LOCALPILOT P0 BASELINE SHALL** ... | 仅在可选能力存在时适用 |
| 异常处理 | **IF** ...，**THEN THE LOCALPILOT P0 BASELINE SHALL** ... | 不期望条件或失败条件下的行为 |

约束：

- `SHALL` 表示强制要求。
- 每条 Acceptance Criterion 必须能通过检查或证据判定通过或失败。
- Acceptance Criterion 只描述 WHAT，不指定技术栈、类、函数、文件结构或实现算法。
- “适当”“尽可能”“基本通过”“易于”等无法直接验收的措辞不作为通过条件。

## 7. Requirements

### 1. 验收资产的单一事实来源

**User Story：** 作为验收者，我希望能够仅从指定仓库修订获得全部 P0 验收资产，以便不依赖实现者的本机状态独立完成验收。

#### Acceptance Criteria

1.1 **WHEN** 验收者创建指定修订的干净检出，**THE LOCALPILOT P0 BASELINE SHALL** 包含执行全部必需检查所需的测试、测试数据、配置说明和验收说明。

1.2 **THE LOCALPILOT P0 BASELINE SHALL** 明确区分受版本控制的验收资产与不得作为验收前提的本机运行时资产。

1.3 **WHILE** 某项测试、测试数据或文档被分类为 P0 必需验收资产，**THE LOCALPILOT P0 BASELINE SHALL** 使其变更能够被仓库变更检测识别。

1.4 **IF** 某项必需检查引用当前修订中不存在的验收资产，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定总体结果为失败并标识缺失资产。

1.5 **THE LOCALPILOT P0 BASELINE SHALL** 在不纳入个人凭证、模型密钥、Cookie、缓存、模型原文日志或任务运行输出的条件下保持验收资产完整。

### 2. 可重复的验证准备

**User Story：** 作为维护者或 AI 编码代理，我希望能够从干净检出重复准备受支持的验证环境，以便不同验收者获得等价的工程基线。

#### Acceptance Criteria

2.1 **WHEN** 验收者在受支持环境中从干净检出开始准备验证，**THE LOCALPILOT P0 BASELINE SHALL** 提供完成准备所需的全部仓库内声明信息。

2.2 **WHEN** 两个受支持环境从同一修订独立完成验证准备，**THE LOCALPILOT P0 BASELINE SHALL** 使二者获得等价的运行依赖集合和验证配置。

2.3 **THE LOCALPILOT P0 BASELINE SHALL** 明确声明 P0 验收所支持的运行环境约束。

2.4 **IF** 当前环境不满足已声明的支持约束，**THEN THE LOCALPILOT P0 BASELINE SHALL** 在执行必需测试前返回失败并指出不满足的约束。

2.5 **IF** 完成验证准备仍需要仓库未声明的人工安装步骤，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定验证准备失败。

2.6 **THE LOCALPILOT P0 BASELINE SHALL** 允许在没有任何真实模型 Provider 凭证的环境中完成 P0 验收准备。

### 3. 统一且确定的基线验收

**User Story：** 作为维护者，我希望人和自动化能够通过同一验收入口获得确定结论，以便在提交或重构前后快速判断基线状态。

#### Acceptance Criteria

3.1 **WHEN** 验收者从仓库根目录启动 P0 基线验收，**THE LOCALPILOT P0 BASELINE SHALL** 执行完整的必需检查集合。

3.2 **WHEN** P0 基线验收结束，**THE LOCALPILOT P0 BASELINE SHALL** 返回且仅返回成功、失败或未完成三类总体结论之一。

3.3 **THE LOCALPILOT P0 BASELINE SHALL** 仅在全部必需检查均已执行且通过时返回成功。

3.4 **IF** 任一必需检查失败、无法启动或被跳过，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回非成功结论。

3.5 **IF** 验收过程被中断或未产生全部必需检查结果，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回未完成而不是成功。

3.6 **WHEN** 同一修订在等价环境和等价输入下重复执行 P0 基线验收，**THE LOCALPILOT P0 BASELINE SHALL** 产生相同的必需检查集合和总体结论。

### 4. 默认离线验证

**User Story：** 作为验收者，我希望在没有真实 Provider 凭证和外部网络的环境中完成 P0 验收，以便结果不受费用、限流或网络波动影响。

#### Acceptance Criteria

4.1 **WHILE** 执行默认 P0 基线验收，**THE LOCALPILOT P0 BASELINE SHALL** 不发起任何外部网络请求。

4.2 **THE LOCALPILOT P0 BASELINE SHALL** 使用受控输入验证 P0 范围内需要覆盖的模型响应和传输结果类别。

4.3 **IF** 默认 P0 验收中的任一必需检查尝试访问外部网络，**THEN THE LOCALPILOT P0 BASELINE SHALL** 使该检查失败并标识网络访问来源。

4.4 **WHERE** 仓库提供真实 Provider 在线烟雾验证，**THE LOCALPILOT P0 BASELINE SHALL** 要求验收者显式选择该验证后才允许其运行。

4.5 **WHERE** 仓库提供真实 Provider 在线烟雾验证，**THE LOCALPILOT P0 BASELINE SHALL** 不允许在线结果替代默认离线必需检查。

4.6 **THE LOCALPILOT P0 BASELINE SHALL** 在没有个人 API Key、Cookie 或私有网关配置时完成默认 P0 验收。

### 5. 测试发现与当前修订对齐

**User Story：** 作为维护者，我希望必需测试只验证当前修订中的代码和受保护行为，以便历史引用或本机残留不会产生错误的验收结论。

#### Acceptance Criteria

5.1 **WHEN** P0 基线验收发现必需测试，**THE LOCALPILOT P0 BASELINE SHALL** 无错误地收集全部指定测试。

5.2 **IF** 必需测试引用当前修订中不存在的模块、符号或启动入口，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回失败并标识过时引用。

5.3 **WHEN** 必需测试加载 LocalPilot 代码，**THE LOCALPILOT P0 BASELINE SHALL** 确保被验证代码来自当前干净检出。

5.4 **IF** 某项必需测试的通过依赖相邻项目文件、未提交文件、预先存在的缓存或旧编译产物，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定该测试无效并返回失败。

5.5 **THE LOCALPILOT P0 BASELINE SHALL** 不包含与当前 P0 范围内受保护行为相冲突的必需测试期望。

5.6 **IF** 某项历史测试不再代表当前 P0 范围内的行为，**THEN THE LOCALPILOT P0 BASELINE SHALL** 要求该测试在总体成功前被明确重新分类，不得静默忽略。

### 6. 关键现有行为的特征验收

**User Story：** 作为后续重构的实施者，我希望获得关键现有行为的可重复特征证据，以便能够识别重构造成的非预期行为变化。

#### Acceptance Criteria

6.1 **WHEN** 验收者在无 Provider 凭证且无网络的环境中请求 CLI 帮助，**THE LOCALPILOT P0 BASELINE SHALL** 证明文档声明的主启动入口能够成功返回帮助信息。

6.2 **WHEN** 验收者从干净检出加载 P0 指定的核心代码，**THE LOCALPILOT P0 BASELINE SHALL** 证明代码能够完成语法检查和模块加载而不要求真实 Provider 调用。

6.3 **WHEN** LocalPilot 从仓库根目录以外的工作目录启动受保护入口，**THE LOCALPILOT P0 BASELINE SHALL** 证明项目自有资产和运行时目录仍指向当前项目。

6.4 **WHEN** 上下文历史达到裁剪条件，**THE LOCALPILOT P0 BASELINE SHALL** 证明消息顺序、首条可发送消息和结构化工具调用与结果的配对保持有效。

6.5 **WHEN** 受控模型响应分别包含纯文本、结构化工具调用、推理内容或错误结果，**THE LOCALPILOT P0 BASELINE SHALL** 证明 LocalPilot 能够将其区分为对应的当前行为结果。

6.6 **WHEN** 受控模型响应包含多个结构化工具调用，**THE LOCALPILOT P0 BASELINE SHALL** 证明每个工具调用与其名称、参数和调用标识保持关联。

6.7 **WHEN** 工具分发接收到有效、参数错误或未知的工具请求，**THE LOCALPILOT P0 BASELINE SHALL** 证明每种请求均产生可判定结果，且单个可恢复工具错误不被误报为总体成功。

6.8 **WHEN** 模型请求遇到可重试错误、不可重试错误或流式响应中断，**THE LOCALPILOT P0 BASELINE SHALL** 证明三类结果能够被区分并产生可诊断状态。

6.9 **WHERE** 某项行为已被后续已批准 Spec 标记为迁移期兼容行为，**THE LOCALPILOT P0 BASELINE SHALL** 将其标识为过渡性证据而不是长期产品验收义务。

### 7. P0 兼容性保护

**User Story：** 作为 LocalPilot 用户，我希望 P0 工程基线建设不改变现有入口和工作流，以便工程治理不会引入未经批准的产品变化。

#### Acceptance Criteria

7.1 **WHILE** P0 处于实施和验收阶段，**THE LOCALPILOT P0 BASELINE SHALL** 保持当前已文档化的交互式 CLI、一次性 task 和 reflect 启动能力。

7.2 **WHILE** P0 处于实施和验收阶段，**THE LOCALPILOT P0 BASELINE SHALL** 保持当前模型配置的用户可见含义和选择行为。

7.3 **WHILE** P0 处于实施和验收阶段，**THE LOCALPILOT P0 BASELINE SHALL** 保持当前模型会话、工具调用、上下文记忆、任务文件和定时触发的用户可见语义。

7.4 **IF** 为使 P0 通过而必须改变上述用户可见语义，**THEN THE LOCALPILOT P0 BASELINE SHALL** 将该变更判定为超出 P0 范围并要求独立 Spec 获得批准。

7.5 **IF** 文档描述与当前可运行入口不一致，**THEN THE LOCALPILOT P0 BASELINE SHALL** 允许修正文档，但不得仅为保留错误文档而新增重复产品入口。

7.6 **THE LOCALPILOT P0 BASELINE SHALL** 不把新的产品能力作为 P0 成功的必要条件。

### 8. 失败诊断与验收证据

**User Story：** 作为验收者或 AI 编码代理，我希望失败结果包含可定位、可追踪且不泄露敏感信息的证据，以便无需猜测日志即可判断下一步行动。

#### Acceptance Criteria

8.1 **IF** 任一必需检查失败，**THEN THE LOCALPILOT P0 BASELINE SHALL** 报告检查标识、失败类型、受影响目标和非空诊断信息。

8.2 **IF** 多个必需检查失败，**THEN THE LOCALPILOT P0 BASELINE SHALL** 保留每个已执行检查的独立结果，不得仅报告最后一个失败。

8.3 **WHEN** P0 基线验收结束，**THE LOCALPILOT P0 BASELINE SHALL** 产生包含仓库修订、受支持环境标识、已执行检查、各检查结果和总体结论的验收证据。

8.4 **THE LOCALPILOT P0 BASELINE SHALL** 使每项 P0 Requirement 至少映射到一个验收检查或人工可复核证据。

8.5 **THE LOCALPILOT P0 BASELINE SHALL** 使 AI 编码代理能够仅根据验收输出判断成功、失败或未完成，而不需要猜测自然语言日志含义。

8.6 **IF** 诊断信息包含名称疑似为密钥、Token、Cookie、Authorization、Password 或 Secret 的值，**THEN THE LOCALPILOT P0 BASELINE SHALL** 不在验收证据中暴露其原始内容。

### 9. 文档一致性

**User Story：** 作为首次接触仓库的维护者，我希望文档准确描述当前可执行的启动与验收路径，以便能够从干净检出复现 P0 验证。

#### Acceptance Criteria

9.1 **THE LOCALPILOT P0 BASELINE SHALL** 提供唯一、明确的主启动入口说明。

9.2 **THE LOCALPILOT P0 BASELINE SHALL** 提供从干净检出准备环境和启动 P0 验收的说明。

9.3 **THE LOCALPILOT P0 BASELINE SHALL** 明确默认验证为离线验证，并说明在线烟雾验证不属于 P0 必需门。

9.4 **IF** 文档声明的必需命令无法在干净检出和受支持环境中启动，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定文档一致性检查失败。

9.5 **IF** 文档声称测试或基线处于成功状态，但对应必需检查未通过，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定文档一致性检查失败。

9.6 **THE LOCALPILOT P0 BASELINE SHALL** 在文档中区分当前已验证能力、迁移期能力和后续阶段计划。

### 10. P0 完成判定

**User Story：** 作为 P0 批准者，我希望完成结论建立在干净、离线、完整且可追踪的证据上，以便只接受能够作为后续重构可信起点的修订。

#### Acceptance Criteria

10.1 **WHEN** P0 在干净检出和受支持环境中接受验收，**THE LOCALPILOT P0 BASELINE SHALL** 完成全部必需检查且总体结论为成功。

10.2 **WHEN** P0 被判定完成，**THE LOCALPILOT P0 BASELINE SHALL** 为第 1 至第 9 项 Requirement 提供完整的验收证据映射。

10.3 **IF** P0 只能依赖未提交文件、被忽略的必需资产、本机缓存、个人凭证或外部网络才能通过，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定 P0 未完成。

10.4 **IF** 任一必需检查被跳过、预期失败或未执行，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定 P0 未完成。

10.5 **IF** P0 交付包含 Out of scope 中的产品或架构变更且没有独立批准，**THEN THE LOCALPILOT P0 BASELINE SHALL** 判定 P0 未完成。

10.6 **WHEN** P0 被判定完成，**THE LOCALPILOT P0 BASELINE SHALL** 允许后续重构以该修订和验收证据作为可比较起点。

## 8. Requirement 追踪矩阵

| Requirement | User Story 主题 | 验收证据主题 |
| --- | --- | --- |
| 1 | 仅从仓库修订取得验收资产 | 干净检出资产清单、仓库状态检查 |
| 2 | 可重复准备验证环境 | 独立环境准备结果、环境约束检查 |
| 3 | 统一入口和确定结论 | 必需检查清单、退出状态、总体结论 |
| 4 | 无凭证、无网络验收 | 网络隔离证据、受控输入结果 |
| 5 | 测试与当前修订一致 | 收集结果、代码来源、缓存隔离结果 |
| 6 | 关键行为可比较 | CLI、加载、路径、上下文、模型响应、工具与错误特征证据 |
| 7 | 用户工作流不被 P0 改写 | P0 前后用户可见行为对照 |
| 8 | 失败可诊断且可追踪 | 失败样例、验收记录、敏感信息检查 |
| 9 | 文档可复现真实路径 | 文档命令执行结果、能力状态对照 |
| 10 | 完成结论可信 | 汇总验收报告、证据映射、范围审计 |

## 9. Requirements Review Gate

### 9.1 覆盖性

- [x] 目标、角色、术语和成功条件明确。
- [x] In scope、Out of scope 和相邻阶段约束明确。
- [x] 每项 Requirement 均包含角色、目标和价值明确的 User Story。
- [x] 正常路径、失败路径、离线路径和干净检出路径均有 Requirement。
- [x] 用户可见兼容性与 AI 验收证据均有 Requirement。

### 9.2 EARS 合规性

- [x] 每条 Acceptance Criterion 包含明确的 `SHALL` 主体。
- [x] 事件、状态、可选能力和异常条件使用对应 EARS 标记。
- [x] 每条 Acceptance Criterion 可独立判定通过或失败。
- [x] Requirement 标题和 Acceptance Criteria 使用数字编号。

### 9.3 WHAT / HOW 边界

- [x] 未规定依赖管理器、构建工具、测试框架或 CI 提供方。
- [x] 未规定包目录、类、函数、数据结构或内部模块拆分。
- [x] 未规定 Provider Adapter、HTTP 客户端或异步实现方式。
- [x] 技术选择和内部架构留待 Design 阶段。

### 9.4 歧义检查

- [x] 成功、失败和未完成具有互斥含义。
- [x] “必需检查”“默认离线验证”“干净检出”等关键词已有定义。
- [x] 不使用“尽量”“适当”“基本通过”等无法验收的措辞。
- [x] P0 不固化后续计划删除的文本工具协议。

**Review Gate 结论：PASS。**

## 10. 批准门

本文件当前为 `Requirements Generated / 待用户确认`。

在用户明确批准前：

- 不进入 P0 Design。
- 不把本文档转换为实现任务。
- 不根据本文档修改生产代码。

批准后，下一阶段只回答“如何满足这些 Requirement”，并保持本文件的范围边界和 Requirement 编号稳定。
