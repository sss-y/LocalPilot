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
from typing import List, Dict, Any
import logging

def estimate_context_cost(messages: List[Dict[str, Any]]) -> int:
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)

# 如果待处理的是字符串,
# 传入的字符串,如果超过 max_len，则保留前后各 max_len//2 字符，并在中间插入 "\n...[Truncated]...\n" 提示。
def _trunc_str(s: str, max_len: int) -> str:
    return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:] if isinstance(s, str) and len(s) > max_len else s

# 如果是文本串表示的块信息,需要匹配
# 将thinking、tool_use、tool_result标签内的文本进行截断，并将history、key_info标签内的内容整段替换为 "[...]"
def _trunc_tag_content(text: str,max_len: int) -> str:
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

    """

    压缩较早历史中的 thinking / tool_use / tool_result / history / key_info。

    注意：这是 Agent 语义压缩，不是 LiteLLM 能替代的 provider 适配。

    """
    """
    原地裁剪 history。
    先轻压缩，再在超过阈值时强压缩并删除早期消息。
    - 压缩对话历史中较早消息里包含的长文本（如 <thinking>、 groundwork、<tool_use>、<tool_result> 标签），
        以节省 token/字符数并加快后续处理。
    - 默认保留最近 keep_recent 条消息不被压缩；通过 force=True 可强制立即执行。
    - 内部使用一个计数器，每 5 次调用才实际进行压缩，以避免过于频繁地修改历史。
    - 对过长文本进行前后截断并插入 "...[Truncated]..." 提示；对 <history> 或 <key_info> 标签之间的内容整段替换为 "[...]"。trunc_str trun函数实现
    - 在原地修改传入的 messages 列表，并打印压缩前后字节/字符长度信息。
    
    """
    compress_history_tags._count = getattr(compress_history_tags, '_count', 0) + 1
    # 强制压缩后重置计数器，确保下一次调用仍然会在 5 次内触发压缩。
    if force:
        compress_history_tags._count = 0
    if not force and compress_history_tags._count % 5 != 0:
        return messages
    total_before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    
    # 修改messages列表,保留keep_recent条消息不被压缩,对其他消息进行压缩处理。
    for i in range(len(messages)):
        if(i >= len(messages) - keep_recent): break
        content = messages[i].get('content')
        # 标签混在文本中
        if(isinstance(content,str)): messages[i]['content'] = _trunc_tag_content(content, max_len)
        # content直接是块结构
        elif(isinstance(content, list)):
            #对多层嵌套进行处理
            for j,block in enumerate(content):
                if not isinstance(block, dict): continue
                type_ = block.get('type')
                if type_== 'text' and isinstance(block.get('text'), str):
                    # text标签,需要对thinking标签处理
                    block['text'] = _trunc_tag_content(block['text'], max_len)
                # type是tooluse和tool_result,是块结构,提取并逐一处理文本信息
                elif type_=='tool_use'and isinstance(block.get('input'), dict):
                    for k,v in block['input'].items():
                        block['input'][k] = _trunc_str(v, max_len)
                elif type_== 'tool_result':
                    # 结构:content标签中,可能是但字符串,也可能是多条文本块的列表,需要分别处理。
                    tool_result_content = block.get('content')
                    if isinstance(tool_result_content, str):
                        block['content'] = _trunc_str(tool_result_content, max_len)
                    elif isinstance(tool_result_content, list):
                        for k,sub_content in enumerate(tool_result_content):
                            if isinstance(sub_content, dict) and sub_content.get('type') == 'text' and isinstance(sub_content.get('text'), str):
                                sub_content['text'] = _trunc_str(sub_content['text'], max_len)
    logging.info(f"cut{total_before}, after={sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)} ")

    return messages


def sanitize_leading_user_msg(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    当裁剪后首条消息含孤立 tool_result 时，将其转成纯文本，避免消息协议非法。
    """
# 函数作用:确保裁剪上下文完成之后,裁剪后第一条 user 是否只剩 tool_result 引用,
# 但是没有 thinking 或 tool_use ,可能导致大模型出现幻觉,认为 tool_result 是孤立的,从而破坏协议.因此需要把这种情况改写成纯文本消息.
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

def trim_messages_history(
    history: List[Dict[str, Any]],
    context_win: int,
    trigger_ratio: float = 3.0,
    target_ratio: float = 0.6,
    min_messages: int = 5,
    keep_recent: int = 4
) -> None:
    compress_history_tags(history)
    cost = estimate_context_cost(history)

    if cost <= context_win * trigger_ratio:
        return

    compress_history_tags(history, keep_recent=keep_recent, force=True)
    target = context_win * trigger_ratio * target_ratio

    while len(history) > min_messages and estimate_context_cost(history) > target:
        history.pop(0)
        while history and history[0].get("role") != "user":
            history.pop(0)
        if history and history[0].get("role") == "user":
            history[0] = sanitize_leading_user_msg(history[0])


def fix_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    修复 user / assistant / tool_result 配对，保证传给模型的消息合法。
    第一版可以只做最小检查。
    """
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
    return messages

# 针对消息发送的模块,后续可能移动到session模块中
def _keep_claude_block(b): return not isinstance(b, dict) or b.get("type") != "thinking" or b.get("signature")

# 针对claude,将没有signature的thinking块直接丢弃
def _drop_unsigned_thinking(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list): m["content"] = [b for b in c if _keep_claude_block(b)]
    return messages

# 针对deepseek等需要think的模型,确保消息里面包含thinking;
def _ensure_thinking_blocks(messages, model):
    """deepseek needs thinking in history!"""
    if 'deepseek' not in model.lower(): return messages
    for m in messages:
        if m.get("role") != "assistant": continue
        c = m.get("content")
        if not isinstance(c, list): continue
        has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in c)
        if not has_thinking: m["content"] = [{"type": "thinking", "thinking": "...", "signature": "placeholder"}, *c]
    return messages
