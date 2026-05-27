import json, re, time, requests, threading, urllib3, uuid
from core import config as _config
from core.client import (
    MockResponse as _MockResponse,
    MockToolCall as _MockToolCall,
    _parse_text_tool_calls,
)
from core.context import (
    fix_messages as _fix_messages,
    trim_messages_history as _trim_messages_history,
)
from core.mylogging import _write_llm_log
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_RESP_CACHE_KEY = str(uuid.uuid4())
__all__ = [
    "BaseSession",
    "ClaudeSession",
    "LLMSession",
    "NativeClaudeSession",
    "NativeOAISession",
    "MixinSession",
    "auto_make_url",
    "openai_tools_to_claude",
]

def __getattr__(name):  # once guard in PEP 562
    if name == 'mykeys': return _config.reload_mykeys()[0]
    raise AttributeError(f"module 'llmcore' has no attribute {name}")

_oldprint = print
def safeprint(*argv):
    """包装系统 print 函数，捕获 OSError 异常，防止在某些环境（如管道断裂、文件关闭）下程序崩溃。
    
    作用：
    - 安全地输出日志信息，避免因 I/O 错误导致程序中断
    - 适用于多线程、网络、远程执行等不稳定输出场景
    
    输入：*argv - 任意个数的参数，与标准 print() 用法相同
    输出：无（print 无返回值）
    
    调用时机：
    - 模块加载时将全局 print 替换为 safeprint
    - 此后所有 print() 调用都经过异常处理
    - 特别适合在 LLM 通信、日志记录等关键路径中使用
    """
    try: _oldprint(*argv)
    except OSError: pass
print = safeprint

def auto_make_url(base, path):
    b, p = base.rstrip('/'), path.strip('/')
    if b.endswith('$'): return b[:-1].rstrip('/')
    if b.endswith(p): return b
    return f"{b}/{p}" if re.search(r'/v\d+(/|$)', b) else f"{b}/v1/{p}"

def _parse_claude_json(data):
    content_blocks = data.get("content", [])
    _record_usage(data.get("usage", {}), "messages")
    for b in content_blocks:
        if b.get("type") == "text": yield b.get("text", "")
        elif b.get("type") == "thinking": yield ""
    return content_blocks

def _parse_claude_sse(resp_lines):
    """Parse Anthropic SSE stream. Yields text chunks, returns list[content_block]."""
    content_blocks = []; current_block = None; tool_json_buf = ""
    stop_reason = None; got_message_stop = False; warn = None
    for line in resp_lines:
        if not line: continue
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line.startswith("data:"): continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]": break
        try: evt = json.loads(data_str)
        except Exception as e:
            print(f"[SSE] JSON parse error: {e}, line: {data_str[:200]}")
            continue
        evt_type = evt.get("type", "")
        if evt_type == "message_start":
            usage = evt.get("message", {}).get("usage", {})
            _record_usage(usage, "messages")
        elif evt_type == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text": current_block = {"type": "text", "text": ""}
            elif block.get("type") == "thinking": current_block = {"type": "thinking", "thinking": "", "signature": ""}
            elif block.get("type") == "tool_use":
                current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                tool_json_buf = ""
        elif evt_type == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if current_block and current_block.get("type") == "text": current_block["text"] += text
                if text: yield text
            elif delta.get("type") == "thinking_delta":
                if current_block and current_block.get("type") == "thinking": current_block["thinking"] += delta.get("thinking", "")
            elif delta.get("type") == "signature_delta":
                if current_block and current_block.get("type") == "thinking":
                    current_block["signature"] = current_block.get("signature", "") + delta.get("signature", "")
            elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
        elif evt_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                    except: current_block["input"] = {"_raw": tool_json_buf}
                content_blocks.append(current_block)
                current_block = None
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens: print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
        elif evt_type == "message_stop": got_message_stop = True
        elif evt_type == "error":
            err = evt.get("error", {})
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            warn = f"\n\n!!!Error: SSE {emsg}"; break
    if not warn:
        if not got_message_stop and not stop_reason: warn = "\n\n[!!! 流异常中断，未收到完整响应 !!!]"
        elif stop_reason == "max_tokens": warn = "\n\n[!!! Response truncated: max_tokens !!!]"
    if current_block:
        if current_block["type"] == "tool_use":
            try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
            except: current_block["input"] = {"_raw": tool_json_buf}
        content_blocks.append(current_block); current_block = None
    if warn:
        print(f"[WARN] {warn.strip()}")
        content_blocks.append({"type": "text", "text": warn}); yield warn
    return content_blocks

def _try_parse_tool_args(raw):
    """Parse tool args string; split concatenated JSON objects like {..}{..} if needed.
    Returns list of parsed dicts."""
    if not raw: return [{}]
    try: return [json.loads(raw)]
    except: pass
    parts = re.split(r'(?<=\})(?=\{)', raw)
    if len(parts) > 1:
        parsed = []
        for p in parts:
            try: parsed.append(json.loads(p))
            except: return [{"_raw": raw}]
        return parsed
    return [{"_raw": raw}]

def _parse_openai_sse(resp_lines, api_mode="chat_completions"):
    """Parse OpenAI SSE stream (chat_completions or responses API).
    Yields text chunks, returns list[content_block].
    content_block: {type:'text', text:str} | {type:'tool_use', id:str, name:str, input:dict}
    """
    content_text = ""
    if api_mode == "responses":
        seen_delta = False; fc_buf = {}; current_fc_idx = None
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            etype = evt.get("type", "")
            if etype == "response.output_text.delta":
                delta = evt.get("delta", "")
                if delta: seen_delta = True; content_text += delta; yield delta
            elif etype == "response.output_text.done" and not seen_delta:
                text = evt.get("text", "")
                if text: content_text += text; yield text
            elif etype == "response.output_item.added":
                item = evt.get("item", {})
                if item.get("type") == "function_call":
                    idx = evt.get("output_index", 0)
                    fc_buf[idx] = {"id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "args": ""}
                    current_fc_idx = idx
            elif etype == "response.function_call_arguments.delta":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] += evt.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] = evt.get("arguments", fc_buf[idx]["args"])
            elif etype == "error":
                err = evt.get("error", {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                if emsg: content_text += f"!!!Error: {emsg}"; yield f"!!!Error: {emsg}"
                break
            elif etype == "response.completed":
                usage = evt.get("response", {}).get("usage", {})
                _record_usage(usage, api_mode)
                break
        blocks = []
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(fc_buf):
            fc = fc_buf[idx]
            inps = _try_parse_tool_args(fc["args"])
            for i, inp in enumerate(inps):
                bid = fc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": fc["name"], "input": inp})
        return blocks
    else:
        tc_buf = {}  # index -> {id, name, args}
        reasoning_text = ""
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            ch = (evt.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_text += delta["reasoning_content"]
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                has_name = bool(tc.get("function", {}).get("name"))
                if idx not in tc_buf:
                    if has_name or not tc_buf: tc_buf[idx] = {"id": tc.get("id") or '', "name": "", "args": ""}
                    else: idx = max(tc_buf)
                if has_name: tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
                if tc.get("id") and not tc_buf[idx]["id"]: tc_buf[idx]["id"] = tc["id"]
            usage = evt.get("usage")
            if usage: _record_usage(usage, api_mode)
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            inps = _try_parse_tool_args(tc["args"])
            for i, inp in enumerate(inps):
                bid = tc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": tc["name"], "input": inp})
        return blocks

def _record_usage(usage, api_mode):
    if not usage: return
    if api_mode == 'responses':
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("input_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
    elif api_mode == 'chat_completions':
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        inp = usage.get("prompt_tokens", 0)
        print(f"[Cache] input={inp} cached={cached}")
    elif api_mode == 'messages':
        ci, cr, inp = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0), usage.get("input_tokens", 0)
        print(f"[Cache] input={inp} creation={ci} read={cr}")
    
def _parse_openai_json(data, api_mode="chat_completions"):
    blocks = []
    if api_mode == "responses":
        _record_usage(data.get("usage") or {}, api_mode)
        for item in (data.get("output") or []):
            if item.get("type") == "message":
                for p in (item.get("content") or []):
                    if p.get("type") in ("output_text", "text") and p.get("text"):
                        blocks.append({"type": "text", "text": p["text"]}); yield p["text"]
            elif item.get("type") == "function_call":
                try: args = json.loads(item.get("arguments", "")) if item.get("arguments") else {}
                except: args = {"_raw": item.get("arguments", "")}
                blocks.append({"type": "tool_use", "id": item.get("call_id", item.get("id", "")),
                               "name": item.get("name", ""), "input": args})
    else:
        _record_usage(data.get("usage") or {}, api_mode)
        msg = (data.get("choices") or [{}])[0].get("message", {})
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content}); yield content
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try: args = json.loads(fn.get("arguments", "")) if fn.get("arguments") else {}
            except: args = {"_raw": fn.get("arguments", "")}
            blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
    return blocks

def _stamp_oai_cache_markers(messages, model):
    """Add cache_control to last 2 user messages for Anthropic models via OAI-compatible relay."""
    ml = model.lower()
    if not any(k in ml for k in ('claude', 'anthropic')): return
    user_idxs = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    for idx in user_idxs[-2:]:
        c = messages[idx].get('content')
        if isinstance(c, str):
            messages[idx] = {**messages[idx], 'content': [{'type': 'text', 'text': c, 'cache_control': {'type': 'ephemeral'}}]}
        elif isinstance(c, list) and c:
            c = list(c); c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            messages[idx] = {**messages[idx], 'content': c}

def _stream_with_retry(sess, url, headers, payload, parse_fn):
    _RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}
    def _delay(resp, attempt):
        try: ra = float((resp.headers or {}).get("retry-after"))
        except: ra = None
        return max(0.5, ra if ra is not None else min(30.0, 1.5 * (2 ** attempt)))
    for attempt in range(sess.max_retries + 1):
        streamed = False
        try:
            with requests.post(url, headers=headers, json=payload, stream=sess.stream, 
                               timeout=(sess.connect_timeout, sess.read_timeout), proxies=sess.proxies, verify=sess.verify) as r:
                if r.status_code >= 400:
                    if r.status_code in _RETRYABLE and attempt < sess.max_retries:
                        d = _delay(r, attempt)
                        print(f"[LLM Retry] HTTP {r.status_code}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                        time.sleep(d); continue
                    try: body = r.text.strip()[:500]
                    except: body = ""
                    err = f"!!!Error: HTTP {r.status_code}" + (f": {body}" if body else "")
                    yield err; return [{"type": "text", "text": err}]
                gen = parse_fn(r)
                try:
                    while True: streamed = True; yield next(gen)
                except StopIteration as e: return e.value or []
        except (requests.Timeout, requests.ConnectionError) as e:
            err = f"!!!Error: {type(e).__name__}"
            if attempt < sess.max_retries:
                d = _delay(None, attempt)
                print(f"[LLM Retry] {type(e).__name__}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                yield err; time.sleep(d); continue
            yield err; return [{"type": "text", "text": err}]
        except Exception as e:
            err = f"\n\n[!!! 流异常中断 {type(e).__name__}: {e} !!!]" if streamed else f"!!!Error: {type(e).__name__}: {e}"
            yield err; return [{"type": "text", "text": err}]

def _openai_stream(sess, messages):
    model, api_mode = sess.model, sess.api_mode
    ml = model.lower()
    temperature = sess.temperature
    if 'kimi' in ml or 'moonshot' in ml: temperature = 1
    elif 'minimax' in ml: temperature = max(0.01, min(temperature, 1.0))  # MiniMax requires temp in (0, 1]
    headers = {"Authorization": f"Bearer {sess.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_mode == "responses":
        url = auto_make_url(sess.api_base, "responses")
        payload = {"model": model, "input": _to_responses_input(messages), "stream": sess.stream, 
                   "prompt_cache_key": _RESP_CACHE_KEY, "instructions": sess.system or "You are an Omnipotent Executor."}
        if sess.reasoning_effort: payload["reasoning"] = {"effort": sess.reasoning_effort}
        if sess.max_tokens: payload["max_output_tokens"] = sess.max_tokens
    else:
        url = auto_make_url(sess.api_base, "chat/completions")
        if sess.system: messages = [{"role": "system", "content": sess.system}] + messages
        _stamp_oai_cache_markers(messages, model)
        payload = {"model": model, "messages": messages, "stream": sess.stream}
        if sess.stream: payload["stream_options"] = {"include_usage": True}
        if temperature != 1: payload["temperature"] = temperature
        if sess.max_tokens: payload["max_completion_tokens" if ml.startswith(("gpt-5", "o1", "o2", "o3", "o4")) else "max_tokens"] = sess.max_tokens
        if sess.reasoning_effort: payload["reasoning_effort"] = sess.reasoning_effort
    tools = getattr(sess, 'tools', None)
    if tools: payload["tools"] = _prepare_oai_tools(tools, api_mode)
    if sess.service_tier: payload["service_tier"] = sess.service_tier
    parse_fn = (lambda r: _parse_openai_sse(r.iter_lines(), api_mode)) if sess.stream else (lambda r: _parse_openai_json(r.json(), api_mode))
    return (yield from _stream_with_retry(sess, url, headers, payload, parse_fn))
        
def _prepare_oai_tools(tools, api_mode="chat_completions"):
    if api_mode == "responses":
        resp_tools = []
        for t in tools:
            if t.get("type") == "function" and "function" in t:
                rt = {"type": "function"}; rt.update(t["function"])
                resp_tools.append(rt)
            else: resp_tools.append(t)
        return resp_tools
    return tools

def _to_responses_input(messages):
    result, pending = [], []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        if role == "tool":
            cid = msg.get("tool_call_id") or (pending.pop(0) if pending else f"call_{uuid.uuid4().hex[:8]}")
            result.append({"type": "function_call_output", "call_id": cid, "output": msg.get("content", "")})
            continue
        if role not in ["user", "assistant", "system", "developer"]: role = "user"
        if role == "system": role = "developer"  # Responses API uses 'developer' instead of 'system'
        content = msg.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if isinstance(content, str):
            if content: parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text: parts.append({"type": text_type, "text": text})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and role != "assistant": parts.append({"type": "input_image", "image_url": url})
        if len(parts) == 0: parts = [{"type": text_type, "text": str(content) if not isinstance(content, list) else '[empty]'}]
        result.append({"role": role, "content": parts})
        pending = []
        for tc in (msg.get("tool_calls") or []):
            f = tc.get("function", {})
            cid = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            pending.append(cid)
            result.append({"type": "function_call", "call_id": cid, "name": f.get("name", ""), "arguments": f.get("arguments", "")})
    return result


def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls, reasoning = [], [], ""
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "thinking" and b.get("thinking"): reasoning = b["thinking"]
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or '', "type": "function",
                        "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
                    })
            m = {"role": "assistant"}
            if reasoning: m["reasoning_content"] = reasoning
            if text_parts: m["content"] = text_parts
            else: m["content"] = ""
            if tool_calls: m["tool_calls"] = tool_calls
            if not text_parts and not tool_calls and reasoning: m["content"] = "."
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict) and x.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": b.get("tool_use_id") or '', "content": tr if isinstance(tr, str) else str(tr)})
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}})
                elif b.get("type") == "image_url": text_parts.append(b)
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts: result.append({"role": "user", "content": text_parts})
        else: result.append(msg)
    return result


class BaseSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']
        self.api_base = cfg['apibase'].rstrip('/')
        self.model = cfg.get('model', '')
        self.context_win = cfg.get('context_win', 28000)
        self.history = []
        self.lock = threading.Lock()
        self.system = ""
        self.name = cfg.get('name', self.model)
        proxy = cfg.get('proxy')
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.max_retries = max(0, int(cfg.get('max_retries', 4)))
        self.verify = cfg.get('verify', True)
        self.stream = cfg.get('stream', True)
        default_ct, default_rt = (5, 30) if self.stream else (10, 240)
        self.connect_timeout = max(1, int(cfg.get('timeout', default_ct)))
        self.read_timeout = max(5, int(cfg.get('read_timeout', default_rt)))
        def _enum(key, valid):
            v = cfg.get(key); v = None if v is None else str(v).strip().lower()
            return v if not v or v in valid else print(f"[WARN] Invalid {key} {v!r}, ignored.")
        self.reasoning_effort = _enum('reasoning_effort', {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'})
        self.service_tier = _enum('service_tier', {'auto', 'default', 'priority', 'flex'})
        self.thinking_type = _enum('thinking_type', {'adaptive', 'enabled', 'disabled'})
        self.thinking_budget_tokens = cfg.get('thinking_budget_tokens')
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        self.api_mode = 'responses' if mode in ('responses', 'response') else 'chat_completions'
        self.temperature = cfg.get('temperature', 1)
        self.max_tokens = cfg.get('max_tokens')
    # 将 Claude 的 thinking 参数对应的内容转换成字典,并设置reasoning规则为output_config的值
    def _apply_claude_thinking(self, payload):
        if self.thinking_type:
            thinking = {"type": self.thinking_type}# 字典类型,并初始化为 type 键对应 thinking_type 的值
            if self.thinking_type == 'enabled':
                if self.thinking_budget_tokens is None: print("[WARN] thinking_type='enabled' requires thinking_budget_tokens, ignored.")
                else:
                    thinking["budget_tokens"] = self.thinking_budget_tokens; payload["thinking"] = thinking
            else: payload["thinking"] = thinking
        if self.reasoning_effort:
            effort = {'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'max'}.get(self.reasoning_effort)
            if effort: payload["output_config"] = {"effort": effort}
            else: print(f"[WARN] reasoning_effort {self.reasoning_effort!r} is unsupported for Claude output_config.effort, ignored.")
    
    def ask(self, prompt):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                _trim_messages_history(self.history, self.context_win)
                messages = self.make_messages(self.history)
            content_blocks = None; content = ''
            gen = self.raw_ask(messages)
            try:
                while True: chunk = next(gen); content += chunk; yield chunk
            # 如果捕捉到 StopIteration，说明raw_ask的yield结束,
            except StopIteration as e: content_blocks = e.value or []

            if len(content_blocks) > 1: 
                print(f"[DEBUG BaseSession.ask] content_blocks: {content_blocks}")
            for block in (content_blocks or []):
                if block.get('type', '') == 'tool_use':
                    tu = {'name': block.get('name', ''), 'arguments': block.get('input', {})}
                    yield f'<tool_use>{json.dumps(tu, ensure_ascii=False)}</tool_use>'
            if not content.startswith("!!!Error:"): 
                self.history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
        return _ask_gen() if self.stream else ''.join(list(_ask_gen()))

def _keep_claude_block(b): return not isinstance(b, dict) or b.get("type") != "thinking" or b.get("signature")
def _drop_unsigned_thinking(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list): m["content"] = [b for b in c if _keep_claude_block(b)]
    return messages

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

class ClaudeSession(BaseSession):
    def raw_ask(self, messages):
        if self.max_tokens is None: self.max_tokens = 8192
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": "prompt-caching-2024-07-31"}
        payload = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        if self.system: payload["system"] = [{"type": "text", "text": self.system, "cache_control": {"type": "persistent"}}]
        url = auto_make_url(self.api_base, "messages")
        if self.stream:
            parse_fn = lambda r: _parse_claude_sse(r.iter_lines())
        else:
            parse_fn = lambda r: _parse_claude_json(r.json())
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn))
    def make_messages(self, raw_list):
        msgs = _drop_unsigned_thinking([{"role": m['role'], "content": list(m['content'])} for m in raw_list])
        user_idxs = [i for i, m in enumerate(msgs) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            msgs[idx]["content"][-1] = dict(msgs[idx]["content"][-1], cache_control={"type": "ephemeral"})
        return msgs

class LLMSession(BaseSession):
    def raw_ask(self, messages): return (yield from _openai_stream(self, messages))
    def make_messages(self, raw_list): return _msgs_claude2oai(raw_list)

class NativeClaudeSession(BaseSession):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.fake_cc_system_prompt = cfg.get("fake_cc_system_prompt", False)
        self.user_agent = cfg.get("user_agent", "claude-cli/2.1.113 (external, cli)")
        self._session_id = str(uuid.uuid4())
        self._account_uuid = str(uuid.uuid4())
        self._device_id = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        self.tools = None
    def raw_ask(self, messages):
        messages = _ensure_thinking_blocks(_drop_unsigned_thinking(_fix_messages(messages)), self.model)
        if self.max_tokens is None: self.max_tokens = 8192
        model = self.model
        beta_parts = ["claude-code-20250219", "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12", "prompt-caching-scope-2026-01-05"]
        if "[1m]" in model.lower():
            beta_parts.insert(1, "context-1m-2025-08-07"); model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(beta_parts), "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": self.user_agent, "x-app": "cli"}
        if self.api_key.startswith("sk-ant-"): headers["x-api-key"] = self.api_key
        else: headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        payload["metadata"] = {"user_id": json.dumps({"device_id": self._device_id, "account_uuid": self._account_uuid, "session_id": self._session_id}, separators=(',', ':'))}
        if self.tools:
            claude_tools = openai_tools_to_claude(self.tools)
            tools = [dict(t) for t in claude_tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        else: print("[ERROR] No tools provided for this session.")
        payload['system'] = [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude.", "cache_control": {"type": "ephemeral"}}]
        if self.system:
            if self.fake_cc_system_prompt: messages[0]["content"].insert(0, {"type": "text", "text": self.system})
            else: payload["system"] = [{"type": "text", "text": self.system}]
        user_idxs = [i for i, m in enumerate(messages) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            messages[idx] = {**messages[idx], "content": list(messages[idx]["content"])}
            messages[idx]["content"][-1] = dict(messages[idx]["content"][-1], cache_control={"type": "ephemeral"})
        url = auto_make_url(self.api_base, "messages") + '?beta=true'
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn))

    def ask(self, msg):
        assert type(msg) is dict
        with self.lock:
            self.history.append(msg)
            _trim_messages_history(self.history, self.context_win)
            messages = [{"role": m["role"], "content": list(m["content"])} for m in self.history]
        content_blocks = None
        gen = self.raw_ask(messages)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []

        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("!!!Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
            
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [_MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in content_blocks if b.get("type") == "tool_use"]
        if not tool_calls: tool_calls, content = _parse_text_tool_calls(content)
        thinking_parts = [b["thinking"] for b in content_blocks if b.get("type") == "thinking"]
        thinking = "\n".join(thinking_parts).strip()
        if not thinking:
            think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
            think_match = re.search(think_pattern, content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(think_pattern, "", content, flags=re.DOTALL)
        return _MockResponse(thinking, content, tool_calls, str(content_blocks))

class NativeOAISession(NativeClaudeSession):
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        return (yield from _openai_stream(self, _msgs_claude2oai(messages)))

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})})
    return result

class MixinSession:
    """Multi-session fallback with spring-back to primary."""
    def __init__(self, all_sessions, cfg):
        self._retries, self._base_delay = cfg.get('max_retries', 3), cfg.get('base_delay', 1.5)
        self._spring_sec = cfg.get('spring_back', 300)
        self._sessions = [all_sessions[i].backend if isinstance(i, int) else 
                          next(s.backend for s in all_sessions if type(s) is not dict and s.backend.name == i) for i in cfg.get('llm_nos', [])]
        is_native = lambda s: 'Native' in s.__class__.__name__
        groups = {is_native(s) for s in self._sessions}
        assert len(groups) == 1, f"MixinSession: sessions must be in same group (Native or non-Native), got {[type(s).__name__ for s in self._sessions]}"
        self.name = '|'.join(s.name for s in self._sessions)
        import copy; self._sessions = [copy.copy(s) for s in self._sessions]
        for s in self._sessions: s.max_retries = 0
        self._orig_raw_asks = [s.raw_ask for s in self._sessions]
        self._sessions[0].raw_ask = self._raw_ask
        self.model = getattr(self._sessions[0], 'model', None)
        self._cur_idx, self._switched_at = 0, 0.0
    def __getattr__(self, name): return getattr(self._sessions[0], name)
    _BROADCAST_ATTRS = frozenset({'system', 'tools', 'temperature', 'max_tokens', 'reasoning_effort', 'history'})
    def __setattr__(self, name, value):
        if name in self._BROADCAST_ATTRS:
            for s in self._sessions:
                v = openai_tools_to_claude(value) if name == 'tools' and type(s) is NativeClaudeSession else value
                setattr(s, name, v)
        else: object.__setattr__(self, name, value)
    @property
    def primary(self): return self._sessions[0]
    def _pick(self):
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec: self._cur_idx = 0
        return self._cur_idx
    def _raw_ask(self, *args, **kwargs):
        base, n = self._pick(), len(self._sessions)
        test_error = lambda x: isinstance(x, str) and x.lstrip().startswith(('!!!Error:', '[Error:'))
        for attempt in range(self._retries + 1):
            idx = (base + attempt) % n
            gen = self._orig_raw_asks[idx](*args, **kwargs)
            print(f'[MixinSession] Using session ({self._sessions[idx].name})')
            last_chunk, return_val, yielded = None, [], False
            try:
                while True:
                    chunk = next(gen); last_chunk = chunk
                    if not yielded and test_error(chunk): continue
                    yield chunk; yielded = True
            except StopIteration as e: return_val = e.value or []
            is_err = test_error(last_chunk)
            if not is_err:
                if attempt > 0: self._cur_idx = idx; self._switched_at = time.time()
                elif isinstance(last_chunk, str) and '[!!! 流异常中断' in last_chunk and n > 1:
                    self._cur_idx = (idx + 1) % n; self._switched_at = time.time()
                    print(f'[MixinSession] Partial failure, next call → s{self._cur_idx} ({self._sessions[self._cur_idx].name})')
                return return_val
            if attempt >= self._retries:
                yield last_chunk; return return_val
            nxt = (base + attempt + 1) % n
            if nxt == base:  # full round failed, delay before next
                rnd = (attempt + 1) // n
                delay = min(30, self._base_delay * (1.5 ** rnd))
                print(f'[MixinSession] {last_chunk[:80]}, round {rnd} exhausted, retry in {delay:.1f}s')
                time.sleep(delay)
            else: print(f'[MixinSession] {last_chunk[:80]}, retry {attempt+1}/{self._retries} (s{idx}→s{nxt})')
