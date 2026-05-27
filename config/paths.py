"""Stable path anchors for the agent package."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / "agent"
TOOLS_DIR = PROJECT_ROOT / "tools"
ASSETS_DIR = PROJECT_ROOT / "assets"
MEMORY_DIR = PROJECT_ROOT / "memory"
TEMP_DIR = PROJECT_ROOT / "temp"
SCHE_TASKS_DIR = PROJECT_ROOT / "sche_tasks"
SCHE_TASKS_DONE_DIR = SCHE_TASKS_DIR / "done"
SCHEDULER_LOG_PATH = SCHE_TASKS_DIR / "scheduler.log"
REFLECT_LOG_DIR = TEMP_DIR / "reflect_logs"
MODEL_RESPONSES_DIR = TEMP_DIR / "model_responses"
L4_RAW_SESSIONS_DIR = MEMORY_DIR / "L4_raw_sessions"
L4_COMPRESSOR_PATH = L4_RAW_SESSIONS_DIR / "compress_session.py"
TOOLS_SCHEMA_PATH = TOOLS_DIR / "tools_schema.json"
TOOLS_SCHEMA_CN_PATH = TOOLS_DIR / "tools_schema_cn.json"
GLOBAL_MEMORY_PATH = MEMORY_DIR / "global_mem.txt"
GLOBAL_MEMORY_INSIGHT_PATH = MEMORY_DIR / "global_mem_insight.txt"
MEMORY_ACCESS_STATS_PATH = MEMORY_DIR / "file_access_stats.json"
MEMORY_MANAGEMENT_SOP_PATH = MEMORY_DIR / "memory_management_sop.md"


def task_dir(name: str) -> Path:
    return TEMP_DIR / name


def insight_structure_path(lang_suffix: str = "") -> Path:
    return ASSETS_DIR / f"insight_fixed_structure{lang_suffix}.txt"
