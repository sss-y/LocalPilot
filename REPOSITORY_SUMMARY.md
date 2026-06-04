# Repository Analysis: LocalPilot

## Overview

LocalPilot is a local, command-line Agent runtime for personal workstations and local project directories. Its purpose is to turn natural-language tasks into a closed local execution loop: an LLM session can read and patch files, run Python or shell snippets, update memory, ask the user questions, run planned multi-step work, and trigger scheduled or autonomous background tasks.

The project is intentionally local-first. The README frames it as a "本地通用 Agent" rather than a cloud chat service, browser automation product, or multi-device platform. The implementation supports that framing: the main runtime sits in `agent/`, model/session adapters in `core/`, executable tools in `tools/`, SOP and long-term memory material in `memory/`, and scheduled reflection scripts in `reflect/`.

The strongest architectural description is: LocalPilot is a lightweight Plan-and-Execute plus Multi-Agent-style task orchestration runtime. The main Agent plans, dispatches tools, preserves task state, and converges results; supporting SOPs and subagent conventions guide exploration, verification, memory settlement, and batch execution.

## Architecture

LocalPilot is organized around a single runtime loop:

1. `runagent.py` launches `agent/agentmain.py`.
2. `MyAgent` loads model configuration, initializes LLM clients, prepares system prompt and memory context, and accepts tasks from interactive CLI, `--task`, or `--reflect`.
3. `agent/agent_loop.py` repeatedly calls the selected model session, parses tool calls, dispatches tools through `tools.handler.AgentHandler`, injects tool results back into the next model turn, and stops when a tool outcome or no-tool result marks the task done.
4. `core/session.py` normalizes several LLM backends into a shared internal content-block shape: text, thinking, tool use, and tool results. It supports OpenAI-compatible chat completions, OpenAI Responses-style events, Claude-style messages, streaming, fallback parsing, and tool-call normalization.
5. `tools/` provides the runtime's action surface: code execution, file reading, patching, writing, user questions, short-term working checkpoints, and long-term memory update prompts.
6. `memory/` stores SOPs and persistent context used by the system prompt and plan workflows.
7. `reflect/` can periodically emit prompts into the same Agent runtime, making scheduled or autonomous tasks use the same execution loop as interactive tasks.
8. `core/observability.py` records compact JSONL events under `temp/logs/agent-YYYY-MM-DD.jsonl`, tying task, LLM turn, tool call, retry, exception, and completion events to a `run_id`.

The runtime is deliberately file-system oriented. `config/paths.py` centralizes stable anchors such as `PROJECT_ROOT`, `TEMP_DIR`, `TOOLS_DIR`, `MEMORY_DIR`, `SCHE_TASKS_DIR`, `MODEL_RESPONSES_DIR`, and `REFLECT_LOG_DIR`, reducing the path drift that earlier commits had started to expose.

## Key Components

- **CLI and task entrypoint (`runagent.py`, `agent/agentmain.py`)**: Starts the Agent, loads model sessions from `mykey.py` or `core/mykey.json`, handles interactive prompts, one-shot task directories, background mode, reflect scripts, stop/intervention files, and slash commands such as `/resume` and `/session.<key>=<value>`.
- **Agent execution loop (`agent/agent_loop.py`)**: Owns turn-by-turn execution. It calls the model, detects native tool calls or fallback no-tool behavior, dispatches tools, collects tool results, handles done hooks, and logs each turn.
- **LLM session layer (`core/session.py`, `core/client.py`)**: Adapts OpenAI-compatible, Claude-compatible, native tool calling, text tool protocol fallback, and mixin/fallback session behavior into one internal response model.
- **Configuration layer (`core/config.py`, `config/paths.py`)**: Loads local secret/config files, hot-reloads model configuration by modification time, enables optional Langfuse tracing, and provides canonical path constants.
- **Context management (`core/context.py`)**: Trims history to context budgets, fixes malformed message sequences, inserts missing tool results, and sanitizes adjacent user messages before model calls.
- **Tool protocol and dispatch (`tools/base.py`, `tools/handler.py`, `tools/schemas.py`)**: Converts model tool calls into `StepOutcome` objects, handles unknown or bad-JSON tools, logs tool lifecycle events, and enforces the control contract of `data`, `next_prompt`, and `should_exit`.
- **File tools (`tools/file_tools.py`)**: Read files with line numbers and truncation, expand `{{file:path:start:end}}` references, patch unique text blocks safely, write files, and consume task-control files.
- **Code tools (`tools/code_tools.py`)**: Execute Python or shell snippets in controlled working directories, stream lightweight progress logs, enforce timeouts, and propagate stop signals.
- **Memory tools (`tools/memory_tools.py`)**: Assemble global memory into the system prompt, track memory-file access counts, update short-term working checkpoints, and start long-term memory settlement using `memory/memory_management_sop.md`.
- **Plan helpers (`tools/plan_tools.py`, `memory/plan_sop.md`, `memory/verify_sop.md`, `memory/subagent.md`)**: Provide the state flag and SOP material for plan mode, verification mode, and subagent-style delegated work.
- **Reflect and scheduling (`reflect/scheduler.py`, `reflect/autonomous.py`, `sche_tasks/`)**: Poll task JSON files, enforce repeat/cooldown windows, write reports under `sche_tasks/done/`, run L4 session compression every 12 hours, and optionally emit autonomous prompts after inactivity.
- **Observability (`core/observability.py`, `core/mylogging.py`, `plugins/langfuse_tracing.py`)**: Writes compact redacted JSONL events for control-flow debugging and optionally activates Langfuse tracing when configured.
- **Documentation and local tests (`README.md`, `docs/`, `tests/`)**: The README is the canonical user-facing description. The workspace contains tests for path constants, session parsing, LLM config loading, repo tool behavior, and startup help, although `docs/` and `tests/` are currently ignored by `.gitignore` rather than tracked in the latest repository snapshot.

## Technologies Used

- **Language**: Python 3.11+ recommended by the README; the local workspace contains a `.venv` using Python 3.12.
- **Runtime dependencies**: `requests>=2.31.0`, `urllib3>=2.0.0`.
- **Optional integrations**: `langfuse>=2.0.0` through `plugins/langfuse_tracing.py`; optional `yara-python` is mentioned in README installation notes.
- **LLM protocols**: OpenAI-compatible chat completions, OpenAI Responses-style event parsing, Claude-style messages, native tool calls, and text tool-call fallback parsing.
- **Interface**: Command-line interactive mode, task-directory file I/O mode, background task mode, and reflect-script mode.
- **Storage**: Local files under `memory/`, `temp/`, `sche_tasks/`, and `temp/model_responses/`.
- **Testing approach**: Python `unittest` tests exist in the workspace for path, session, repo tools, and startup behavior.

## Data Flow

Interactive flow:

1. User runs `python runagent.py`.
2. `agent/agentmain.py` loads model config, memory prompt, tool schema, and the selected LLM client.
3. User input is wrapped into a task and pushed into `MyAgent.task_queue`.
4. `agent_runner_loop` sends system prompt and user input to the LLM session.
5. The model either responds directly or emits tool calls.
6. `AgentHandler.dispatch` calls the corresponding `do_*` tool method.
7. Tool output becomes a `StepOutcome`; its `next_prompt` is fed back into the next model turn.
8. When there is no next prompt, a tool exits, or no-tool completion passes validation, the final response is returned to the terminal.
9. JSONL observability records task start/end, LLM turns, tool calls, usage, retries, and exceptions.

Task-directory flow:

1. User runs `python runagent.py --task <name> --input "<prompt>"`.
2. Input is written to `temp/<name>/input.txt`.
3. Intermediate and final outputs are written to `output.txt`, `output1.txt`, and later numbered files.
4. External processes can add `reply.txt`, `_stop`, `_intervene`, or `_keyinfo` to steer or stop the running task.

Reflect flow:

1. User runs `python runagent.py --reflect reflect/scheduler.py` or another reflect script.
2. The reflect script's `check()` function returns a task prompt when a schedule or trigger condition is met.
3. The same `MyAgent` runtime processes that prompt.
4. Results are written to reflect logs and, for scheduled tasks, report files under `sche_tasks/done/`.

Memory flow:

1. `get_system_prompt()` reads prompt assets and appends global memory material.
2. Memory tools can update short-term `handler.working` checkpoints or initiate long-term memory settlement.
3. Reading memory/SOP files increments `memory/file_access_stats.json`, making memory usage observable.
4. `memory/L4_raw_sessions/compress_session.py` can archive model-response history into L4 raw sessions.

## Team and Ownership

Git history for the past year contains 17 commits, all authored by `sunny`. There are no merge commits, so the repository currently reads as a single-maintainer project with a linear development style.

Ownership by area is implied by the same author working across all major surfaces:

- `core/session.py`, `core/client.py`, and `core/context.py`: model protocol and context ownership.
- `tools/handler.py`, `tools/base.py`, and related tool files: tool execution and control-flow ownership.
- `agent/agentmain.py` and `agent/agent_loop.py`: runtime orchestration ownership.
- `memory/` and `reflect/`: autonomous operation, planning, scheduling, and memory lifecycle ownership.
- `README.md`: product positioning and user-facing operating guide.

The current repository state is clean, but several useful local files are intentionally ignored, including `docs/`, `tests/`, `temp/`, `.venv/`, `sche_tasks/`, and local key files. That split suggests the tracked repository is the runtime core, while experiments, evaluation artifacts, and machine-local operational state stay outside version control.
