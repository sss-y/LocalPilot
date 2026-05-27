"""core.config

职责：
- 读取项目根目录可导入的 `mykey.py`，或回退到 `core/mykey.json`
- 对外暴露 `mykeys` 懒加载访问
- 按文件修改时间做热更新

边界：
- 这里只负责配置获取，不负责模型请求和日志写入
- Session 层通过这里拿到 provider / model / timeout 等配置
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any


_mykey_path: str | None = None
_mykey_mtime: int | None = None


def _load_mykeys() -> dict[str, Any]:
    """Load mykey.py first, then fall back to core/mykey.json."""
    global _mykey_path
    try:
        import mykey

        importlib.reload(mykey)
        _mykey_path = mykey.__file__
        return {k: v for k, v in vars(mykey).items() if not k.startswith("_")}
    except ImportError:
        pass

    _mykey_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mykey.json")
    if not os.path.exists(_mykey_path):
        raise Exception("[ERROR] mykey.py or mykey.json not found, please create one from mykey_template.")
    with open(_mykey_path, encoding="utf-8") as file:
        return json.load(file)


def reload_mykeys() -> tuple[dict[str, Any], bool]:
    """Reload config and return (config, changed)."""
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
