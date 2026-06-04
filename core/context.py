"""core.context

职责：
- 估算上下文成本
- 压缩较旧消息中的 thinking / tool_use / tool_result
- 修复裁剪后的首条 user 消息
- 修复工具调用前后的消息配对

边界：
- 这里只处理消息历史本身
- 不负责模型请求、provider 适配或日志落盘
"""

import json
import re
from typing import Any, Dict, List


def estimate_context_cost(messages: List[Dict[str, Any]]) -> int:
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)


def _trunc_str(s: str, max_len: int) -> str:
    return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:] if isinstance(s, str) and len(s) > max_len else s


def _trunc_tag_content(text: str, max_len: int) -> str:
    pats = {tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)') for tag in ('thinking', 'think', 'tool_use', 'tool_result')}
    hist_pat = re.compile(r'<(history|key_info)>[\s\S]*?</\1>')
    text = hist_pat.sub(lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text)
    for pat in pats.values(): text = pat.sub(lambda m: m.group(1) + _trunc_str(m.group(2), max_len) + m.group(3), text)
    return text


def compress_history_tags(
    messages: List[Dict[str, Any]],
    keep_recent: int = 10,
    max_len: int = 800,
    force: bool = False
) -> List[Dict[str, Any]]:
    """压缩较早消息中的长标签内容，保留 llmcore 原有节流和输出行为。"""
    compress_history_tags._cd = getattr(compress_history_tags, "_cd", 0) + 1
    if force:
        compress_history_tags._cd = 0
    if compress_history_tags._cd % 5 != 0:
        return messages
    total_before = estimate_context_cost(messages)
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent:
            break
        content = msg["content"]
        if isinstance(content, str):
            msg["content"] = _trunc_tag_content(content, max_len)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                type_ = block.get("type")
                if type_ == "text" and isinstance(block.get("text"), str):
                    block["text"] = _trunc_tag_content(block["text"], max_len)
                elif type_ == "tool_result":
                    tool_result_content = block.get("content")
                    if isinstance(tool_result_content, str):
                        block["content"] = _trunc_str(tool_result_content, max_len)
                    elif isinstance(tool_result_content, list):
                        for sub_content in tool_result_content:
                            if isinstance(sub_content, dict) and sub_content.get("type") == "text":
                                sub_content["text"] = _trunc_str(sub_content.get("text"), max_len)
                elif type_ == "tool_use" and isinstance(block.get("input"), dict):
                    for key, value in block["input"].items():
                        block["input"][key] = _trunc_str(value, max_len)
    print(f"[Cut] {total_before} -> {estimate_context_cost(messages)}")
    return messages


def _sanitize_leading_user_msg(msg: Dict[str, Any]) -> Dict[str, Any]:
    """把 user 消息里的 tool_result 块改写成纯文本，避免孤立引用。
    history 统一使用 Claude content-block 格式：content 是 list of blocks。"""
    msg = dict(msg)  # 浅拷贝外层 dict
    content = msg.get('content')
    if not isinstance(content, list): return msg
    texts = []
    for block in content:
        if not isinstance(block, dict): continue
        if block.get('type') == 'tool_result':
            c = block.get('content', '')
            if isinstance(c, list):  # content 本身也可能是 list[{type:text,text:...}]
                texts.extend(b.get('text', '') for b in c if isinstance(b, dict))
            else: texts.append(str(c))
        elif block.get('type') == 'text': texts.append(block.get('text', ''))
    msg['content'] = [{"type": "text", "text": '\n'.join(t for t in texts if t)}]
    return msg


def sanitize_leading_user_msg(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility wrapper for callers using the public name."""
    return _sanitize_leading_user_msg(msg)


def trim_messages_history(
    history: List[Dict[str, Any]],
    context_win: int,
    trigger_ratio: float = 3.0,
    target_ratio: float = 0.6,
    min_messages: int = 5,
    keep_recent: int = 4
) -> None:
    """消息压缩级别定义（按字符数估算）：
    - L1 轻压缩（标准化压缩标签）：始终执行 compress_history_tags(history)
    - L2 强压缩（触发条件）：cost > context_win * TRIGGER_RATIO
      - 先执行 force 压缩：compress_history_tags(..., keep_recent=KEEP_RECENT, force=True)
      - 再裁剪到目标：target = context_win * TRIGGER_RATIO * TARGET_RATIO
      - 直到满足 target 或消息数降到 MIN_MESSAGES
    触发参数：TRIGGER_RATIO=3, KEEP_RECENT=4, TARGET_RATIO=0.6, MIN_MESSAGES=5
    """
    # 轻压缩
    compress_history_tags(history)
    cost = estimate_context_cost(history)
    print(f"[Debug] Current context: {cost} chars, {len(history)} messages.")

    if cost <= context_win * trigger_ratio:
        return
    # 强压
    compress_history_tags(history, keep_recent=keep_recent, force=True)
    target = context_win * trigger_ratio * target_ratio
    while len(history) > min_messages and cost > target:
        history.pop(0)
        while history and history[0].get("role") != "user":
            history.pop(0)
        if history and history[0].get("role") == "user":
            history[0] = _sanitize_leading_user_msg(history[0])
        cost = estimate_context_cost(history)
    print(f"[Debug] Trimmed context, current: {cost} chars, {len(history)} messages.")


def fix_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """修复 user / assistant / tool_result 配对，保证传给模型的消息合法。"""
    if not messages: return messages
    _wrap = lambda c: c if isinstance(c, list) else [{"type": "text", "text": str(c)}]
    fixed = []
    for m in messages:
        if fixed and m['role'] == fixed[-1]['role']:
            fixed[-1] = {**fixed[-1], 'content': _wrap(fixed[-1]['content']) + [{"type": "text", "text": "\n"}] + _wrap(m['content'])}; continue
        if fixed and fixed[-1]['role'] == 'assistant' and m['role'] == 'user':
            uses = [b.get('id') for b in fixed[-1].get('content', []) if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('id')]
            has = {b.get('tool_use_id') for b in _wrap(m['content']) if isinstance(b, dict) and b.get('type') == 'tool_result'}
            miss = [uid for uid in uses if uid not in has]
            if miss: m = {**m, 'content': [{"type": "tool_result", "tool_use_id": uid, "content": "(error)"} for uid in miss] + _wrap(m['content'])}
            orphan = has - set(uses)
            if orphan: m = {**m, 'content': [{"type":"text","text":str(b.get('content',''))} if isinstance(b,dict) and b.get('type')=='tool_result' and b.get('tool_use_id') in orphan else b for b in _wrap(m['content'])]}
        fixed.append(m)
    while fixed and fixed[0]['role'] != 'user': fixed.pop(0)
    return fixed

