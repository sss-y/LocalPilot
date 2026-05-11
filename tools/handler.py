"""Handler implementations for tool dispatch."""

from __future__ import annotations

import json
import os
import re

from .base import BaseHandler, StepOutcome
from .code_tools import code_run
from .file_tools import consume_file, expand_file_refs, file_patch, file_read
from .formatter import smart_format
from .human_tools import ask_user
from .memory_tools import (
    do_start_long_term_update as build_long_term_update,
    do_update_working_checkpoint as update_working_checkpoint_data,
    get_global_memory,
    log_memory_access,
)
from .plan_tools import (
    _check_plan_completion as check_plan_completion,
    _exit_plan_mode as exit_plan_mode,
    _in_plan_mode as in_plan_mode,
    enter_plan_mode as set_plan_mode,
)
from .web_tools import web_execute_js, web_scan

def json_default(obj):
    return list(obj) if isinstance(obj, set) else str(obj)


class GenericAgentHandler(BaseHandler):
    """Concrete tool handler used by the agent loop."""

    def __init__(self, parent, last_history=None, cwd="./temp"):
        self.parent = parent
        self.working = {}
        self.cwd = cwd
        self.current_turn = 0
        self.history_info = last_history if last_history else []
        self.code_stop_signal = []
        self._done_hooks = []
        self.max_turns = 40

    def _get_abs_path(self, path):
        if not path:
            return ""
        return os.path.abspath(os.path.join(self.cwd, path))

    def _extract_code_block(self, response, code_type):
        code_type = {
            "python": "python|py",
            "powershell": "powershell|ps1|pwsh",
            "bash": "bash|sh|shell",
            "javascript": "javascript|js",
        }.get(code_type, re.escape(code_type))
        content = getattr(response, "content", "") or ""
        matches = re.findall(rf"```(?:{code_type})\n(.*?)\n```", content, re.DOTALL)
        return matches[-1].strip() if matches else None

    def do_code_run(self, args, response):
        """Execute code or shell snippets."""
        code_type = args.get("type", "python")
        code = args.get("code") or args.get("script")
        if not code:
            code = self._extract_code_block(response, code_type)
            if not code:
                return StepOutcome(
                    "[Error] Code missing. Must use reply code block or 'script' arg.",
                    next_prompt="\n",
                )
        timeout = args.get("timeout", 60)
        raw_path = os.path.join(self.cwd, args.get("cwd", "./"))
        cwd = os.path.normpath(os.path.abspath(raw_path))
        code_cwd = os.path.normpath(self.cwd)
        if code_type == "python" and args.get("inline_eval"):
            namespace = {"handler": self, "parent": self.parent}
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                try:
                    try:
                        result = repr(eval(code, namespace))
                    except SyntaxError:
                        exec(code, namespace)
                        result = namespace.get("_r", "OK")
                except Exception as exc:
                    result = f"Error: {exc}"
            finally:
                os.chdir(old_cwd)
        else:
            result = yield from code_run(
                code,
                code_type,
                timeout,
                cwd,
                code_cwd=code_cwd,
                stop_signal=self.code_stop_signal,
            )
        next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)

    def do_ask_user(self, args, response):
        question = args.get("question", "请提供输入：")
        candidates = args.get("candidates", [])
        result = ask_user(question, candidates)
        yield "Waiting for your answer ...\n"
        return StepOutcome(result, next_prompt="", should_exit=True)

    def do_web_scan(self, args, response):
        tabs_only = args.get("tabs_only", False)
        switch_tab_id = args.get("switch_tab_id", None)
        text_only = args.get("text_only", False)
        result = web_scan(
            tabs_only=tabs_only,
            switch_tab_id=switch_tab_id,
            text_only=text_only,
        )
        content = result.pop("content", None)
        yield f"[Info] {str(result)}\n"
        if content:
            result = json.dumps(result, ensure_ascii=False, default=json_default) + f"\n```html\n{content}\n```"
        return StepOutcome(result, next_prompt="\n")

    def do_web_execute_js(self, args, response):
        script = args.get("script", "") or self._extract_code_block(response, "javascript")
        if not script:
            return StepOutcome(
                "[Error] Script missing. Use ```javascript block or 'script' arg.",
                next_prompt="\n",
            )
        abs_path = self._get_abs_path(script.strip())
        if os.path.isfile(abs_path):
            with open(abs_path, "r", encoding="utf-8") as handle:
                script = handle.read()
        save_to_file = args.get("save_to_file", "")
        switch_tab_id = args.get("switch_tab_id") or args.get("tab_id")
        no_monitor = args.get("no_monitor", False)
        result = web_execute_js(script, switch_tab_id=switch_tab_id, no_monitor=no_monitor)
        if save_to_file and "js_return" in result:
            content = str(result["js_return"] or "")
            abs_path = self._get_abs_path(save_to_file)
            result["js_return"] = smart_format(content, max_str_len=170)
            try:
                with open(abs_path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                result["js_return"] += f"\n\n[已保存完整内容到 {abs_path}]"
            except Exception:
                result["js_return"] += f"\n\n[保存失败，无法写入文件 {abs_path}]"
        show = smart_format(
            json.dumps(result, ensure_ascii=False, indent=2, default=json_default),
            max_str_len=300,
        )
        yield f"JS 执行结果:\n{show}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
        result = json.dumps(result, ensure_ascii=False, default=json_default)
        return StepOutcome(smart_format(result, max_str_len=8000), next_prompt=next_prompt)

    def do_file_patch(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        yield f"[Action] Patching file: {path}\n"
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        try:
            new_content = expand_file_refs(new_content, base_dir=self.cwd)
        except ValueError as exc:
            yield f"[Status] ❌ 引用展开失败: {exc}\n"
            return StepOutcome({"status": "error", "msg": str(exc)}, next_prompt="\n")
        result = file_patch(path, old_content, new_content)
        yield f"\n{str(result)}\n"
        next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
        return StepOutcome(result, next_prompt=next_prompt)

    def do_file_write(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        mode = args.get("mode", "overwrite")
        action_str = {"prepend": "Prepending to", "append": "Appending to"}.get(mode, "Overwriting")
        yield f"[Action] {action_str} file: {os.path.basename(path)}\n"

        def extract_robust_content(text):
            tags = re.findall(r"<file_content[^>]*>(.*?)</file_content>", text, re.DOTALL)
            if tags:
                return tags[-1].strip()
            blocks = re.findall(r"```[^\n]*\n([\s\S]*?)```", text)
            if blocks:
                return blocks[-1].strip()
            return None

        blocks = extract_robust_content(getattr(response, "content", "") or "")
        if not blocks:
            yield "[Status] ❌ 失败: 未在回复中找到<file_content>代码块内容\n"
            return StepOutcome(
                {
                    "status": "error",
                    "msg": "No content found. Put content inside <file_content>...</file_content> tags in your reply body before call file_write.",
                },
                next_prompt="\n",
            )
        try:
            new_content = expand_file_refs(blocks, base_dir=self.cwd)
            if mode == "prepend":
                old_content = ""
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as handle:
                        old_content = handle.read()
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(new_content + old_content)
            else:
                with open(path, "a" if mode == "append" else "w", encoding="utf-8") as handle:
                    handle.write(new_content)
            yield f"[Status] ✅ {mode.capitalize()} 成功 ({len(new_content)} bytes)\n"
            next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
            return StepOutcome({"status": "success", "writed_bytes": len(new_content)}, next_prompt=next_prompt)
        except Exception as exc:
            yield f"[Status] ❌ 写入异常: {exc}\n"
            return StepOutcome({"status": "error", "msg": str(exc)}, next_prompt="\n")

    def do_file_read(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        yield f"\n[Action] Reading file: {path}\n"
        start = args.get("start", 1)
        count = args.get("count", 200)
        keyword = args.get("keyword")
        show_linenos = args.get("show_linenos", True)
        result = file_read(path, start=start, keyword=keyword, count=count, show_linenos=show_linenos)
        if show_linenos and not result.startswith("Error:"):
            result = "由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n" + result
        if " ... [TRUNCATED]" in result:
            result += "\n\n（某些行被截断，如需完整内容可改用 code_run 读取）"
        result = smart_format(result, max_str_len=20000, omit_str="\n\n[omitted long content]\n\n")
        next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
        log_memory_access(path)
        if "memory" in path or "sop" in path:
            next_prompt += "\n[SYSTEM TIPS] 正在读取记忆或SOP文件，若决定按sop执行请提取sop中的关键点（特别是靠后的）update working memory."
        return StepOutcome(result, next_prompt=next_prompt)

    def _in_plan_mode(self):
        return in_plan_mode(self.working)

    def _exit_plan_mode(self):
        exit_plan_mode(self.working)

    def enter_plan_mode(self, plan_path):
        set_plan_mode(self.working, plan_path)
        self.max_turns = 100
        print(f"[Info] Entered plan mode with plan file: {plan_path}")
        return plan_path

    def _check_plan_completion(self):
        return check_plan_completion(self.working)

    def do_update_working_checkpoint(self, args, response):
        update_working_checkpoint_data(self.working, args)
        yield "[Info] Updated key_info and related_sop.\n"
        next_prompt = self._get_anchor_prompt(skip=args.get("_index", 0) > 0)
        return StepOutcome({"result": "working key_info updated"}, next_prompt=next_prompt)

    def do_no_tool(self, args, response):
        content = getattr(response, "content", "") or ""
        thinking = getattr(response, "thinking", "") or ""
        if not response or (not content.strip() and not thinking.strip()):
            self._empty_ct = getattr(self, "_empty_ct", 0) + 1
            if self._empty_ct >= 3:
                return StepOutcome({}, should_exit=True)
            yield "[Warn] LLM returned an empty response. Retrying...\n"
            return StepOutcome({}, next_prompt="[System] Blank response, regenerate and tooluse")
        if len(content) > 50 and ("[!!! 流异常中断" in content[-100:] or "!!!Error:" in content[-100:]):
            return StepOutcome({}, next_prompt="[System] Incomplete response. Regenerate and tooluse.")
        if "max_tokens !!!]" in content[-100:]:
            return StepOutcome({}, next_prompt="[System] max_tokens limit reached. Use multi small steps to do it.")

        if self._in_plan_mode() and any(keyword in content for keyword in ["任务完成", "全部完成", "已完成所有", "🏁"]):
            if "VERDICT" not in content and "[VERIFY]" not in content and "验证subagent" not in content:
                yield "[Warn] Plan模式完成声明拦截。\n"
                return StepOutcome(
                    {},
                    next_prompt="⛔ [验证拦截] 检测到你在plan模式下声称完成，但未执行[VERIFY]验证步骤。请先按plan_sop §四启动验证subagent，获得VERDICT后才能声称完成。",
                )

        code_block_pattern = r"```[a-zA-Z0-9_]*\n[\s\S]{50,}?```"
        blocks = re.findall(code_block_pattern, content)
        if len(blocks) == 1:
            match = re.search(code_block_pattern, content)
            after_block = content[match.end():]
            if not after_block.strip():
                residual = content.replace(match.group(0), "")
                residual = re.sub(r"<thinking>[\s\S]*?</thinking>", "", residual, flags=re.IGNORECASE)
                residual = re.sub(r"<summary>[\s\S]*?</summary>", "", residual, flags=re.IGNORECASE)
                clean_residual = re.sub(r"\s+", "", residual)
                if len(clean_residual) <= 30:
                    yield "[Info] Detected large code block without tool call and no extra natural language. Requesting clarification.\n"
                    next_prompt = (
                        "[System] 检测到你在上一轮回复中主要内容是较大代码块，且本轮未调用任何工具。\n"
                        "如果这些代码需要执行、写入文件或进一步分析，请重新组织回复并显式调用相应工具"
                        "（例如：code_run、file_write、file_patch 等）；\n"
                        "如果只是向用户展示或讲解代码片段，请在回复中补充自然语言说明，"
                        "并明确是否还需要额外的实际操作。"
                    )
                    return StepOutcome({}, next_prompt=next_prompt)

        if self._in_plan_mode():
            remaining = self._check_plan_completion()
            if remaining == 0:
                self._exit_plan_mode()
                yield "[Info] Plan完成：plan.md中0个[ ]残留，退出plan模式。\n"

        yield "[Info] Final response to user.\n"
        return StepOutcome(response, next_prompt=None)

    def do_start_long_term_update(self, args, response):
        prompt, result = build_long_term_update()
        yield "[Info] Start distilling good memory for long-term storage.\n"
        return StepOutcome(result, next_prompt=prompt)

    def _get_anchor_prompt(self, skip=False):
        if skip:
            return "\n"
        history_text = "\n".join(self.history_info[-40:])
        prompt = f"\n### [WORKING MEMORY]\n<history>\n{history_text}\n</history>"
        prompt += f"\nCurrent turn: {self.current_turn}\n"
        if self.working.get("key_info"):
            prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"
        if self.working.get("related_sop"):
            prompt += f"\n有不清晰的地方请再次读取{self.working.get('related_sop')}"
        if getattr(self.parent, "verbose", False):
            try:
                print(prompt)
            except Exception:
                pass
        return prompt

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        content = getattr(response, "content", "") or ""
        stripped = re.sub(r"```.*?```|<thinking>.*?</thinking>", "", content, flags=re.DOTALL)
        summary_match = re.search(r"<summary>(.*?)</summary>", stripped, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
        else:
            tool_call = tool_calls[0]
            tool_name, args = tool_call["tool_name"], tool_call["args"]
            clean_args = {key: value for key, value in args.items() if not key.startswith("_")}
            summary = f"调用工具{tool_name}, args: {clean_args}"
            if tool_name == "no_tool":
                summary = "直接回答了用户问题"
            next_prompt += "\n[DANGER] 你遗漏了<summary>，必须按协议一直在每次回复中用<summary>中输出极简单行摘要！"
        summary = smart_format(summary, max_str_len=100)
        self.history_info.append(f"[Agent] {summary}")
        if turn % 65 == 0 and "plan" not in str(self.working.get("related_sop")):
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。你必须总结情况进行ask_user，不允许继续重试。"
        elif turn % 7 == 0:
            next_prompt += (
                f"\n\n[DANGER] 已连续执行第 {turn} 轮。禁止无效重试。若无有效进展，必须切换策略："
                "1. 探测物理边界 2. 请求用户协助。如有需要，可调用 update_working_checkpoint 保存关键上下文。"
            )
        elif turn % 10 == 0:
            next_prompt += get_global_memory()

        plan_path = self._in_plan_mode()
        if plan_path and turn >= 10 and turn % 5 == 0:
            next_prompt = (
                f"[Plan Hint] 你正在计划模式。必须 file_read({plan_path}) 确认当前步骤，回复开头引用：📌 当前步骤：...\n\n"
                + next_prompt
            )
        if plan_path and turn >= 90:
            next_prompt += f"\n\n[DANGER] Plan模式已运行 {turn} 轮，已达上限。必须 ask_user 汇报进度并确认是否继续。"

        task_dir = getattr(self.parent, "task_dir", None)
        injected_key_info = consume_file(task_dir, "_keyinfo")
        injected_prompt = consume_file(task_dir, "_intervene")
        if injected_key_info:
            self.working["key_info"] = self.working.get("key_info", "") + f"\n[MASTER] {injected_key_info}"
        if injected_prompt:
            next_prompt += f"\n\n[MASTER] {injected_prompt}\n"
        for hook in getattr(self.parent, "_turn_end_hooks", {}).values():
            hook(locals())
        return next_prompt
