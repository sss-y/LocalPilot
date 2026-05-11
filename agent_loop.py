import json, re, os

def json_default(obj):
    return list(obj) if isinstance(obj, set) else str(obj)

def exhaust(g):
    try: 
        while True: next(g)
    except StopIteration as e: return e.value

def get_pretty_json(data):
    if isinstance(data, dict) and "script" in data:
        data = data.copy(); data["script"] = data["script"].replace("; ", ";\n  ")
    return json.dumps(data, indent=2, ensure_ascii=False).replace('\\n', '\n')

def agent_runner_loop(client, system_prompt, user_input, handler, tools_schema, max_turns=40, verbose=True, initial_user_content=None):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input}
    ]

    turn = 0;  handler.max_turns = max_turns
    # 对于一个问题,开启最大轮数内的循环处理
    # 退出标准:工具调用结果指示退出、没有新的prompt、达到最大轮数限制、或者通过钩子函数指示退出。
    while turn < handler.max_turns:

        turn += 1; turnstr = f'LLM Running (Turn {turn}) ...'
        if handler.parent.task_dir: turnstr = f'Turn {turn} ...'
        if verbose: turnstr = f'**{turnstr}**'
        yield f"\n\n{turnstr}\n\n"

        if turn%10 == 0: client.last_tools = ''  # 每10轮重置一次工具描述，避免上下文过大导致的模型性能下降

        response_gen = client.chat(messages=messages, tools=tools_schema)
        # ? verbose模式下，response_gen是一个生成器，yield from response_gen可以边生成边输出；
        # 非verbose模式下，将回复做上下文压缩,不展示全部的内容,而是将超过窗口的记录,拼接nlines....
        if verbose:
            response = yield from response_gen
            yield '\n\n'
        else:
            response = exhaust(response_gen)
            cleaned = _clean_content(response.content)
            if cleaned: yield cleaned + '\n'

        # tool加载
        if not response.tool_calls: tool_calls = [{'tool_name': 'no_tool', 'args': {}}]
        else: tool_calls = [{'tool_name': tc.function.name, 'args': json.loads(tc.function.arguments), 'id': tc.id}
                          for tc in response.tool_calls]
       
        tool_results = []; next_prompts = set(); exit_reason = {}
        # 调用的多个工具会依次处理，每个工具的调用结果会影响后续的流程控制（如是否继续当前任务、是否退出、是否进入下一个任务等）。
        # 工具调用结果的处理逻辑：每个工具调用后都会得到一个StepOutcome，根据这个结果决定是否继续当前任务、退出还是进入下一个任务。
        for ii, tc in enumerate(tool_calls):
            tool_name, args, tid = tc['tool_name'], tc['args'], tc.get('id', '')
            if tool_name == 'no_tool': pass
            else: 
                if verbose: yield f"🛠️ Tool: `{tool_name}`  📥 args:\n````text\n{get_pretty_json(args)}\n````\n"
                else: yield f"🛠️ {tool_name}({_compact_tool_args(tool_name, args)})\n\n\n"
            handler.current_turn = turn
            gen = handler.dispatch(tool_name, args, response, index=ii)
            # 如果是verbose模式，工具执行的过程和结果都会被逐步输出；如果不是verbose模式，则直接执行工具并获取最终结果，不展示中间过程。
            try:
                v = next(gen)
                def proxy(): yield v; return (yield from gen)
                if verbose: yield '`````\n'
                outcome = (yield from proxy()) if verbose else exhaust(proxy())
                if verbose: yield '`````\n'
            except StopIteration as e: outcome = e.value
            
            if outcome.should_exit: 
                exit_reason = {'result': 'EXITED', 'data': outcome.data}; break
            if not outcome.next_prompt: 
                exit_reason = {'result': 'CURRENT_TASK_DONE', 'data': outcome.data}; break
            if outcome.next_prompt.startswith('未知工具'): client.last_tools = ''
            if outcome.data is not None and tool_name != 'no_tool': 
                datastr = json.dumps(outcome.data, ensure_ascii=False, default=json_default) if type(outcome.data) in [dict, list] else str(outcome.data) 
                tool_results.append({'tool_use_id': tid, 'content': datastr})
            next_prompts.add(outcome.next_prompt)
        
        # 如果无新的prompt或工具调用结果指示退出，则结束当前任务的循环；
        # 否则将新的prompt加入消息列表，继续下一轮对话。    
        if len(next_prompts) == 0 or exit_reason:
            # todo 留存设置执行reflect 模式下的sop注入的done_hook中的下一个任务,能够自主执行,直到任务结束
            if len(handler._done_hooks) == 0 or exit_reason.get('result', '') == 'EXITED': break
            next_prompts.add(handler._done_hooks.pop(0))
        
        next_prompt = handler.turn_end_callback(response, tool_calls, tool_results, turn, '\n'.join(next_prompts), exit_reason)
        messages = [{"role": "user", "content": next_prompt, "tool_results": tool_results}]   # just new message, history is kept in *Session
    
    # 超过最大轮数限制后，如果没有其他退出原因，则默认以'MAX_TURNS_EXCEEDED'作为退出原因结束循环。
    if exit_reason: handler.turn_end_callback(response, tool_calls, tool_results, turn, '', exit_reason)
    return exit_reason or {'result': 'MAX_TURNS_EXCEEDED'}

def _clean_content(text):
    if not text: return ''
    def _shrink_code(m):
        lines = m.group(0).split('\n')
        lang = lines[0].replace('```','').strip()
        body = [l for l in lines[1:-1] if l.strip()]
        if len(body) <= 6: return m.group(0)
        preview = '\n'.join(body[:5])
        return f'```{lang}\n{preview}\n  ... ({len(body)} lines)\n```'
    text = re.sub(r'```[\s\S]*?```', _shrink_code, text)
    for p in [r'<file_content>[\s\S]*?</file_content>', r'<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>', r'(\r?\n){3,}']:
        text = re.sub(p, '\n\n' if '\\n' in p else '', text)
    return text.strip()

def _compact_tool_args(name, args):
    a = {k: v for k, v in args.items() if k != '_index'}
    for k in ('path',): 
        if k in a: a[k] = os.path.basename(a[k])
    if name == 'update_working_checkpoint': s = a.get('key_info', ''); return (s[:60]+'...') if len(s)>60 else s
    if name == 'ask_user':
        q = str(a.get('question', ''))
        cs = a.get('candidates') or []
        if cs: q += '\ncandidates:\n' + '\n'.join(f'- {c}' for c in cs)
        return q
    s = json.dumps(a, ensure_ascii=False); return (s[:120]+'...') if len(s)>120 else s
