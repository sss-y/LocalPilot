"""Memory-related helpers extracted from ga.py."""

from __future__ import annotations

import json
import os
from datetime import datetime

from config.paths import (
    GLOBAL_MEMORY_INSIGHT_PATH,
    MEMORY_ACCESS_STATS_PATH,
    MEMORY_MANAGEMENT_SOP_PATH,
    TEMP_DIR,
    insight_structure_path,
)
from .file_tools import file_read


def get_global_memory() -> str:
    """Assemble the global memory prompt when supporting files exist."""
    prompt = "\n"
    try:
        suffix = "_en" if os.environ.get("GA_LANG", "") == "en" else ""
        insight = GLOBAL_MEMORY_INSIGHT_PATH.read_text(encoding="utf-8", errors="replace")
        structure = insight_structure_path(suffix).read_text(encoding="utf-8")
        prompt += f"cwd = {TEMP_DIR} (./)\n"
        prompt += "\n[Memory] (../memory)\n"
        prompt += structure + "\n../memory/global_mem_insight.txt:\n"
        prompt += insight + "\n"
    except FileNotFoundError:
        pass
    return prompt

# 记录对memory文件的访问,统计访问次数和最后访问日期,保存在memory/file_access_stats.json中,用于分析哪些记忆文件被频繁访问,哪些可能过时未被使用
def log_memory_access(path: str) -> None:
    """Track reads/writes for memory files."""
    if "memory" not in path:
        return
    try:
        stats = json.loads(MEMORY_ACCESS_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        stats = {}
    file_name = os.path.basename(path)
    stats[file_name] = {
        "count": stats.get(file_name, {}).get("count", 0) + 1,
        "last": datetime.now().strftime("%Y-%m-%d"),
    }
    MEMORY_ACCESS_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_ACCESS_STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")


def do_update_working_checkpoint(
    working: dict,
    args: dict | None = None,
) -> dict:
    """Update short-term working memory."""
    args = args or {}
    if "key_info" in args:
        working["key_info"] = args.get("key_info", "")
    if "related_sop" in args:
        working["related_sop"] = args.get("related_sop", "")
    working["passed_sessions"] = 0
    return {"result": "working key_info updated"}


def do_start_long_term_update() -> tuple[str, str]:
    """Return the long-term memory settlement prompt and current SOP snapshot."""
    prompt = (
        "### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，请提取最近一次任务中"
        "【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。\n"
        "本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。\n"
        "**如果没有经验证的，未来能用上的信息，忽略本次调用！**\n"
        "**只能提取行动验证成功的信息**：\n"
        "- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1\n"
        "- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP（只记你被坑得多次重试的核心要点）\n"
        "**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节、只是做了但没有验证的信息\n"
        "**操作**：严格遵循提供的L0的记忆更新SOP。先 `file_read` 看现有 → 判断类型 → 最小化更新 → 无新内容跳过，保证对记忆库最小局部修改。\n\n"
        + get_global_memory()
    )
    if MEMORY_MANAGEMENT_SOP_PATH.exists():
        result = "自动读取L0内容：\n" + file_read(str(MEMORY_MANAGEMENT_SOP_PATH), show_linenos=False)
    else:
        result = "Memory Management SOP not found. Do not update memory."
    return prompt, result
