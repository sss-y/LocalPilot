import os, sys, threading, queue, time, json, re, random, locale
from pathlib import Path
# 非重点,但是涉及到输出乱码和路径问题,所以放在最前面
os.environ.setdefault('GA_LANG', 'zh' if any(k in (locale.getlocale()[0] or '').lower() for k in ('zh', 'chinese')) else 'en')
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(errors='replace')
# 添加上级目录到sys.path以便导入同级模块和包内模块
# 将项目根路径添加到sys.path
_PROJECT_ROOT_FOR_IMPORT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT_FOR_IMPORT not in sys.path:
    sys.path.append(_PROJECT_ROOT_FOR_IMPORT)

from core.client import NativeToolClient, ToolClient
from core.config import reload_mykeys
from core.session import ClaudeSession, LLMSession, MixinSession, NativeClaudeSession, NativeOAISession

from agent.agent_loop import agent_runner_loop
from config.paths import ASSETS_DIR, MEMORY_DIR, PROJECT_ROOT, REFLECT_LOG_DIR, TEMP_DIR, TOOLS_DIR, task_dir
from tools import AgentHandler, smart_format, get_global_memory, format_error, consume_file

# 项目根目录
script_dir = str(PROJECT_ROOT)
def load_tool_schema(suffix=''):
    global TOOLS_SCHEMA
    with open(TOOLS_DIR / f'tools_schema{suffix}.json', 'r', encoding='utf-8') as f:
        TS = f.read()
    # Windows用户的使用powershell和Linux/Mac用户的bash工具
    TOOLS_SCHEMA = json.loads(TS if os.name == 'nt' else TS.replace('powershell', 'bash'))
load_tool_schema()
# 将memory配置加载,并保证不存在的时候正常创建,
lang_suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
mem_dir = str(MEMORY_DIR)
if not os.path.exists(mem_dir): os.makedirs(mem_dir)
mem_txt = str(MEMORY_DIR / 'global_mem.txt')
if not os.path.exists(mem_txt): open(mem_txt, 'w', encoding='utf-8').write('# [Global Memory - L2]\n')
mem_insight = str(MEMORY_DIR / 'global_mem_insight.txt')
if not os.path.exists(mem_insight):
    t = ASSETS_DIR / f'global_mem_insight_template{lang_suffix}.txt'
    open(mem_insight, 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')

def get_system_prompt():
    with open(ASSETS_DIR / f'sys_prompt{lang_suffix}.txt', 'r', encoding='utf-8') as f: prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt

class MyAgent:
    def __init__(self):
        os.makedirs(TEMP_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.task_dir = None # 对应task模式
        self.history = []
        self.task_queue = queue.Queue() 
        self.is_running = False 
        self.stop_sig = False
        self.llm_no = 0
        self.inc_out = False
        self.handler = None
        self.verbose = True
        self.load_llm_sessions()
    # 如果mykey有变动,将history迁移
    def load_llm_sessions(self):
        mykeys, changed = reload_mykeys()
        if not changed and hasattr(self, 'llmclients'): return
        try: oldhistory = self.llmclient.backend.history
        except: oldhistory = None
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ['api', 'config', 'cookie']): continue
            try:
                if 'native' in k and 'claude' in k: llm_sessions += [NativeToolClient(NativeClaudeSession(cfg=cfg))]
                elif 'native' in k and 'oai' in k: llm_sessions += [NativeToolClient(NativeOAISession(cfg=cfg))]
                elif 'claude' in k: llm_sessions += [ToolClient(ClaudeSession(cfg=cfg))]
                elif 'oai' in k: llm_sessions += [ToolClient(LLMSession(cfg=cfg))]
                elif 'mixin' in k: llm_sessions += [{'mixin_cfg': cfg}]
            except: pass
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and 'mixin_cfg' in s:
                try:
                    mixin = MixinSession(llm_sessions, s['mixin_cfg'])
                    if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)): llm_sessions[i] = NativeToolClient(mixin)
                    else: llm_sessions[i] = ToolClient(mixin)
                except Exception as e: print(f'\n\n\n[ERROR] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}!!!\n\n')
        # 设置:llm_clients和当前使用的llmclient,并迁移历史记录
        self.llmclients = llm_sessions
        self.llmclient = self.llmclients[self.llm_no%len(self.llmclients)]
        if oldhistory: self.llmclient.backend.history = oldhistory
    # 配置llmclient为第n个,默认切换到下一个,并迁移历史记录;如果是mixin,根据当前模型加载对应工具配置
    def next_llm(self, n=-1):
        self.load_llm_sessions()
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        lastc = self.llmclient
        self.llmclient = self.llmclients[self.llm_no]
        try: self.llmclient.backend.history = lastc.backend.history
        except: raise Exception('[ERROR] BAD Mixin config: Check your mykey.py')
        self.llmclient.last_tools = ''
        name = self.get_llm_name(model=True)
        if 'glm' in name or 'minimax' in name or 'kimi' in name: load_tool_schema('_cn')
        else: load_tool_schema()
    def list_llms(self): 
        self.load_llm_sessions()
        return [(i, self.get_llm_name(b), i == self.llm_no) for i, b in enumerate(self.llmclients)]
    def get_llm_name(self, b=None, model=False):
        b = self.llmclient if b is None else b
        if isinstance(b, dict): return 'BADCONFIG_MIXIN'
        if model: return b.backend.model.lower()
        return f"{type(b.backend).__name__}/{b.backend.name}"

# 打断当前任务的执行,设置停止信号,并通知handler(如果存在)也设置停止信号以便及时响应
    def abort(self):
        if not self.is_running: return
        print('Abort current task...')
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

# 支持以"/"开头的特殊命令,如/session.{key}={value}设置会话属性,/resume恢复最近会话记录等,处理完后返回新的查询字符串或None表示命令已处理无需继续
    # i know it is dangerous, but raw_query is dangerous enough it doesn't enlarge
    def _handle_slash_cmd(self, raw_query, display_queue):
        """处理以斜杠开头的特殊命令。
        
        支持的命令：
        - /session.{key}={value}: 设置LLM会话后端的属性，支持JSON值或文件路径
        - /resume: 恢复最近的会话记录（返回指令字符串）
        
        Args:
            raw_query: 原始查询字符串，可能包含斜杠命令
            display_queue: 用于输出提示消息的队列
            
        Returns:
            处理后的查询字符串，或None表示命令已处理完毕
        """
        if not raw_query.startswith('/'): return raw_query
        if _sm := re.match(r'/session\.(\w+)=(.*)', raw_query.strip()):
            k, v = _sm.group(1), _sm.group(2)
            vfile = TEMP_DIR / v
            if os.path.isfile(vfile): v = open(vfile, encoding='utf-8').read().strip()
            try: v = json.loads(v)  # cover number parsing
            except (json.JSONDecodeError, ValueError): pass
            setattr(self.llmclient.backend, k, v)
            display_queue.put({'done': smart_format(f"✅ session.{k} = {repr(v)}", max_str_len=500), 'source': 'system'})
            return None
        if raw_query.strip() == '/resume':
            return r'扫temp/model_responses/下时间最近的10个文件(除本PID)，读取每个文件content后先replace("\\n","\n").replace("\\r","\r")统一为真换行，再用re.findall(r"<history>\n\[(?:USER|Agent)\].*?</history>", content, re.DOTALL)提取，取每文件最后一个匹配作为该会话内容，按mtime倒序，每个用一句话总结聊了什么让我选择；选定后再简单读该文件末尾作为聊天基础'
        return raw_query
    # 对task进行消费
    def run(self):
        while True:
            task = self.task_queue.get()
            raw_query, source, images, display_queue = task["query"], task["source"], task.get("images") or [], task["output"]
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                self.task_queue.task_done(); continue
            self.is_running = True
            # 截断query过长部分,并替换掉换行以免显示问题,同时记录历史
            rquery = smart_format(raw_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")
            # session中对每次调用:指定行动规范:summary和记录长期记忆的落盘
            sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, 'extra_sys_prompt', '')
            handler = AgentHandler(self, self.history, str(TEMP_DIR))
            
            # key_info保存重要的长期工作记忆结构化的信息->通过工具:update_key_info进行注入,由llm调用;通常使用在plan模式下的sop中注入
            if self.handler and 'key_info' in self.handler.working: 
                ki = re.sub(r'\n\[SYSTEM\] 此为.*?工作记忆[。\n]*', '', self.handler.working['key_info'])  # 去旧
                handler.working['key_info'] = ki
                handler.working['passed_sessions'] = ps = self.handler.working.get('passed_sessions', 0) + 1
                if ps > 0: handler.working['key_info'] += f'\n[SYSTEM] 此为 {ps} 个对话前设置的key_info，若已在新任务，先更新或清除工作记忆。\n'
            self.handler = handler

            # although new handler, the **full** history is in llmclient, so it is full history!
            gen = agent_runner_loop(self.llmclient, sys_prompt, raw_query, 
                                handler, TOOLS_SCHEMA, max_turns=70, verbose=self.verbose)
            # try-catch:
            try:
                full_resp = ""; last_pos = 0
                for chunk in gen:
                    # 先验证task模式下的停止信号,再验证交互模式下的
                    if consume_file(self.task_dir, '_stop'): self.abort() 
                    if self.stop_sig: break

                    full_resp += chunk
                    # 50字符或以上才更新一次显示，或者遇到LLM Running提示（可能是工具调用前的提示）
                    # 如果inc_out为True则每次都更新显示未完成部分,否则直接显示全部的内容,true的时候对应流失输出,false对应task模式下的最后输出
                    if len(full_resp) - last_pos > 50 or 'LLM Running' in chunk:
                        display_queue.put({'next': full_resp[last_pos:] if self.inc_out else full_resp, 'source': source})
                        last_pos = len(full_resp)
                if self.inc_out and last_pos < len(full_resp): display_queue.put({'next': full_resp[last_pos:], 'source': source})

                if '</summary>' in full_resp: full_resp = full_resp.replace('</summary>', '</summary>\n\n')
                if '</file_content>' in full_resp: full_resp = re.sub(r'<file_content>\s*(.*?)\s*</file_content>', r'\n````\n<file_content>\n\1\n</file_content>\n````', full_resp, flags=re.DOTALL)    

                display_queue.put({'done': full_resp, 'source': source})
                self.history = handler.history_info# 将handler里记录的历史更新到agent的历史属性,以便后续任务使用(ga.py中)
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                display_queue.put({'done': full_resp + f'\n```\n{format_error(e)}\n```', 'source': source})
            finally:
                if self.stop_sig:
                    print('User aborted the task.')
                    #with self.task_queue.mutex: self.task_queue.queue.clear()
                self.is_running = self.stop_sig = False
                self.task_queue.task_done()
                # 设置handler为停止,一个task对应一个handler,这里在结束任务之后,开启新的任务;,
                if self.handler is not None: self.handler.code_stop_signal.append(1)


# 主程序入口，解析命令行参数，支持一次性任务模式（通过文件IO）和反射模式（加载监控脚本），并启动agent的运行循环
if __name__ == '__main__':
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', metavar='IODIR', help='一次性任务模式(文件IO)')
    parser.add_argument('--reflect', metavar='SCRIPT', help='反射模式：加载监控脚本，check()触发时发任务')
    parser.add_argument('--input', help='prompt')
    parser.add_argument('--llm_no', type=int, default=0)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--bg', action='store_true', help='popen, print PID, exit')
    args = parser.parse_args()

    if args.bg:
        import subprocess, platform
        cmd = [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:] if a != '--bg']
        # 创建tas
        d = task_dir(args.task); os.makedirs(d, exist_ok=True)
        p = subprocess.Popen(cmd, cwd=script_dir,
            creationflags=0x08000000 if platform.system() == 'Windows' else 0,
            stdout=open(d / 'stdout.log', 'w', encoding='utf-8'),
            stderr=open(d / 'stderr.log', 'w', encoding='utf-8'))
        print(p.pid); sys.exit(0)

    agent = MyAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    # 以守护线程的方式运行agent.run，这样主线程可以继续执行其他代码（如处理命令行输入或监控文件变化），而不会被agent.run的循环阻塞
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        # 作为一次性任务模式的文件目录，基于文件IO与外部交互，监控指定目录下的输入输出文件，直到完成或超时
        agent.task_dir = d = str(task_dir(args.task)); 
        # 计数器
        nround = ''
        infile = os.path.join(d, 'input.txt')
        if args.input:
            os.makedirs(d, exist_ok=True)
            # 删除之前的输出文件
            import glob; [os.remove(f) for f in glob.glob(os.path.join(d, 'output*.txt'))]
            # 把通过 python agentmain.py --task my_task --input "你的提示词" 命令行传入的内容写成文件
            with open(infile, 'w', encoding='utf-8') as f: f.write(args.input)
        # 读取infile文件中的内容
        with open(infile, encoding='utf-8') as f: raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            while 'done' not in (item := dq.get(timeout=120)): 
                if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果
                    # 将中间结果写入到当前轮次的文件夹中
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: 
                        f.write(item.get('next', ''))
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: 
                f.write(item['done'] + '\n\n[ROUND END]\n')
            # 将当前轮次的停止信号删除;(stop信号文件,是由sop文件通过model调用工具生成的)
            consume_file(d, '_stop')  # 已经成功停下来了，避免打断下次reply
            for _ in range(300):  # 等reply.txt，10分钟超时,reply.txt，用它作为下一轮输入；
                time.sleep(2)
                # 等待reply文件,如果无内容,就break掉
                if (raw := consume_file(d, 'reply.txt')): break
            else: break
            nround = nround + 1 if isinstance(nround, int) else 1
    elif args.reflect:
        # 加载指定的反射脚本
        import importlib.util
        spec = importlib.util.spec_from_file_location('reflect_script', args.reflect)
        # exec_module(mod) 会把 args.reflect 这个文件里的代码真正执行一遍，并把其中定义的变量、函数、类都加载进 mod。
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        _mt = os.path.getmtime(args.reflect)
        print(f'[Reflect] loaded {args.reflect}')

        while True:
            # 如果脚本被修改,重新加载和执行
            if os.path.getmtime(args.reflect) != _mt:
                try: spec.loader.exec_module(mod); _mt = os.path.getmtime(args.reflect); print('[Reflect] reloaded')
                except Exception as e: print(f'[Reflect] reload error: {e}')
            time.sleep(getattr(mod, 'INTERVAL', 5))# 设置轮训检查的时间间隔,默认5s

            # 对应:reflect文件夹下的scheduler里的check函数和autonomouse里的check函数
            try: task = mod.check()
            except Exception as e: 
                print(f'[Reflect] check() error: {e}'); continue
            if task is None: continue
            print(f'[Reflect] triggered: {task[:80]}')
            dq = agent.put_task(task, source='reflect')
            try:
                while 'done' not in (item := dq.get(timeout=120)): pass
                result = item['done']
                print(result)
            except Exception as e:
                if getattr(mod, 'ONCE', False): raise
                print(f'[Reflect] drain error: {e}'); result = f'[ERROR] {e}'
            # 将结果写入到reflect_logs文件夹下以reflect脚本命名的日志文件中,并调用on_done回调(如果存在),最后根据ONCE决定是否退出
            log_dir = str(REFLECT_LOG_DIR); os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f'{script_name}_{datetime.now():%Y-%m-%d}.log'), 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            # 如果反射脚本里定义了on_done函数,就调用它并传入结果;如果定义了ONCE=True,就执行完一次任务后退出,否则继续监控和执行任务
            if (on_done := getattr(mod, 'on_done', None)):
                try: on_done(result)
                except Exception as e: print(f'[Reflect] on_done error: {e}')
            if getattr(mod, 'ONCE', False): print('[Reflect] ONCE=True, exiting.'); break
    else:
        try: import readline
        except Exception: pass
        agent.inc_out = True
        while True:
            q = input('> ').strip()
            if not q: continue
            try:
                dq = agent.put_task(q, source='user')
                while True:
                    item = dq.get()
                    if 'next' in item: print(item['next'], end='', flush=True)
                    if 'done' in item: print(); break
            except KeyboardInterrupt:
                agent.abort()
                print('\n[Interrupted]')
