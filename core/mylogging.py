"""core.mylogging

职责：
- 为当前进程生成统一日志文件路径
- 记录 Prompt / Response / Usage

边界：
- 这里只负责落盘，不参与模型请求和协议解析
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from config.paths import MODEL_RESPONSES_DIR


class LLMLogger:
    def __init__(self, log_dir: str | os.PathLike[str] = MODEL_RESPONSES_DIR):
        self.log_dir = os.fspath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)

    def log_path(self) -> str:
        return os.path.join(
            self.log_dir,
            f"model_responses_{os.getpid()}.txt"
        )

    def write(self, label: str, content: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write(f"=== {label} === {ts}\n{content}\n\n")

    def record_usage(self, usage: Optional[Dict[str, Any]], source: str = "litellm") -> None:
        if not usage:
            return
        self.write("Usage", f"[{source}] {usage}")


def _write_llm_log(label: str, content: str) -> None:
    """Compatibility function matching the legacy core.llmcore log format."""
    LLMLogger().write(label, content)
