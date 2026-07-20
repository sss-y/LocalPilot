# LocalPilot P0 个人项目版需求

## 文档信息

| 字段 | 内容 |
| --- | --- |
| 项目 | LocalPilot |
| 阶段 | P0 — 可验证工程基线 |
| 文档类型 | Requirements Spec |
| 状态 | Replanned / 待用户确认 |
| 重写日期 | 2026-07-20 |
| 原需求批准日期 | 2026-07-15 |
| 实施计划 | [p0-verifiable-engineering-baseline-implementation-plan.md](./p0-verifiable-engineering-baseline-implementation-plan.md) |

## 1. 目标

P0 只为个人开发提供一个可信的项目体检命令：

```bash
python -m p0_baseline
```

开发者修改代码后运行该命令，应当能够快速知道：

1. 当前环境、依赖和仓库状态是否适合继续验证；
2. 已登记的必需检查是否真正执行完毕；
3. 结果是通过、失败，还是没有检查完整；
4. 检查是否保持离线且没有泄露个人凭证；
5. LocalPilot 的主帮助入口是否仍能启动。

P0 是开发体检工具，不是企业认证平台，也不证明 LocalPilot 的全部业务逻辑都正确。

## 2. 必须保留的业务边界

P0 的实现不得为了通过体检而改变以下现有业务：

- Agent 启动与运行流程；
- Session、Client 和模型调用流程；
- 上下文管理；
- 工具注册和工具调用；
- 配置、路径和 Provider 选择方式；
- `runagent.py` 等现有产品入口。

P0 允许增加独立检查代码、测试、说明文档，以及修复明确且很小的兼容性缺陷。涉及 Session/Client、Agent Loop 或产品语义的修改必须另立计划。

## 3. 范围

### 3.1 本轮包含

- 一个统一的本地体检入口；
- 已支持环境、依赖指纹和仓库状态检查；
- 当前检出资产与代码来源检查；
- 受控 Python Worker 和结构化检查结果；
- 默认离线和凭证环境净化；
- `success / failure / incomplete` 三态与 `0 / 1 / 2` 退出码；
- 脱敏后的 human、JSON 和可选文件输出；
- `runagent.py --help` 的最小业务烟雾检查；
- 简短、可复制执行的使用说明。

### 3.2 本轮不包含

- 62 条 Requirement 的完整认证；
- 上下文、模型响应、transport、重试和工具分发的全量行为矩阵；
- 恶意 Python 代码、动态 Loader、直接文件读取或 native 扩展的强沙箱；
- 自动 candidate commit、clean clone 或独立验收环境；
- 在线 Provider smoke；
- Session/Client/Agent Loop 重构；
- 新 Provider、新工具、新存储或新用户功能。

## 4. 术语

| 术语 | 定义 |
| --- | --- |
| 必需检查 | 已在 Manifest 中登记、会影响总体结论的检查 |
| success | 所有必需检查都执行并通过，且没有阻止成功的资格问题 |
| failure | 至少存在一个已经确定的检查或准备失败 |
| incomplete | 检查没有完整执行，或当前状态不具备成功资格 |
| 默认离线 | 未经额外选择时不允许任何外部网络请求 |
| 当前检出 | 当前仓库工作区及其对应的 Git revision |
| 历史映射 | 旧版 56/62 条 Requirement 覆盖字段，仅为兼容现有 Manifest 和模型保留 |

## 5. Requirements

### 1. 统一体检入口

**User Story：** 作为个人开发者，我希望只记住一个命令，就能检查项目当前是否适合继续开发。

#### Acceptance Criteria

1.1 **WHEN** 开发者运行 P0 帮助命令，**THE LOCALPILOT P0 BASELINE SHALL** 返回可读帮助，且不加载真实 Provider 凭证。

1.2 **WHEN** 开发者从仓库根目录运行 P0，**THE LOCALPILOT P0 BASELINE SHALL** 执行 Manifest、Preflight 和活动 Manifest 中全部 `required=true` 的检查；延后能力和旧描述符不得作为占位必需检查执行。

1.3 **WHEN** 开发者选择 human 或 JSON 输出，**THE LOCALPILOT P0 BASELINE SHALL** 用所选格式返回同一个总体结论。

1.4 **WHERE** 开发者指定输出文件，**THE LOCALPILOT P0 BASELINE SHALL** 写出经过校验和脱敏的 JSON 结果。

### 2. 环境、依赖和当前检出

**User Story：** 作为个人开发者，我希望体检先确认自己正在验证正确的代码和环境，避免本机残留制造假通过。

#### Acceptance Criteria

2.1 **THE LOCALPILOT P0 BASELINE SHALL** 明确声明当前支持的操作系统、架构和 Python 版本。

2.2 **WHEN** P0 开始执行，**THE LOCALPILOT P0 BASELINE SHALL** 记录当前完整 revision、工作树状态和依赖指纹。

2.3 **WHEN** P0 使用必需资产或加载 LocalPilot 代码，**THE LOCALPILOT P0 BASELINE SHALL** 验证其来自当前仓库检出和受版本控制的文件。

2.4 **IF** 运行环境不受支持、依赖指纹不匹配或必需资产缺失，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回 failure 并指出具体原因。

2.5 **IF** 工作树存在未提交修改，**THEN THE LOCALPILOT P0 BASELINE SHALL** 允许检查继续执行，但总体结果不得为 success。

### 3. 默认离线与敏感信息保护

**User Story：** 作为个人开发者，我希望体检不会产生模型费用，也不会把自己的凭证写进报告。

#### Acceptance Criteria

3.1 **WHILE** 执行默认 P0，**THE LOCALPILOT P0 BASELINE SHALL** 在父进程执行任何 Adapter 前以及 Worker 导入测试前安装 Offline Guard，不发起外部网络请求。

3.2 **IF** 必需检查尝试访问外部网络，**THEN THE LOCALPILOT P0 BASELINE SHALL** 阻止该访问并将对应检查判定为 failure。

3.3 **WHEN** P0 启动受控 Worker，**THE LOCALPILOT P0 BASELINE SHALL** 从 Worker 环境移除 Provider 凭证、Cookie、代理和个人网关配置。

3.4 **IF** 诊断或输出中出现疑似 API Key、Token、Cookie、Authorization、Password 或 Secret 的内容，**THEN THE LOCALPILOT P0 BASELINE SHALL** 隐藏原始值。

### 4. 可靠执行与三态结论

**User Story：** 作为个人开发者，我希望“通过”只表示检查真的全部完成，而不是被跳过或中途失败。

#### Acceptance Criteria

4.1 **WHEN** P0 执行必需检查，**THE LOCALPILOT P0 BASELINE SHALL** 为每个检查保留独立的结构化结果。

4.2 **WHEN** 全部必需检查都执行并通过，且成功资格门全部满足，**THE LOCALPILOT P0 BASELINE SHALL** 返回 success 和退出码 `0`。

4.3 **IF** 任一检查产生明确失败或错误，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回 failure 和退出码 `1`，并保留其他已执行结果。

4.4 **IF** 必需检查被跳过、超时、中断、未运行或没有产生结果，**THEN THE LOCALPILOT P0 BASELINE SHALL** 返回 incomplete 和退出码 `2`。

4.5 **IF** 明确 failure 与 incomplete 条件同时出现，**THEN THE LOCALPILOT P0 BASELINE SHALL** 保留所有细节，并以 failure 作为总体结论。

4.6 **THE LOCALPILOT P0 BASELINE SHALL** 不把测试框架日志文字或最后一个检查结果直接当作总体结论。

4.7 **IF** 指定的结果文件无法安全写出，**THEN THE LOCALPILOT P0 BASELINE SHALL** 不得报告 success。

### 5. 最小业务烟雾检查与兼容性

**User Story：** 作为 LocalPilot 使用者，我希望增加体检工具不会破坏原来的启动和工作方式。

#### Acceptance Criteria

5.1 **WHEN** 在无 Provider 凭证且无外网的环境中运行 `runagent.py --help`，**THE LOCALPILOT P0 BASELINE SHALL** 证明帮助入口能够成功返回；该烟雾测试无论由 unittest discovery 直接执行还是由 Worker 执行，都必须自行建立环境净化、离线保护和凭证加载禁用边界。

5.2 **WHEN** 执行该烟雾检查，**THE LOCALPILOT P0 BASELINE SHALL** 证明入口加载的代码来自当前仓库检出。

5.3 **WHILE** 实施 P0，**THE LOCALPILOT P0 BASELINE SHALL** 保持现有 Agent、Session、Client、上下文、工具和 Provider 选择的用户可见语义。

5.4 **IF** 通过 P0 必须改变现有产品语义或进行结构重构，**THEN THE LOCALPILOT P0 BASELINE SHALL** 将该修改判定为超出范围并要求独立计划。

### 6. 输出与文档

**User Story：** 作为未来的自己，我希望不阅读实现代码也能知道如何运行体检和理解结果。

#### Acceptance Criteria

6.1 **WHEN** P0 结束，**THE LOCALPILOT P0 BASELINE SHALL** 输出总体状态、退出码、检查统计和必要诊断。

6.2 **THE LOCALPILOT P0 BASELINE SHALL** 提供运行命令、支持环境、三态含义、默认离线和已知限制的使用说明。

6.3 **IF** 某项能力没有纳入本轮检查，**THEN THE LOCALPILOT P0 BASELINE SHALL** 将其标记为未验证，不得声明已经通过。

6.4 **WHEN** P0 被判定完成，**THE LOCALPILOT P0 BASELINE SHALL** 使全部 P0 测试、代码编译检查、帮助命令和外层 dirty 语义验证程序以退出码 `0` 通过；外层程序内部可以断言真实 P0 在 dirty 工作树返回 incomplete / `2`。

### 7. 现有实现兼容

**User Story：** 作为项目维护者，我希望需求收缩不会迫使已经完成且有价值的 P0 实现被删除。

#### Acceptance Criteria

7.1 **THE LOCALPILOT P0 BASELINE SHALL** 继续保留已实现的 Manifest、Schema、模型、脱敏、Preflight、Worker、Adapter、Offline Guard 和 Safe Subprocess 能力。

7.2 **WHERE** 现有 Manifest 和报告模型仍包含旧版 56/62 条历史映射，**THE LOCALPILOT P0 BASELINE SHALL** 允许其作为兼容元数据暂时存在。

7.3 **WHEN** 计算个人项目版 P0 总体结论，**THE LOCALPILOT P0 BASELINE SHALL** 以当前必需检查和三态资格规则为准，不以凑齐旧版 56/62 条认证作为完成条件；Manifest 完整性只返回实际存在且引用有效的旧映射。

7.4 **THE LOCALPILOT P0 BASELINE SHALL** 不得仅因某项旧版需求移出当前范围而删除仍被现有检查使用的代码或测试。

## 6. 验收摘要

| 需求 | 保留的实际价值 | 主要验收方式 |
| --- | --- | --- |
| 1 | 一个命令完成体检 | CLI 单元和集成测试 |
| 2 | 不验证错环境、错依赖、错代码 | Preflight 与 Manifest 测试 |
| 3 | 不访问外网、不泄露凭证 | Offline Guard、环境净化和脱敏测试 |
| 4 | 没跑完不能冒充通过 | Aggregator 和 Worker 场景测试 |
| 5 | 原有 LocalPilot 启动业务不被破坏 | `runagent.py --help` 烟雾检查 |
| 6 | 未来能看懂、能复现 | 文档命令和完整 P0 测试 |
| 7 | 已完成投入不浪费 | 现有模块继续参与体检链路 |

## 7. 完成条件

P0 只有在以下条件全部满足时才可以标记完成：

- Requirements 1–7 的当前必需检查均已实现并通过；
- `python -m p0_baseline --help` 正常；
- `python -m p0_baseline` 能产生可信三态结论；
- 默认执行不需要真实 Provider 凭证或外部网络；
- `runagent.py --help` 最小烟雾检查通过；
- 全部 P0 测试和 compile check 通过；
- 文档没有把未验证能力写成已通过。

当前工作树 dirty 时，允许功能检查通过但总体为 incomplete；不要求为了得到 success 而清理、覆盖或提交用户文件。

## 8. 批准门

本文件替代 2026-07-15 批准的 62 条重型 Requirements。旧版 Requirement 编号只作为现有实现兼容信息保留，不再代表当前 P0 必须完成的认证清单。

用户确认本文件后，Design 和实现应以本版范围为准；确认前不因本次需求重写修改生产实现或删除现有测试。
