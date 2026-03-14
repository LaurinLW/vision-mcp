"""
browser_session — persistent Playwright browser session for interactive web exploration.

A single browser instance and page are kept alive in module-level state between
tool calls so the LLM can open a page, click around, take screenshots or GIFs,
and finally close the browser — all within one conversation.

Public API
----------
open_session(url, width, height)  -> dict
close_session()                   -> dict
interact(action, ...)             -> dict
get_page()                        -> playwright Page | None
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Module-level session state
# ---------------------------------------------------------------------------

_playwright_ctx: Any = None  # AsyncPlaywright context manager result
_browser: Any = None
_page: Any = None


def get_page() -> Any:
    """Return the active Playwright Page, or None if no session is open."""
    return _page


def is_session_open() -> bool:
    return _page is not None


# ---------------------------------------------------------------------------
# open / close
# ---------------------------------------------------------------------------


async def open_session(
    url: str,
    width: int = 1280,
    height: int = 900,
) -> dict:
    """
    Launch a new Playwright browser session, navigate to *url*, and keep it
    alive.  If a session is already open it is closed first.

    Returns a dict with:
        url         : final URL after navigation
        width       : viewport width
        height      : viewport height
        status      : "opened"
    """
    global _playwright_ctx, _browser, _page

    # Close any existing session cleanly
    if _page is not None or _browser is not None:
        await close_session()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. "
            "Run: pip install playwright && playwright install chromium"
        )

    _playwright_ctx = async_playwright()
    pw = await _playwright_ctx.__aenter__()
    _browser = await pw.chromium.launch(headless=True)
    _page = await _browser.new_page(viewport={"width": width, "height": height})
    await _page.goto(url, wait_until="networkidle", timeout=30_000)

    return {
        "status": "opened",
        "url": _page.url,
        "width": width,
        "height": height,
    }


async def close_session() -> dict:
    """
    Close the active Playwright browser session and clean up state.

    Returns a dict with:
        status : "closed" | "no_session"
    """
    global _playwright_ctx, _browser, _page

    if _page is None and _browser is None and _playwright_ctx is None:
        return {"status": "no_session"}

    try:
        if _browser is not None:
            await _browser.close()
    except Exception:
        pass

    try:
        if _playwright_ctx is not None:
            await _playwright_ctx.__aexit__(None, None, None)
    except Exception:
        pass

    _playwright_ctx = None
    _browser = None
    _page = None

    return {"status": "closed"}


# ---------------------------------------------------------------------------
# interact
# ---------------------------------------------------------------------------

Action = Literal["click", "type", "scroll", "hover", "wait", "keyboard"]


async def interact(
    action: Action,
    selector: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    text: Optional[str] = None,
    key: Optional[str] = None,
    delta_x: float = 0,
    delta_y: float = 0,
    timeout: float = 5000,
) -> dict:
    """
    Perform a single interaction on the active page.

    Parameters
    ----------
    action   : "click" | "type" | "scroll" | "hover" | "wait" | "keyboard"
    selector : CSS selector (takes priority over x/y for click/hover/type/wait)
    x, y     : page coordinates (used when selector is not provided)
    text     : text to type (required for "type")
    key      : Playwright key name to press, e.g. "Enter", "Escape", "Control+z"
               (required for "keyboard")
    delta_x  : horizontal scroll amount in pixels (for "scroll")
    delta_y  : vertical scroll amount in pixels (for "scroll")
    timeout  : max wait time in ms for "wait" action (default 5000)

    Returns a dict with:
        action  : echoed action name
        detail  : human-readable description of what was done
        url     : current page URL after the interaction
    """
    if _page is None:
        raise RuntimeError("No browser session is open. Call browser_open first.")

    detail: str

    if action == "click":
        if selector is not None:
            await _page.click(selector)
            detail = f"Clicked selector '{selector}'"
        elif x is not None and y is not None:
            await _page.mouse.click(x, y)
            detail = f"Clicked at ({x}, {y})"
        else:
            raise ValueError("click requires either 'selector' or both 'x' and 'y'.")

    elif action == "type":
        if text is None:
            raise ValueError("'type' action requires the 'text' parameter.")
        if selector is not None:
            await _page.fill(selector, text)
            detail = f"Typed '{text}' into selector '{selector}'"
        elif x is not None and y is not None:
            await _page.mouse.click(x, y)
            await _page.keyboard.type(text)
            detail = f"Typed '{text}' at ({x}, {y})"
        else:
            # Type at wherever focus currently is
            await _page.keyboard.type(text)
            detail = f"Typed '{text}' at current focus"

    elif action == "scroll":
        if selector is not None:
            await _page.evaluate(
                "(el, dx, dy) => el.scrollBy(dx, dy)",
                await _page.query_selector(selector),
                delta_x,
                delta_y,
            )
            detail = f"Scrolled selector '{selector}' by ({delta_x}, {delta_y})"
        elif x is not None and y is not None:
            await _page.mouse.wheel(delta_x, delta_y)
            detail = f"Scrolled at ({x}, {y}) by ({delta_x}, {delta_y})"
        else:
            await _page.mouse.wheel(delta_x, delta_y)
            detail = f"Scrolled page by ({delta_x}, {delta_y})"

    elif action == "hover":
        if selector is not None:
            await _page.hover(selector)
            detail = f"Hovered over selector '{selector}'"
        elif x is not None and y is not None:
            await _page.mouse.move(x, y)
            detail = f"Hovered at ({x}, {y})"
        else:
            raise ValueError("hover requires either 'selector' or both 'x' and 'y'.")

    elif action == "wait":
        if selector is None:
            raise ValueError("'wait' action requires a 'selector' to wait for.")
        await _page.wait_for_selector(selector, timeout=timeout)
        detail = f"Waited for selector '{selector}' to appear (timeout={timeout}ms)"

    elif action == "keyboard":
        if key is None:
            raise ValueError(
                "'keyboard' action requires the 'key' parameter. "
                "Examples: 'Enter', 'Escape', 'Tab', 'Control+z', 'Meta+a'."
            )
        await _page.keyboard.press(key)
        detail = f"Pressed key '{key}'"

    else:
        raise ValueError(
            f"Unknown action '{action}'. Must be one of: click, type, scroll, hover, wait, keyboard."
        )

    return {
        "action": action,
        "detail": detail,
        "url": _page.url,
    }


# ---------------------------------------------------------------------------
# navigate — open/reuse session, run a sequence of steps, return screenshots
# ---------------------------------------------------------------------------

WaitUntil = Literal["networkidle", "domcontentloaded", "load"]


async def navigate(
    url: str,
    steps: Optional[list[dict]] = None,
    screenshot_after: bool = True,
    wait_for: WaitUntil = "networkidle",
    width: int = 1280,
    height: int = 900,
) -> dict:
    """
    Navigate to *url* in a browser session, optionally execute a sequence of
    interaction steps, and return collected screenshots and step results.

    If a session is already open the existing browser is reused (the page is
    navigated to *url*); otherwise a new session is opened.

    Parameters
    ----------
    url             : URL to navigate to
    steps           : list of step dicts.  Each step supports the same fields as
                      ``interact()`` plus an optional ``"screenshot": true/false``
                      flag to capture a PNG after that specific step.
                      Supported step actions: "click", "type", "scroll", "hover", "wait", "keyboard".
    screenshot_after : whether to take a final screenshot after all steps (default True)
    wait_for        : page load event to wait for after navigation
                      ("networkidle" | "domcontentloaded" | "load")
    width / height  : viewport dimensions (only used when opening a new session)

    Returns
    -------
    dict with keys:
        url             : final page URL
        steps_executed  : list of step result dicts (action, detail, url, screenshot_path?)
        final_screenshot: file path of the final screenshot, or None
    """
    global _playwright_ctx, _browser, _page

    from tools.screenshot import _screenshot_page  # local import to avoid circulars

    # --- Open or reuse session ---
    if _page is None or _browser is None:
        await open_session(url=url, width=width, height=height)
    else:
        # Reuse existing browser — just navigate the existing page
        await _page.goto(url, wait_until=wait_for, timeout=30_000)

    step_results: list[dict] = []

    for i, step in enumerate(steps or []):
        action: str = step.get("action", "")
        selector: Optional[str] = step.get("selector")
        x: Optional[float] = step.get("x")
        y: Optional[float] = step.get("y")
        text: Optional[str] = step.get("text")
        key: Optional[str] = step.get("key")
        delta_x: float = float(step.get("delta_x", 0))
        delta_y: float = float(step.get("delta_y", 0))
        step_timeout: float = float(step.get("timeout", 5000))
        take_step_screenshot: bool = bool(step.get("screenshot", False))

        step_result: dict = {
            "step": i + 1,
            "action": action,
            "detail": "",
            "url": _page.url,
            "screenshot_path": None,
        }

        try:
            result = await interact(
                action=action,  # type: ignore[arg-type]
                selector=selector,
                x=x,
                y=y,
                text=text,
                key=key,
                delta_x=delta_x,
                delta_y=delta_y,
                timeout=step_timeout,
            )
            step_result["detail"] = result["detail"]
            step_result["url"] = result["url"]
        except (ValueError, RuntimeError) as exc:
            step_result["detail"] = f"ERROR: {exc}"

        if take_step_screenshot:
            try:
                path = await _screenshot_page(_page)
                step_result["screenshot_path"] = path
            except Exception as exc:
                step_result["screenshot_path"] = None
                step_result["detail"] += f" | screenshot failed: {exc}"

        step_results.append(step_result)

    # --- Final screenshot ---
    final_path: Optional[str] = None
    if screenshot_after:
        try:
            final_path = await _screenshot_page(_page)
        except Exception:
            pass

    return {
        "url": _page.url if _page else url,
        "steps_executed": step_results,
        "final_screenshot": final_path,
    }


# ---------------------------------------------------------------------------
# evaluate — execute JavaScript in the active page context
# ---------------------------------------------------------------------------


async def evaluate(
    expression: str,
    arg: Any = None,
) -> dict:
    """
    Execute a JavaScript expression or function in the active page context.

    Parameters
    ----------
    expression : JavaScript to evaluate.  Can be:
                 - A simple expression: "document.title"
                 - An arrow function:   "() => window.location.pathname"
                 - A function with arg: "(n) => n * 2"  (paired with ``arg``)
    arg        : Optional JSON-serializable value passed as the sole argument
                 when ``expression`` is a function.  Defaults to None (not passed).

    Returns
    -------
    dict with keys:
        result    : the return value, JSON-serialized (string, number, list, dict, …)
                    or a string representation when the value is not serialisable.
        type      : JavaScript typeof string ("string", "number", "boolean", "object",
                    "undefined") — helps distinguish null/undefined from real values.
        error     : error message string if the expression threw, else None.
        url       : current page URL at time of evaluation.
    """
    import json

    if _page is None:
        raise RuntimeError("No browser session is open. Call browser_open first.")

    try:
        if arg is not None:
            raw = await _page.evaluate(expression, arg)
        else:
            raw = await _page.evaluate(expression)

        # Determine a useful type label
        if raw is None:
            type_label = "null"
        elif isinstance(raw, bool):
            type_label = "boolean"
        elif isinstance(raw, int) or isinstance(raw, float):
            type_label = "number"
        elif isinstance(raw, str):
            type_label = "string"
        elif isinstance(raw, (list, dict)):
            type_label = "object"
        else:
            type_label = type(raw).__name__

        # Serialise result — fall back to str() for non-JSON types
        try:
            result_serialised = json.loads(json.dumps(raw))
        except (TypeError, ValueError):
            result_serialised = str(raw)

        return {
            "result": result_serialised,
            "type": type_label,
            "error": None,
            "url": _page.url,
        }

    except RuntimeError:
        raise  # re-raise "no session" errors
    except Exception as exc:
        return {
            "result": None,
            "type": "error",
            "error": str(exc),
            "url": _page.url if _page else "",
        }
