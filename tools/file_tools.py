"""File helpers extracted from ga.py."""

from __future__ import annotations

import collections
import difflib
import itertools
import os
import re
from pathlib import Path
from typing import Generator

_read_dirs: set[str] = set()

'''函数:展开形如{{file:path:start:end}}的文件内容
如果不包含,则直接返回原文本
'''
def expand_file_refs(text: str, base_dir: str | None = None) -> str:
    """Expand {{file:path:start:end}} references into actual file content."""
    pattern = r"\{\{file:(.+?):(\d+):(\d+)\}\}"

    def replacer(match: re.Match[str]) -> str:
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        abs_path = os.path.abspath(os.path.join(base_dir or ".", path))
        if not os.path.isfile(abs_path):
            raise ValueError(f"引用文件不存在: {abs_path}")
        with open(abs_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        if start < 1 or end > len(lines) or start > end:
            raise ValueError(f"行号越界: {abs_path} 共{len(lines)}行, 请求{start}-{end}")
        return "".join(lines[start - 1 : end])

    return re.sub(pattern, replacer, text)

'''函数:替换内容
1. 如果文件不存在,返回错误信息
2. 如果文件存在,但未找到old_content,返回错误信息
3. 如果找到多个old_content,返回错误信息
4. 如果old_content为空,返回错误信息
5. 如果成功替换,返回成功信息
'''
def file_patch(path: str, old_content: str, new_content: str) -> dict:
    """Replace a unique text block in a file."""
    abs_path = str(Path(path).resolve())
    try:
        if not os.path.exists(abs_path):
            return {"status": "error", "msg": "文件不存在"}
        with open(abs_path, "r", encoding="utf-8") as handle:
            full_text = handle.read()
        if not old_content:
            return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0:
            return {
                "status": "error",
                "msg": (
                    "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。"
                    "若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。"
                ),
            }
        if count > 1:
            return {
                "status": "error",
                "msg": (
                    f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。"
                    "建议：包含上下文行来增强特征，或分小段逐个修改。"
                ),
            }
        updated_text = full_text.replace(old_content, new_content)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def _scan_files(base: str, depth: int = 2) -> Generator[tuple[str, str], None, None]:
    try:
        for entry in os.scandir(base):
            if entry.is_file():
                yield (entry.name, entry.path)
            elif depth > 0 and entry.is_dir(follow_symlinks=False):
                yield from _scan_files(entry.path, depth - 1)
    except (PermissionError, OSError):
        return

'''函数:读取文件内容,支持返回行号,和关键词读取
1. 如果指定了关键词,返回关键词所在行以及前后各100行的内容,如果没有找到关键词,则返回指定行开始的内容
2. 如果文件不存在,尝试在前两级目录中寻找文件,选出相似度大于0.6的,并返回候选列表
3. 再返回内容之前进行过长截断和总行数统计;
    1. 截断:将每行的长度控制在100-8000之间,超过部分用... [TRUNCATED]替代;
    2. 统计:向后统计至多5000行
4. 最终返回:总行数统计+当前行数+提示信息+读取的内容:[FILE] {total_lines_str} lines"
                + (f" | PARTIAL showing {real_count}; assess need for more" if partial else "")
                + "\n"
'''
def file_read(
    path: str,
    start: int = 1,
    keyword: str | None = None,
    count: int = 200,
    show_linenos: bool = True,
) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            stream = ((i, line.rstrip("\r\n")) for i, line in enumerate(handle, 1))
            stream = itertools.dropwhile(lambda item: item[0] < start, stream)
            
            if keyword:
                before = collections.deque(maxlen=count // 3)
                for i, line in stream:
                    if keyword.lower() in line.lower():
                        res = list(before) + [(i, line)] + list(
                            itertools.islice(stream, count - len(before) - 1)
                        )
                        break
                    before.append((i, line))
                else:
                    return (
                        f"Keyword '{keyword}' not found after line {start}. "
                        f"Falling back to content from line {start}:\n\n"
                        + file_read(path, start, None, count, show_linenos)
                    )
            else:
                res = list(itertools.islice(stream, count))
            # 截断处理
            real_count = len(res)
            max_len = min(max(100, 256000 // max(real_count, 1)), 8000)
            tag = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (res[0][0] - 1 if res else start - 1) + real_count + remaining
            total_lines_str = f"{total_lines}+" if remaining >= 5000 else str(total_lines)
            partial = total_lines > real_count
            total_tag = (
                f"[FILE] {total_lines_str} lines"
                + (f" | PARTIAL showing {real_count}; assess need for more" if partial else "")
                + "\n"
            )
            res = [(i, line if len(line) <= max_len else line[:max_len] + tag) for i, line in res]
            result = "\n".join(f"{i}|{line}" if show_linenos else line for i, line in res)
            if show_linenos:
                result = total_tag + result
            elif partial:
                result += f"\n\n[FILE PARTIAL: showing {real_count}/{total_lines_str} lines; assess need for more]"
            _read_dirs.add(os.path.dirname(os.path.abspath(path)))
            return result
    except FileNotFoundError:
        msg = f"Error: File not found: {path}"
        # 尝试在传入的父目录中寻找
        try:
            target = os.path.basename(path)
            scan_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
            roots = [scan_root] + [item for item in _read_dirs if not item.startswith(scan_root)]
            candidates = list(
                itertools.islice((candidate for base in roots for candidate in _scan_files(base)), 2000)
            )
            top = sorted(
                [
                    (
                        difflib.SequenceMatcher(None, target.lower(), candidate[0].lower()).ratio(),
                        candidate,
                    )
                    for candidate in candidates[:2000]
                ],
                key=lambda item: -item[0],
            )[:5]
            top = [(score, candidate) for score, candidate in top if score > 0.3]
            if top:
                msg += "\n\nDid you mean:\n" + "\n".join(
                    f"  {candidate[1]}  ({score:.0%})" for score, candidate in top
                )
        # 如果发生异常,返回原始file not found消息,不影响主流程
        except Exception:
            pass
        return msg
    except Exception as exc:
        return f"Error: {exc}"


def consume_file(directory: str | None, file: str) -> str | None:
    """Read a file then delete it."""
    if directory and os.path.exists(os.path.join(directory, file)):
        abs_path = os.path.join(directory, file)
        with open(abs_path, encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        os.remove(abs_path)
        return content
    return None
