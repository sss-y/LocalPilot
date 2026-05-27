"""Tool schema loading utilities."""

from __future__ import annotations

import json
from pathlib import Path

from config.paths import TOOLS_SCHEMA_CN_PATH, TOOLS_SCHEMA_PATH


def load_tool_schema(path: str | Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_tools_schema(lang: str | None = None) -> list[dict]:
    schema_path = TOOLS_SCHEMA_CN_PATH if lang == "cn" else TOOLS_SCHEMA_PATH
    return load_tool_schema(schema_path)


TOOLS_SCHEMA = load_tool_schema(TOOLS_SCHEMA_PATH)
TOOLS_SCHEMA_CN = load_tool_schema(TOOLS_SCHEMA_CN_PATH)
