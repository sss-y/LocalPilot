"""core.config

职责：
- 读取 `core/config/mykey.py` 或 `mykey.json`
- 对外暴露 `mykeys` 懒加载访问
- 按文件修改时间做热更新

边界：
- 这里只负责配置获取，不负责模型请求和日志写入
- Session 层通过这里拿到 provider / model / timeout 等配置
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any


_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_MYKEY_PY_PATH = _CONFIG_DIR / "mykey.py"
_MYKEY_JSON_PATH = _CONFIG_DIR / "mykey.json"

# 赋值全局变量为 none，触发第一次访问时加载 mykeys 并更新全局变量。
_mykey_path: str | None = None
_mykey_mtime: int | None = None


def _module_to_dict(module: ModuleType) -> dict[str, Any]:
    return {
        key: value
        for key, value in vars(module).items()
        if not key.startswith("_") and not callable(value)
    }


def _load_py_config(path: Path) -> dict[str, Any]:
    module = ModuleType("_ga_mykey_runtime")
    module.__file__ = str(path)
    source = path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), vars(module))
    return _module_to_dict(module)


def _load_mykeys() -> dict[str, Any]:
    """读取 mykey.py 或 mykey.json，优先 py。"""
    global _mykey_path

    if _MYKEY_PY_PATH.exists():
        _mykey_path = str(_MYKEY_PY_PATH)
        return _load_py_config(_MYKEY_PY_PATH)

    _mykey_path = str(_MYKEY_JSON_PATH)
    if not _MYKEY_JSON_PATH.exists():
        raise Exception(
            "[ERROR] mykey.py or mykey.json not found, please create one from mykey_template."
        )

    with _MYKEY_JSON_PATH.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("mykey.json must contain a top-level object")
    return data


def reload_mykeys() -> tuple[dict[str, Any], bool]:
    """重新加载配置并返回 (配置字典, 是否发生变化)。"""
    global _mykey_mtime

    mt = os.stat(_mykey_path).st_mtime_ns if _mykey_path else -1
    if mt == _mykey_mtime:
        return globals().get("mykeys", {}), False

    mk = _load_mykeys()
    _mykey_mtime = os.stat(_mykey_path).st_mtime_ns
    print(f"[Info] Load mykeys from {_mykey_path}")
    globals().update(mykeys=mk)

    if mk.get("langfuse_config"):
        try:
            from plugins import langfuse_tracing  # noqa: F401
        except Exception:
            pass

    return mk, True


def __getattr__(name: str) -> Any:
    if name == "mykeys":
        return reload_mykeys()[0]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
