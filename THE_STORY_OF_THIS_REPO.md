# The Story of LocalPilot

## The Chronicles: A Year in Numbers

LocalPilot's visible git history is compact and intense:

- **Total commits**: 17.
- **Commits in the past year**: 17.
- **Active month**: May 2026 only.
- **First visible commit**: `1f35beb` on 2026-05-04, "🎉 Initial commit: Setup project and venv".
- **Latest visible commit**: `39fd306` on 2026-05-28, "update memory stats".
- **Contributor count**: one visible author, `sunny`.
- **Merge commits**: none.
- **Highest-activity days**: 2026-05-27 with 6 commits, followed by 2026-05-28 with 4 commits.

The history is not a long-running product archaeology dig. It is a three-and-a-half-week sprint where a local Agent runtime appears, grows quickly, then gets reorganized into a clearer architecture.

The day-by-day shape:

- 2026-05-04: 1 commit, repository bootstrap.
- 2026-05-08: 1 commit, LLM session layer and context trimming arrive.
- 2026-05-11: 1 commit, tools and Agent loop arrive.
- 2026-05-17: 2 commits, plan mode, memory, scheduler, SOPs, and README expansion arrive.
- 2026-05-21: 1 commit, tool surface matures.
- 2026-05-22: 1 commit, small context readability pass.
- 2026-05-27: 6 commits, major restructuring and documentation cleanup.
- 2026-05-28: 4 commits, rename, README correction, structured observability, and memory stats update.

## Cast of Characters

**sunny** is the whole visible cast: runtime designer, tool author, memory-system author, documentation writer, test author, and maintainer. The work pattern is not narrow feature ownership; it is whole-system construction.

The specialties visible in the commit history are:

- **Runtime orchestration**: `agent/agentmain.py` and `agent/agent_loop.py` were split out and stabilized on 2026-05-27 in `adb7742`, turning earlier root-level scripts into a clearer package layout.
- **LLM protocol adaptation**: `core/session.py` is one of the biggest and most frequently rewritten files. It starts with the LiteLLM-based session work in `83c703d`, expands in `33a3189`, and is heavily simplified in `c7b0260`.
- **Tool execution**: `tools/handler.py`, `tools/base.py`, `tools/file_tools.py`, `tools/code_tools.py`, and the schema files show a progression from early tool stubs into a controlled `StepOutcome` contract.
- **Memory and autonomy**: `memory/plan_sop.md`, `memory/verify_sop.md`, `memory/subagent.md`, `memory/scheduled_task_sop.md`, `reflect/scheduler.py`, and `reflect/autonomous.py` show the project moving beyond one-off chat into planned, repeatable local operation.
- **Operational visibility**: `a76fd2f` adds `core/observability.py` and threads JSONL logging across `agent/`, `core/`, and `tools/`.

This is a maintainer working both as product user and infrastructure engineer: the repository adds capabilities, then quickly adds the guardrails needed to keep those capabilities debuggable.

## Seasonal Patterns

There is only one season in this history: May 2026. The project starts on 2026-05-04 and compresses what would often be several phases of a prototype into one month.

The early May phase is foundation:

- `1f35beb` creates the initial repository.
- `83c703d` adds LiteLLM integration, logging, and history trimming.
- `ae8b7e4` adds the first major tool layer and Agent loop.

The middle May phase is capability expansion:

- `33a3189` adds plan mode and autonomous memory settlement. This is the first point where the project looks less like a chat wrapper and more like a local Agent runtime.
- The same commit adds large SOP material, scheduler code, memory files, prompt assets, tests, and a large README.
- `79928a0` continues tool work, especially around `tools/handler.py` and file/code helpers.

The late May phase is consolidation:

- `adb7742` restructures the agent module and shared path config.
- `c7b0260` refactors the core module, removes older `llmcore/schema/tool_protocol` surfaces, adds `core/client.py`, and substantially reduces `core/session.py`.
- `26fd9a7`, `b1fce01`, and nearby commits keep the README aligned with the renamed entrypoint and current architecture.
- `a76fd2f` adds structured observability after the architecture has become complex enough to need it.

The most revealing rhythm is that documentation is not an afterthought. `README.md` changes in six commits, often right after structural changes. That suggests the maintainer is using the README as a live map of the system, not merely a user manual.

## The Great Themes

### Theme 1: From Script to Runtime

The earliest shape of LocalPilot appears to be a script-oriented Agent. By 2026-05-11, `agent_loop.py`, `llmcore.py`, and a full `tools/` package exist. By 2026-05-27, root-level pieces are pulled into `agent/`, `core/`, `tools/`, and `config/paths.py`.

The key turning point is `adb7742`: "refactor: restructure agent module and update tools/config". This commit introduces `agent/agentmain.py`, moves `agent_loop.py` into `agent/`, and adds `config/paths.py`. It changes the project from "a collection of working files" into "a runtime with module boundaries."

### Theme 2: Tool Calling Is the Product Core

The tool layer is not peripheral. `tools/handler.py` first grows by 376 lines in `ae8b7e4`, then keeps changing as the Agent loop matures. Current tools include:

- `code_run`
- `file_read`
- `file_patch`
- `file_write`
- `update_working_checkpoint`
- `ask_user`
- `start_long_term_update`

The interesting design choice is `StepOutcome`. Tools do not just return data; they return control-flow instructions: whether to continue, what prompt to send next, and whether the task should exit. That makes tools part of the Agent's state machine rather than simple utility calls.

### Theme 3: Memory Is Operational, Not Decorative

The memory system is implemented as local files plus SOPs, not as an external vector database. `memory/global_mem.txt`, `memory/global_mem_insight.txt`, `memory/file_access_stats.json`, and multiple SOP markdown files are read into the prompt or used by tools.

`33a3189` is the big memory expansion commit. It adds plan, verify, scheduled-task, supervisor, autonomous-operation, and subagent SOPs. Later, `39fd306` updates memory stats, showing that memory usage itself is treated as runtime data.

The story here is pragmatic: the project chooses inspectable local text and JSON as the first durable memory layer.

### Theme 4: Context and Protocol Compatibility Became a Hard Problem Early

`core/session.py` is central from the start. `83c703d` adds LiteLLM integration and context trimming. The current file handles OpenAI-compatible streaming, Claude-style SSE, Responses API-style events, reasoning/thinking blocks, tool-call argument parsing, usage recording, and fallback shapes.

The heavy refactor in `c7b0260` is a strong signal that the first model-protocol design became too broad or too tangled. That commit removes `core/llmcore.py`, `core/schema.py`, and `core/tool_protocol.py`, introduces `core/client.py`, and rewrites `core/session.py` with a much smaller surface.

### Theme 5: Debuggability Arrived After Complexity

The commit `a76fd2f`, "feat: add structured JSONL observability across the agent pipeline", is the operational maturity point. It adds `core/observability.py` and modifies `agent/agent_loop.py`, `agent/agentmain.py`, `core/session.py`, `tools/base.py`, and `README.md`.

That change adds task-level `run_id`s and compact event records for task lifecycle, LLM turns, model requests, retries, usage, tool calls, exceptions, and completion. This is the repository admitting that once an Agent can call tools and run long workflows, print debugging is not enough.

## Plot Twists and Turning Points

### The Big Expansion: 2026-05-17

Commit `33a3189`, "新增plan模式和memory自主沉淀", is the project becoming ambitious. It adds a 282-line README, a 481-line expansion to `core/session.py`, a 262-line `memory/plan_sop.md`, scheduler support, memory SOPs, prompt assets, test material, and reflective/autonomous scripts.

This is the moment where LocalPilot stops being a simple LLM command wrapper and becomes an attempt at a persistent local Agent system.

### The Tool-Layer Consolidation: 2026-05-21

Commit `79928a0`, simply named "tools", is modestly titled but meaningful. It changes README, `agent_loop.py`, `agentmain.py`, `tools/file_tools.py`, `tools/handler.py`, and other utility modules. The handler gains most of the lines in this commit, showing that the maintainer was discovering the real complexity: reliable tool dispatch and task continuation.

### The Architecture Refactor: 2026-05-27

Two commits define this day:

- `adb7742`: restructures `agent/`, updates tools and config, and introduces shared path constants.
- `c7b0260`: refactors `core/`, removes older protocol modules, adds `core/client.py`, and simplifies `core/session.py`.

The day has six commits total. It reads like a cleanup sprint after the system proved useful enough to deserve better boundaries.

### The Rename: 2026-05-28

Commit `c3b3967`, "rename, 避免冲突", renames `agentmain.py` to `runagent.py`. The next docs commit updates README references. Small as it is, the rename matters: the root entrypoint becomes a launcher, while the implementation entrypoint lives under `agent/agentmain.py`.

### The Observability Layer: 2026-05-28

Commit `a76fd2f` adds 427 insertions across the runtime. It is the moment the project starts treating Agent execution as something that needs traceable operations: task starts and ends, LLM turn durations, tool exceptions, retry behavior, and token usage.

This is also where the repository's story becomes more production-minded. The code still targets a local personal Agent, but it now has enough instrumentation to diagnose local failures instead of guessing.

## The Current Chapter

LocalPilot currently stands as a compact, local-first Agent runtime with a clear architecture:

- `agent/` handles orchestration.
- `core/` handles model sessions, configuration, context, logging, and observability.
- `tools/` handles the executable action surface.
- `memory/` holds SOPs and persistent prompt material.
- `reflect/` turns the same runtime into a scheduler/autonomous worker.
- `README.md` documents the intended operating model.

The repository is still early. Its tracked history is only 17 commits, and some useful local material such as `tests/`, `docs/`, and `temp/` is ignored. The current git snapshot therefore represents the runtime core more than the full working environment.

The next natural chapter is hardening:

- Decide which tests should be tracked and make the test command part of normal development.
- Clarify boundaries between runtime state (`temp/`, `sche_tasks/`, memory stats) and reusable project code.
- Keep `core/session.py` narrow as more provider protocols are added.
- Expand observability around task-directory and reflect workflows.
- Preserve the current local-first architecture instead of drifting into a general cloud Agent platform.

The human story is straightforward: one maintainer built a tool for making a local machine act through an Agent loop, then quickly learned that planning, memory, paths, protocol normalization, and logs are not extras. They are the actual runtime.
