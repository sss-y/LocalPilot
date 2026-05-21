"""Local code execution helpers."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Generator, Iterable

from .formatter import smart_format

SCRIPT_DIR = Path(__file__).resolve().parent.parent


def code_run(
    code: str,
    code_type: str = "python",
    timeout: int = 60,
    cwd: str | None = None,
    code_cwd: str | None = None,
    stop_signal: Iterable[object] | None = None,
) -> Generator[str, None, dict]:
    """Run code and stream lightweight progress logs."""
    stop_signal = stop_signal if stop_signal is not None else []
    preview = (code[:60].replace("\n", " ") + "...") if len(code) > 60 else code.strip()
    run_cwd = cwd or str(SCRIPT_DIR / "temp")
    tmp_path: str | None = None
    yield f"[Action] Running {code_type} in {os.path.basename(run_cwd)}: {preview}\n"

    if code_type in {"python", "py"}:
        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".ai.py",
            delete=False,
            mode="w",
            encoding="utf-8",
            dir=code_cwd,
        )
        tmp_file.write(code)
        tmp_path = tmp_file.name
        tmp_file.close()
        cmd = [sys.executable, "-X", "utf8", "-u", tmp_path]

    
    elif code_type in {"powershell", "bash", "sh", "shell", "ps1", "pwsh"}:
        if os.name == "nt":
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", code]
        else:
            cmd = ["bash", "-c", code]
    else:
        return {"status": "error", "msg": f"不支持的类型: {code_type}"}

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    stdout_parts: list[str] = []

    def stream_reader(proc: subprocess.Popen[bytes], logs: list[str]) -> None:
        try:
            for line_bytes in iter(proc.stdout.readline, b""):  # type: ignore[union-attr]
                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    line = line_bytes.decode("gbk", errors="ignore")
                logs.append(line)
        except Exception:
            pass

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            cwd=run_cwd,
            startupinfo=startupinfo,
        )
        start_t = time.time()
        # 启动线程读取输出流
        reader = threading.Thread(target=stream_reader, args=(process, stdout_parts), daemon=True)
        reader.start()
        # 监控读线程,超时或者用户打断直接杀死进程
        while reader.is_alive():
            is_timeout = time.time() - start_t > timeout
            if is_timeout or stop_signal:
                process.kill()
                if is_timeout:
                    stdout_parts.append("\n[Timeout Error] 超时强制终止")
                else:
                    stdout_parts.append("\n[Stopped] 用户强制终止")
                break
            time.sleep(1)

        reader.join(timeout=1)
        exit_code = process.poll()
        stdout_str = "".join(stdout_parts)
        status = "success" if exit_code == 0 else "error"
        status_icon = "✅" if exit_code == 0 else "❌"
        if exit_code is None:
            status_icon = "⏳"
        output_snippet = smart_format(
            stdout_str,
            max_str_len=600,
            omit_str="\n\n[omitted long output]\n\n",
        )
        output_snippet = re.sub(
            r"`{4,}",
            lambda match: match.group(0)[:3] + "\u200b" + match.group(0)[3:],
            output_snippet,
        )
        yield f"[Status] {status_icon} Exit Code: {exit_code}\n[Stdout]\n{output_snippet}\n"
        return {
            "status": status,
            "stdout": smart_format(
                stdout_str,
                max_str_len=10000,
                omit_str="\n\n[omitted long output]\n\n",
            ),
            "exit_code": exit_code,
        }
    except Exception as exc:
        if process is not None:
            process.kill()
        return {"status": "error", "msg": str(exc)}
    finally:
        if code_type in {"python", "py"} and tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
