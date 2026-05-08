"""Multi-turn regression script for session/context/tool protocol flow.

Default behavior:
- run deterministic local tests for history trimming
- run deterministic local tests for multi-tag merging

Optional:
- set ENABLE_REAL_MODEL_SMOKE=1 to also call the real configured model
"""

from __future__ import annotations

import copy
import os

from core.config import reload_mykeys
from core.context import estimate_context_cost
from core.session import NativeClaudeSession, NativeToolClient


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file content",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]


class InspectNativeSession(NativeClaudeSession):
    def __init__(self, cfg, scripted_blocks):
        super().__init__(cfg)
        self.scripted_blocks = [copy.deepcopy(blocks) for blocks in scripted_blocks]
        self.observed_messages = []
        self._turn_index = 0

    def raw_ask(self, messages):
        self.observed_messages.append(copy.deepcopy(messages))
        idx = min(self._turn_index, len(self.scripted_blocks) - 1)
        blocks = copy.deepcopy(self.scripted_blocks[idx])
        self._turn_index += 1
        for block in blocks:
            if block.get("type") == "text" and block.get("text"):
                yield block["text"]
        return blocks


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def run_history_trim_test(base_cfg):
    cfg = dict(base_cfg)
    cfg["context_win"] = 120

    backend = InspectNativeSession(
        cfg,
        scripted_blocks=[[{"type": "text", "text": f"ack-{i}"}] for i in range(8)],
    )

    for turn in range(8):
        msg = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"turn={turn}\n"
                        + "<thinking>" + ("A" * 120) + "</thinking>\n"
                        + "<tool_result>" + ("B" * 120) + "</tool_result>\n"
                        + "<history>" + ("C" * 120) + "</history>"
                    ),
                }
            ],
        }
        gen = backend.ask(msg)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

    sent_messages = backend.observed_messages[-1]
    sent_cost = estimate_context_cost(sent_messages)
    target = cfg["context_win"] * 3 * 0.6

    assert_true(
        len(sent_messages) <= 5 or sent_cost <= target,
        f"history trim failed: len={len(sent_messages)} cost={sent_cost} target={target}",
    )
    assert_true(
        sent_messages[0]["role"] == "user",
        "trimmed history should still start with a user message",
    )

    print("[PASS] history_trim")
    print("  sent_messages =", len(sent_messages))
    print("  sent_cost =", sent_cost)
    print("  target =", target)


def run_multi_tag_merge_test(base_cfg):
    backend = InspectNativeSession(
        base_cfg,
        scripted_blocks=[
            [
                {"type": "text", "text": "need tools"},
                {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "a.py"}},
                {"type": "tool_use", "id": "call_2", "name": "read_file", "input": {"path": "b.py"}},
            ],
            [{"type": "text", "text": "merged ok"}],
        ],
    )
    client = NativeToolClient(backend)

    first_gen = client.chat(
        [{"role": "user", "content": "先决定是否需要工具"}],
        tools=TOOLS,
    )
    try:
        while True:
            next(first_gen)
    except StopIteration as stop:
        first_resp = stop.value

    assert_true(len(first_resp.tool_calls) == 2, "first turn should produce two pending tool calls")

    second_messages = [
        {
            "role": "user",
            "content": "工具结果已返回，请继续",
            "tool_results": [
                {"tool_use_id": "call_1", "content": "a.py content"},
            ],
        }
    ]
    second_gen = client.chat(second_messages, tools=TOOLS)
    try:
        while True:
            next(second_gen)
    except StopIteration:
        pass

    merged_user_msg = backend.observed_messages[-1][-1]
    merged_blocks = merged_user_msg["content"]

    assert_true(merged_blocks[0]["type"] == "tool_result", "merged message should start with tool_result")
    assert_true(merged_blocks[0]["tool_use_id"] == "call_1", "resolved tool_result id missing")
    assert_true(
        any(
            block.get("type") == "tool_result" and block.get("tool_use_id") == "call_2" and block.get("content") == ""
            for block in merged_blocks
        ),
        "missing auto-added blank tool_result for unresolved pending id",
    )
    assert_true(
        any(block.get("type") == "text" and "工具结果已返回" in block.get("text", "") for block in merged_blocks),
        "merged message should preserve user text block",
    )

    print("[PASS] multi_tag_merge")
    print("  pending_after_turn1 =", [tool.id for tool in first_resp.tool_calls])
    print("  merged_block_types =", [block.get("type") for block in merged_blocks])


def run_real_model_smoke(base_cfg):
    backend = NativeClaudeSession(base_cfg)
    client = NativeToolClient(backend)
    messages = [
        {"role": "user", "content": "读取他.py的文件内容,请先思考，再决定是否需要工具。"}
    ]

    gen = client.chat(messages, tools=TOOLS)
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as stop:
        resp = stop.value

    print("[PASS] real_model_smoke")
    print("  text =", "".join(chunks))
    print("  tool_calls =", getattr(resp, "tool_calls", []))
    print("  log =", client.logger.log_path())


def main():
    mykeys, _ = reload_mykeys()
    cfg = mykeys["native_claude_dash_config"]

    run_history_trim_test(cfg)
    run_multi_tag_merge_test(cfg)

    if os.environ.get("ENABLE_REAL_MODEL_SMOKE") == "1":
        run_real_model_smoke(cfg)
    else:
        print("[SKIP] real_model_smoke (set ENABLE_REAL_MODEL_SMOKE=1 to enable)")


if __name__ == "__main__":
    main()
