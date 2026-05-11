"""Lightweight web helpers."""

from __future__ import annotations

import importlib

from .formatter import format_error, smart_format

driver = None


def first_init_driver():
    """Try to initialize the browser driver lazily."""
    global driver
    if driver is not None:
        return driver
    try:
        from TMWebDriver import TMWebDriver  # type: ignore
    except Exception:
        return None
    driver = TMWebDriver()
    try:
        sessions = driver.get_all_sessions()
        if len(sessions) == 1:
            import time

            time.sleep(3)
    except Exception:
        return None
    return driver


def web_scan(
    tabs_only: bool = False,
    switch_tab_id: str | None = None,
    text_only: bool = False,
) -> dict:
    """Return current tab metadata and optionally simplified page content."""
    global driver
    try:
        if driver is None:
            first_init_driver()
        if driver is None or len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        tabs = []
        for session in driver.get_all_sessions():
            session.pop("connected_at", None)
            session.pop("type", None)
            url = session.get("url", "")
            session["url"] = url[:50] + ("..." if len(url) > 50 else "")
            tabs.append(session)
        if switch_tab_id:
            driver.default_session_id = switch_tab_id
        result = {
            "status": "success",
            "metadata": {
                "tabs_count": len(tabs),
                "tabs": tabs,
                "active_tab": driver.default_session_id,
            },
        }
        if not tabs_only:
            import simphtml  # type: ignore

            importlib.reload(simphtml)
            result["content"] = simphtml.get_html(
                driver,
                cutlist=True,
                maxchars=35000,
                text_only=text_only,
            )
            if text_only:
                result["content"] = smart_format(
                    result["content"],
                    max_str_len=10000,
                    omit_str="\n\n[omitted long content]\n\n",
                )
        return result
    except Exception as exc:
        return {"status": "error", "msg": format_error(exc)}


def web_execute_js(
    script: str,
    switch_tab_id: str | None = None,
    no_monitor: bool = False,
) -> dict:
    """Execute JavaScript in the active browser tab."""
    global driver
    try:
        if driver is None:
            first_init_driver()
        if driver is None or len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        if switch_tab_id:
            driver.default_session_id = switch_tab_id
        import simphtml  # type: ignore

        return simphtml.execute_js_rich(script, driver, no_monitor=no_monitor)
    except Exception as exc:
        return {"status": "error", "msg": format_error(exc)}
