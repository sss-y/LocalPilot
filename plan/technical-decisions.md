# LocalPilot 技术决策记录

## 文档信息

| 字段 | 内容 |
| --- | --- |
| 项目 | LocalPilot |
| 当前决策集 | P0 — 可验证工程基线 |
| 文档类型 | Technical Decision Log / ADR |
| 状态 | Active / 生效中 |
| 初始决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| Requirements | [p0-verifiable-engineering-baseline-requirements.md](./p0-verifiable-engineering-baseline-requirements.md) |
| Interface Contract | [p0-verifiable-engineering-baseline-interface-contracts.md](./p0-verifiable-engineering-baseline-interface-contracts.md) |
| Technical Design | [p0-verifiable-engineering-baseline-design.md](./p0-verifiable-engineering-baseline-design.md) |
| Implementation Plan | [p0-verifiable-engineering-baseline-implementation-plan.md](./p0-verifiable-engineering-baseline-implementation-plan.md) |

## 1. 记录规则

- 每项决策使用稳定 ADR ID，不因文件重排而改变；P0 使用 `ADR-P0-NNN`，后续项目级决策使用 `ADR-LP-NNN`。
- 已批准记录不直接改写结论；需要改变时新增 ADR，并通过 `取代` / `被取代` 字段建立关系。
- 每项记录必须包含：当时约束、决策日期、决策人、选择理由、备选方案及其简短淘汰原因。
- AI 代理不得把未获得用户明确确认的建议写成“User 已批准”；未确认决策使用 `Proposed`。
- 代码或文档变更命中根目录 `agent.md` 的技术决策触发条件时，必须在同一变更中新增或更新本文件。

## 2. 决策索引

| ID | 决策 | 状态 |
| --- | --- | --- |
| ADR-P0-001 | P0 验收控制面与产品 CLI 分离 | Approved |
| ADR-P0-002 | 统一命令绑定为 `python -m p0_baseline` | Approved |
| ADR-P0-003 | 首版支持 Darwin arm64 / CPython 3.12.x | Approved |
| ADR-P0-004 | 使用哈希锁定依赖和标准库 unittest | Approved |
| ADR-P0-005 | Manifest 使用 JSON、Schema 和注册 Adapter | Approved |
| ADR-P0-006 | 总体采用三态与固定退出码 | Approved |
| ADR-P0-007 | 权威证据使用版本化 JSON 和原子持久化 | Superseded |
| ADR-P0-008 | 离线边界覆盖父进程和受控 Python Worker | Approved |
| ADR-P0-009 | 只把 `tests/p0/**` 作为 P0 测试资产 | Approved |
| ADR-P0-010 | 历史测试迁移、重写或显式排除 | Approved |
| ADR-P0-011 | Requirement 覆盖采用 56 条 Manifest + 6 条 Runner 合成 | Superseded |
| ADR-P0-012 | P0 首版不实现在线 smoke | Approved |
| ADR-P0-013 | 正式成功只针对不可变 candidate commit 的干净检出 | Superseded |
| ADR-P0-014 | 证据先脱敏后持久化，失败时丢弃详情 | Approved |
| ADR-P0-015 | P0 仅允许最小兼容修复，不进行产品架构重构 | Approved |
| ADR-P0-016 | 活动 Manifest 只登记当前叶子检查，旧映射按实际存在项兼容 | Approved |
| ADR-P0-017 | 首版只提供脱敏 JSON 输出，不建设权威证据发布服务 | Approved |
| ADR-P0-018 | 个人项目版 success 使用当前干净检出，不自动化 clean-clone 验收 | Approved |

## ADR-P0-001：P0 验收控制面与产品 CLI 分离

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | `runagent.py` 承担交互、task、reflect 和后台产品语义；产品任务错误没有 P0 所需三态退出码；P0 不得改变现有工作流。 |
| 决策 | 新建独立 P0 验收控制面，不复用产品 Agent 任务生命周期来决定基线结论。 |
| 选择理由 | 隔离工程验收和产品运行语义，使退出码、离线边界和证据完整性可以独立演进。 |
| 备选方案及淘汰原因 | 扩展 `runagent.py --verify-p0`：耦合产品 CLI 与工程门；复用 Agent JSONL：日志写入失败不影响产品运行，不能作为权威证据。 |

## ADR-P0-002：统一命令绑定为 `python -m p0_baseline`

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 仓库尚未配置可安装的 console script；命令必须从仓库根目录直接执行，并明确使用当前 Python 环境。 |
| 决策 | 逻辑命令 `p0-verify` 的唯一具体绑定为 `python -m p0_baseline`。 |
| 选择理由 | 无需安装额外入口，包内模块可复用，且不会改变 `runagent.py`。 |
| 备选方案及淘汰原因 | 根脚本 `verify_p0.py`：模块复用与导入边界较弱；console script：要求先引入打包配置；直接 unittest 命令：不能统一预检、聚合和证据。 |

## ADR-P0-003：首版支持 Darwin arm64 / CPython 3.12.x

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 当前可验证环境为 Darwin arm64 / CPython 3.12.13；README 的 Python 3.11+ 尚无完整环境矩阵证据。 |
| 决策 | P0 首版只声明 Darwin arm64 / CPython 3.12.x；其他组合需独立 clean-checkout 验证后加入。 |
| 选择理由 | 支持声明与真实证据一致，避免把未验证平台误报为受支持。 |
| 备选方案及淘汰原因 | 继续声明 Python 3.11+：范围过宽且无矩阵；同时支持 Linux/Windows：当前缺少干净环境证据。 |

## ADR-P0-004：使用哈希锁定依赖和标准库 unittest

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | `requirements.txt` 只有宽松下限；当前环境没有 pytest；P0 不负责决定新的依赖管理器。 |
| 决策 | 保留产品 `requirements.txt`，新增带精确版本和哈希的 `requirements-p0.lock`；P0 测试使用标准库 `unittest`。 |
| 选择理由 | 以最小工具变化获得可复现环境，并避免为工程基线增加测试框架依赖。 |
| 备选方案及淘汰原因 | 直接使用宽松 requirements：不能保证等价集合；引入 pytest：增加非必要依赖；切换 Poetry/uv：超出 P0 工具治理范围。 |

## ADR-P0-005：Manifest 使用 JSON、Schema 和注册 Adapter

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | Manifest 必须机器可判定、受版本控制、可计算摘要，并且检查不能通过任意 shell 绕过 Offline Boundary。 |
| 决策 | 使用 `p0_baseline/manifest.json` 和 JSON Schema；检查只引用注册的 `unittest` / `internal` Adapter 与精确 test ID。 |
| 选择理由 | JSON 无新增运行依赖，Schema 可验证字段，注册 Adapter 将执行面限制在受控边界。 |
| 备选方案及淘汰原因 | YAML：引入解析依赖；Python 配置：数据与执行混合；任意 shell command：难以保证离线、脱敏和跨环境确定性。 |

## ADR-P0-006：总体采用三态与固定退出码

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 失败和未执行完整检查具有不同语义；自动化必须无需解析自然语言即可判定。 |
| 决策 | 总体状态为 `success/failure/incomplete`，退出码固定为 `0/1/2`；failure 优先于 incomplete。 |
| 选择理由 | 明确区分确定失败和证据不完整，防止中断或 skip 被误报为成功。 |
| 备选方案及淘汰原因 | 仅 pass/fail：丢失未完成语义；沿用 unittest 退出码：不能表达 dirty、证据写入失败和跨检查聚合。 |

## ADR-P0-007：权威证据使用版本化 JSON 和原子持久化

| 字段 | 内容 |
| --- | --- |
| 状态 | Superseded |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 人和 AI 都要读取证据；报告写入失败不能被当作成功；运行日志不是权威证据。 |
| 决策 | 生成版本化 `BaselineReport` JSON，默认写入 `temp/p0-baseline/<run_id>/report.json`，通过临时文件、fsync、原子替换和回读发布。 |
| 选择理由 | 数据可校验、可追踪，原子发布避免截断文件被误认成完整结论。 |
| 备选方案及淘汰原因 | 只输出 stdout：不利于复核；复用 Agent JSONL：非权威且写入失败被吞；把报告提交 Git：混淆运行时证据和验收资产。 |
| 被取代 | ADR-P0-017 |

## ADR-P0-008：离线边界覆盖父进程和受控 Python Worker

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 默认验收不得访问外网；仅 mock requests 不覆盖 DNS、socket 或子进程；首版依赖的网络路径使用 Python socket。 |
| 决策 | 父进程和 Check Worker 在导入测试前安装 socket/DNS Guard；子进程只允许当前 Python 解释器和净化环境；任意非 Python 子进程不得作为必需检查。 |
| 选择理由 | 在现有技术栈内覆盖真实请求路径，并把无法证明的 native 子进程排除在支持边界外。 |
| 备选方案及淘汰原因 | 只 patch requests：覆盖不足；真实断网人工操作：不可自动复现；跨平台 OS sandbox：首版环境与维护成本不确定。 |

## ADR-P0-009：只把 `tests/p0/**` 作为 P0 测试资产

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | `tests/` 当前整体被忽略，HEAD 中没有测试；本机历史测试大量过时；P0 必需资产必须在干净检出中存在。 |
| 决策 | 只解除 `tests/p0/**` 的忽略并将其作为 P0 受控测试；恢复忽略 `temp/`。 |
| 选择理由 | 创建小而可信的单一事实来源，同时避免把运行缓存和历史失效测试纳入基线。 |
| 备选方案及淘汰原因 | 跟踪整个本机 tests：收集错误严重；继续忽略测试：干净检出无法验收；跟踪 temp：泄露并依赖本机状态。 |

## ADR-P0-010：历史测试迁移、重写或显式排除

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 历史测试引用不存在的 `agentmain.py`、`core.llmcore`、`core.llm_client`、`evals` 等；P0 不得为保留错误测试重建重复入口。 |
| 决策 | 在 `plan/p0-test-asset-classification.md` 对每个历史测试执行迁移、重写或 P0 排除，并只把当前受保护行为迁入 `tests/p0`。 |
| 选择理由 | 保留有价值的行为证据，同时明确处理过时测试而非静默跳过。 |
| 备选方案及淘汰原因 | 全量修复历史套件：超出 P0 且会固化旧实现；直接删除不记录：失去审计链；恢复已删除模块：引入重复产品入口。 |

## ADR-P0-011：Requirement 覆盖采用 56 条 Manifest + 6 条 Runner 合成

| 字段 | 内容 |
| --- | --- |
| 状态 | Superseded |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 第 1–9 项共 56 条可由检查直接证明；`10.1`–`10.6` 是聚合后的完成门，若放入普通检查会产生循环依赖。 |
| 决策 | Manifest 映射第 1–9 项 56 条；Runner 在聚合后合成第 10 项 6 条；最终报告覆盖全部 62 条。 |
| 选择理由 | 避免“先证明总体成功才能计算总体成功”的循环，同时保持完整追踪。 |
| 备选方案及淘汰原因 | Manifest 直接注册 62 条检查：完成门循环；只报告 56 条：无法证明 P0 完成条件。 |
| 被取代 | ADR-P0-016 |

## ADR-P0-012：P0 首版不实现在线 smoke

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | P0 必须默认离线且无需凭证；Provider 状态、费用、限流和网络波动会导致不确定结果。 |
| 决策 | P0 首版不提供在线 smoke 参数或真实 Provider 必需检查，只保留未来可选扩展契约。 |
| 选择理由 | 收窄首版范围并确保每次验收可重复、无费用、无凭证。 |
| 备选方案及淘汰原因 | 把在线 smoke 作为必需门：结果不确定；实现可选在线路径：增加当前 P0 不需要的分支和凭证边界。 |

## ADR-P0-013：正式成功只针对不可变 candidate commit 的干净检出

| 字段 | 内容 |
| --- | --- |
| 状态 | Superseded |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 开发工作树天然 dirty；P0 success 必须能由独立验收者复现；AI 未获得用户授权不能自行提交。 |
| 决策 | 组件测试可在 dirty tree 运行但总体至多 incomplete；正式 success 仅在用户提供或授权的不可变 candidate commit 的独立 clean clone 中产生。 |
| 选择理由 | 把开发反馈与正式验收分开，确保成功证据对应可复现修订。 |
| 备选方案及淘汰原因 | dirty tree 也 success：无法复现；自动创建 commit：超出授权；复制当前目录验收：会携带未跟踪文件和缓存。 |
| 被取代 | ADR-P0-018 |

## ADR-P0-014：证据先脱敏后持久化，失败时丢弃详情

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | 当前运行可能包含 API Key、Cookie、Authorization、个人路径、prompt 和原始 traceback；权威报告必须安全复核。 |
| 决策 | 报告对象必须先递归脱敏和限长，再执行 Schema 校验与写入；脱敏失败时省略或替换详情，绝不回退原值。 |
| 选择理由 | 让敏感数据在进入持久化边界前即被移除，避免错误路径泄露。 |
| 备选方案及淘汰原因 | 写入后再清洗：原值已落盘；保存 secret 哈希：仍可能用于关联；保留完整 traceback：包含上下文泄露风险。 |

## ADR-P0-015：P0 仅允许最小兼容修复，不进行产品架构重构

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-15 |
| 决策人 | User（最终批准）；Codex（方案起草） |
| 当时约束 | Session/Client、文本工具协议、Agent Loop、Memory、Scheduler 和 Observability 重构已明确 Out of scope；当前生产文件还有用户未提交修改。 |
| 决策 | P0 默认新增独立控制面和测试资产；只有特征测试证明当前受保护语义失败时，才允许在明确文件边界内做最小兼容修复。 |
| 选择理由 | 防止工程基线项目演变成产品重写，并保护用户工作树。 |
| 备选方案及淘汰原因 | 借 P0 完成协议重构：范围和风险不可控；完全禁止生产修复：无法处理真实 P0 基线缺陷；覆盖当前 dirty 文件：破坏用户资产。 |

## ADR-P0-016：活动 Manifest 只登记当前叶子检查，旧映射按实际存在项兼容

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-20 |
| 决策人 | User（授权按重规划任务执行）；Codex（方案起草） |
| 当时约束 | 个人项目版 P0 已明确延后全量行为、重复确定性、权威证据和文档一致性认证；旧 Manifest 仍强制 56 条覆盖并包含没有 callable 的必需 InternalAdapter；把 Runner 集成测试登记进当前 Runner 会产生递归。 |
| 决策 | `checks` 只保留当前真实可执行的叶子检查；延后描述符不进入活动执行集合。ManifestIntegrity 继续解析旧 Requirement ID，但只返回实际存在且引用有效的映射，不要求旧 56/62 条完整覆盖。当前结果完整性由活动必需检查全部登记并产生结构化结果证明。 |
| 选择理由 | 使 Manifest 的声明与本轮真实能力一致，消除占位必需检查、旧覆盖硬门和 Runner 自测递归，同时保留历史数据兼容性。 |
| 备选方案及淘汰原因 | 将延后检查改为 `required=false` 但仍执行：仍会运行未实现能力；保留旧 56 条硬门：个人项目版永远无法 success；登记 Runner 集成测试：形成执行递归；删除所有旧字段：产生不必要的破坏性兼容变更。 |
| 关联文件/Requirement | `p0_baseline/manifest.py`, `p0_baseline/manifest.json`, Requirements 1.2、4.1–4.5、7.2–7.4，IC-02、IC-05、IC-09 |
| 取代/被取代 | 取代 ADR-P0-011 |

## ADR-P0-017：首版只提供脱敏 JSON 输出，不建设权威证据发布服务

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-20 |
| 决策人 | User（授权按重规划任务执行）；Codex（方案起草） |
| 当时约束 | 个人项目版 P0 只需要 stdout 和可选 `--output` 文件；独立 Evidence Sink、证据目录、fsync、发布回读和历史管理均已延后。 |
| 决策 | 首版使用经过模型、Schema 和脱敏校验的版本化 JSON；`--output` 写入失败不得 success，但本轮不把该文件称为权威证据发布，也不实现独立证据服务和原子发布协议。 |
| 选择理由 | 保留机器可读、安全输出和失败语义，同时避免为个人开发闭环建设未被当前需求使用的证据基础设施。 |
| 备选方案及淘汰原因 | 继续实现完整 Evidence Sink：超出当前范围；只输出 human：自动化不可判定；复用产品日志：不是稳定验收对象且可能含敏感信息。 |
| 关联文件/Requirement | `p0_baseline/cli.py`, `p0_baseline/models.py`, Requirements 1.3–1.4、4.7、6.1，IC-01、IC-06、IC-07 |
| 取代/被取代 | 取代 ADR-P0-007 |

## ADR-P0-018：个人项目版 success 使用当前干净检出，不自动化 clean-clone 验收

| 字段 | 内容 |
| --- | --- |
| 状态 | Approved |
| 决策日期 | 2026-07-20 |
| 决策人 | User（授权按重规划任务执行）；Codex（方案起草） |
| 当时约束 | 当前个人项目版明确不实现 candidate commit、clean clone 和独立验收环境；Preflight 已能记录 revision、dirty 状态、依赖指纹和 HEAD 资产来源。 |
| 决策 | 当前检出只有在工作树 clean、环境和依赖受支持、活动必需检查全部产生结果并通过、其他资格门全部满足时才可 success。dirty 检出继续执行检查但总体至多 incomplete；本轮不自动创建 candidate commit 或独立 clean clone。 |
| 选择理由 | 让个人开发闭环在现有控制面内可执行，同时保留 clean 工作树这一可复现资格门，并诚实标注未进行独立 clone 验收。 |
| 备选方案及淘汰原因 | 保留独立 clean-clone 硬门：当前计划无法闭环；允许 dirty success：结果不可复现；Runner 自动提交或清理：越权并可能破坏用户文件。 |
| 关联文件/Requirement | `p0_baseline/preflight.py`, `p0_baseline/aggregation.py`, Requirements 2.2–2.5、4.2、6.3，IC-03、IC-05、IC-06 |
| 取代/被取代 | 取代 ADR-P0-013 |

## 3. 后续决策模板

```markdown
## ADR-P0-NNN：决策标题

| 字段 | 内容 |
| --- | --- |
| 状态 | Proposed / Approved / Superseded / Rejected |
| 决策日期 | YYYY-MM-DD |
| 决策人 | 实际决策人；方案起草人（如适用） |
| 当时约束 | 做出决策时存在的技术、范围、兼容、安全和环境约束 |
| 决策 | 最终选择 |
| 选择理由 | 为什么该方案最适合当时约束 |
| 备选方案及淘汰原因 | 备选 A：简短原因；备选 B：简短原因 |
| 关联文件/Requirement | 文件和数字 Requirement ID |
| 取代/被取代 | ADR ID 或 None |
```
