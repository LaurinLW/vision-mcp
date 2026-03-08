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

Action = Literal["click", "type", "scroll", "hover"]


async def interact(
    action: Action,
    selector: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    text: Optional[str] = None,
    delta_x: float = 0,
    delta_y: float = 0,
) -> dict:
    """
    Perform a single interaction on the active page.

    Parameters
    ----------
    action   : "click" | "type" | "scroll" | "hover"
    selector : CSS selector (takes priority over x/y for click/hover/type)
    x, y     : page coordinates (used when selector is not provided)
    text     : text to type (required for "type")
    delta_x  : horizontal scroll amount in pixels (for "scroll")
    delta_y  : vertical scroll amount in pixels (for "scroll")

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

    else:
        raise ValueError(
            f"Unknown action '{action}'. Must be one of: click, type, scroll, hover."
        )

    return {
        "action": action,
        "detail": detail,
        "url": _page.url,
    }
