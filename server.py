"""
opencode-vision-mcp — MCP server exposing screenshot, record, and browser session tools.

Usage:
    python server.py

Configure in opencode.jsonc:
    "mcp": {
        "vision": {
            "type": "local",
            "command": ["python", "/path/to/opencode-mcp/server.py"],
            "enabled": true
        }
    }
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ImageContent,
    TextContent,
    Tool,
)

from tools.record import record_gif, _record_page
from tools.screenshot import take_screenshot, _screenshot_page
from tools.browser_session import (
    close_session,
    interact,
    is_session_open,
    open_session,
    get_page,
    navigate,
    evaluate,
)
from tools.diff import screenshot_diff

app = Server("opencode-vision")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_RETURN_INLINE_SCHEMA = {
    "type": "boolean",
    "description": (
        "When true (default), the image is returned inline so vision-capable models "
        "can see it directly. When false, only the file path is returned and the image "
        "is saved to the tmp directory without being transmitted."
    ),
    "default": True,
}

SCREENSHOT_TOOL = Tool(
    name="screenshot",
    description=(
        "Capture a screenshot of a running application and return the file path to a PNG image. "
        "Use 'url' to capture a web page in a headless browser. "
        "Use 'window_title' to capture a specific desktop window by title substring match. "
        "If neither is given, captures the full primary screen. "
        "The returned file_path can be opened or referenced to inspect the visual state of the app."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to open in a headless browser and capture. Takes priority over window_title.",
            },
            "window_title": {
                "type": "string",
                "description": "Substring to match against visible window titles for desktop capture.",
            },
            "delay": {
                "type": "number",
                "description": "Seconds to wait before capturing (useful to let animations or page loads settle). Default: 0.",
                "default": 0,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)

RECORD_TOOL = Tool(
    name="record",
    description=(
        "Record a short animated GIF of a running application and return the file path. "
        "Use 'url' to record a web page in a headless browser. "
        "Use 'window_title' to record a specific desktop window by title substring match. "
        "If neither is given, records the full primary screen. "
        "Keep duration short (2-5s) and fps low (3-8) for LLM-friendly file sizes."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to open in a headless browser and record.",
            },
            "window_title": {
                "type": "string",
                "description": "Substring to match against visible window titles for desktop recording.",
            },
            "duration": {
                "type": "number",
                "description": "How many seconds to record. Default: 3.",
                "default": 3,
            },
            "fps": {
                "type": "integer",
                "description": "Frames per second for the GIF (lower = smaller file). Default: 5.",
                "default": 5,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)

BROWSER_OPEN_TOOL = Tool(
    name="browser_open",
    description=(
        "Open a persistent Playwright browser session and navigate to a URL. "
        "The session stays alive between tool calls so you can click around, "
        "take screenshots, record GIFs, and interact with the page. "
        "If a session is already open, it is closed and replaced. "
        "Always call browser_close when you are done."
    ),
    inputSchema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to.",
            },
            "width": {
                "type": "integer",
                "description": "Viewport width in pixels. Default: 1280.",
                "default": 1280,
            },
            "height": {
                "type": "integer",
                "description": "Viewport height in pixels. Default: 900.",
                "default": 900,
            },
        },
    },
)

BROWSER_CLOSE_TOOL = Tool(
    name="browser_close",
    description=(
        "Close the active Playwright browser session and free all resources. "
        "Call this when you are done interacting with the browser."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

BROWSER_SCREENSHOT_TOOL = Tool(
    name="browser_screenshot",
    description=(
        "Take a screenshot of the currently active browser session page. "
        "Requires an open session (call browser_open first)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "delay": {
                "type": "number",
                "description": "Seconds to wait before capturing. Default: 0.",
                "default": 0,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)

BROWSER_RECORD_TOOL = Tool(
    name="browser_record",
    description=(
        "Record a short animated GIF of the currently active browser session page. "
        "Requires an open session (call browser_open first). "
        "Keep duration short (2-5s) and fps low (3-8) for LLM-friendly file sizes."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "duration": {
                "type": "number",
                "description": "How many seconds to record. Default: 3.",
                "default": 3,
            },
            "fps": {
                "type": "integer",
                "description": "Frames per second for the GIF. Default: 5.",
                "default": 5,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)

BROWSER_INTERACT_TOOL = Tool(
    name="browser_interact",
    description=(
        "Perform an interaction (click, type, scroll, hover, wait, keyboard) on the active browser session page. "
        "Requires an open session (call browser_open first). "
        "After interacting, use browser_screenshot to see the result. "
        "Use action='wait' with a selector to pause until an element appears. "
        "Use action='keyboard' to send key presses such as 'Enter', 'Escape', 'Tab', "
        "'ArrowDown', 'Control+z', 'Meta+a', 'F5', etc."
    ),
    inputSchema={
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "type", "scroll", "hover", "wait", "keyboard"],
                "description": "The type of interaction to perform.",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector to target. Takes priority over x/y coordinates.",
            },
            "x": {
                "type": "number",
                "description": "Page X coordinate (used when selector is not provided).",
            },
            "y": {
                "type": "number",
                "description": "Page Y coordinate (used when selector is not provided).",
            },
            "text": {
                "type": "string",
                "description": "Text to type. Required for the 'type' action.",
            },
            "key": {
                "type": "string",
                "description": (
                    "Playwright key name to press. Required for the 'keyboard' action. "
                    "Examples: 'Enter', 'Escape', 'Tab', 'Backspace', 'Delete', "
                    "'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', "
                    "'Control+a', 'Control+z', 'Control+c', 'Control+v', "
                    "'Meta+a', 'Meta+z', 'Shift+Tab', 'F5'."
                ),
            },
            "delta_x": {
                "type": "number",
                "description": "Horizontal scroll amount in pixels. Default: 0.",
                "default": 0,
            },
            "delta_y": {
                "type": "number",
                "description": "Vertical scroll amount in pixels. Default: 0.",
                "default": 0,
            },
            "timeout": {
                "type": "number",
                "description": "Max wait time in ms for the 'wait' action. Default: 5000.",
                "default": 5000,
            },
        },
    },
)

BROWSER_EVALUATE_TOOL = Tool(
    name="browser_evaluate",
    description=(
        "Execute JavaScript in the active browser session page context and return the result. "
        "Requires an open session (call browser_open first). "
        "Use this to: read DOM state (document.title, element text, computed styles), "
        "check application data (localStorage, sessionStorage, window variables), "
        "trigger events that browser_interact cannot (custom events, drag-and-drop), "
        "or verify conditions programmatically without taking a screenshot. "
        "The expression can be a simple JS expression ('document.title'), "
        "an arrow function ('() => window.location.pathname'), "
        "or a function that accepts an argument ('(n) => n * 2', paired with 'arg'). "
        "Returns the result value, its JS type, and any error message."
    ),
    inputSchema={
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "JavaScript expression or function to evaluate in the page. "
                    "Examples:\n"
                    "  'document.title'\n"
                    "  '() => document.querySelectorAll(\".error\").length'\n"
                    "  '() => JSON.parse(localStorage.getItem(\"user\"))'\n"
                    "  '() => window.getComputedStyle(document.body).backgroundColor'\n"
                    "  '(sel) => document.querySelector(sel)?.textContent' (use with arg)"
                ),
            },
            "arg": {
                "description": (
                    "Optional JSON-serializable value passed as the sole argument "
                    "when expression is a function. Default: null (not passed)."
                ),
            },
        },
    },
)

SCREENSHOT_DIFF_TOOL = Tool(
    name="screenshot_diff",
    description=(
        "Compute a visual diff between two screenshots and return a side-by-side PNG "
        "with changed pixels highlighted. "
        "Each input can be a local file path (from a previous screenshot tool call) or a URL "
        "(which will be screenshotted automatically). "
        "The result image shows the 'before' panel on the left and the 'after' panel on the right "
        "with changed areas highlighted in the specified color. "
        "Also returns statistics: changed_pixels, total_pixels, and change_percent."
    ),
    inputSchema={
        "type": "object",
        "required": ["before", "after"],
        "properties": {
            "before": {
                "type": "string",
                "description": "File path or URL of the 'before' image.",
            },
            "after": {
                "type": "string",
                "description": "File path or URL of the 'after' image.",
            },
            "highlight_color": {
                "type": "string",
                "description": "Hex color used to highlight changed pixels. Default: '#ff0000' (red).",
                "default": "#ff0000",
            },
            "threshold": {
                "type": "integer",
                "description": (
                    "Per-channel difference (0-255) below which a pixel is considered unchanged. "
                    "Higher values ignore minor rendering differences. Default: 10."
                ),
                "default": 10,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)

BROWSER_NAVIGATE_TOOL = Tool(
    name="browser_navigate",
    description=(
        "Navigate to a URL and optionally execute a sequence of interactions in a single tool call. "
        "Replaces the pattern of browser_open + multiple browser_interact + browser_screenshot calls. "
        "Reuses an existing browser session if one is open; otherwise opens a new one. "
        "Each step can optionally capture an intermediate screenshot by setting 'screenshot: true'. "
        "A final screenshot is taken after all steps by default. "
        "Supports a 'wait' step action to pause until a CSS selector appears in the DOM."
    ),
    inputSchema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to navigate to.",
            },
            "steps": {
                "type": "array",
                "description": (
                    "Optional list of interaction steps to execute in order after navigation. "
                    "Each step is an object with 'action' (click|type|scroll|hover|wait) "
                    "and the same parameters as browser_interact, plus an optional "
                    "'screenshot' boolean to capture an intermediate PNG after that step."
                ),
                "items": {
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "click",
                                "type",
                                "scroll",
                                "hover",
                                "wait",
                                "keyboard",
                            ],
                        },
                        "selector": {"type": "string"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "delta_x": {"type": "number", "default": 0},
                        "delta_y": {"type": "number", "default": 0},
                        "timeout": {"type": "number", "default": 5000},
                        "screenshot": {
                            "type": "boolean",
                            "description": "Capture a screenshot after this step.",
                            "default": False,
                        },
                    },
                },
            },
            "screenshot_after": {
                "type": "boolean",
                "description": "Take a final screenshot after all steps complete. Default: true.",
                "default": True,
            },
            "wait_for": {
                "type": "string",
                "enum": ["networkidle", "domcontentloaded", "load"],
                "description": "Page load event to wait for after navigation. Default: 'networkidle'.",
                "default": "networkidle",
            },
            "width": {
                "type": "integer",
                "description": "Viewport width in pixels (only used when opening a new session). Default: 1280.",
                "default": 1280,
            },
            "height": {
                "type": "integer",
                "description": "Viewport height in pixels (only used when opening a new session). Default: 900.",
                "default": 900,
            },
            "return_inline": _RETURN_INLINE_SCHEMA,
        },
    },
)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        SCREENSHOT_TOOL,
        RECORD_TOOL,
        BROWSER_OPEN_TOOL,
        BROWSER_CLOSE_TOOL,
        BROWSER_SCREENSHOT_TOOL,
        BROWSER_RECORD_TOOL,
        BROWSER_INTERACT_TOOL,
        BROWSER_EVALUATE_TOOL,
        SCREENSHOT_DIFF_TOOL,
        BROWSER_NAVIGATE_TOOL,
    ]


@app.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[TextContent | ImageContent]:
    if name == "screenshot":
        return await _handle_screenshot(arguments)
    elif name == "record":
        return await _handle_record(arguments)
    elif name == "browser_open":
        return await _handle_browser_open(arguments)
    elif name == "browser_close":
        return await _handle_browser_close(arguments)
    elif name == "browser_screenshot":
        return await _handle_browser_screenshot(arguments)
    elif name == "browser_record":
        return await _handle_browser_record(arguments)
    elif name == "browser_interact":
        return await _handle_browser_interact(arguments)
    elif name == "browser_evaluate":
        return await _handle_browser_evaluate(arguments)
    elif name == "screenshot_diff":
        return await _handle_screenshot_diff(arguments)
    elif name == "browser_navigate":
        return await _handle_browser_navigate(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_inline_png(file_path: str) -> Optional[ImageContent]:
    """Read a PNG file and return an ImageContent block, or None on error."""
    try:
        import base64

        with open(file_path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return ImageContent(type="image", data=data, mimeType="image/png")
    except Exception:
        return None


def _make_inline_gif_frame(file_path: str) -> Optional[ImageContent]:
    """Extract the first frame of a GIF as PNG and return an ImageContent, or None on error."""
    try:
        import base64
        import io

        from PIL import Image

        with Image.open(file_path) as gif:
            gif.seek(0)
            frame = gif.convert("RGB")
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        return ImageContent(type="image", data=data, mimeType="image/png")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# screenshot handler
# ---------------------------------------------------------------------------


async def _handle_screenshot(args: dict[str, Any]) -> list[TextContent | ImageContent]:
    url: Optional[str] = args.get("url")
    window_title: Optional[str] = args.get("window_title")
    delay: float = float(args.get("delay", 0))
    return_inline: bool = bool(args.get("return_inline", True))

    try:
        result = await take_screenshot(url=url, window_title=window_title, delay=delay)
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error taking screenshot: {exc}")
        ]

    parts: list[TextContent | ImageContent] = []

    if result.get("warning"):
        parts.append(TextContent(type="text", text=f"Warning: {result['warning']}"))

    file_path: str = result["file_path"]
    source: str = result["source"]

    summary = f"Screenshot saved.\n  file_path : {file_path}\n  source    : {source}\n"
    parts.append(TextContent(type="text", text=summary))

    if return_inline:
        inline = _make_inline_png(file_path)
        if inline:
            parts.append(inline)

    return parts


# ---------------------------------------------------------------------------
# record handler
# ---------------------------------------------------------------------------


async def _handle_record(args: dict[str, Any]) -> list[TextContent | ImageContent]:
    url: Optional[str] = args.get("url")
    window_title: Optional[str] = args.get("window_title")
    duration: float = float(args.get("duration", 3))
    fps: int = int(args.get("fps", 5))
    return_inline: bool = bool(args.get("return_inline", True))

    # Clamp to sane limits
    duration = max(0.5, min(duration, 30))
    fps = max(1, min(fps, 30))

    try:
        result = await record_gif(
            url=url, window_title=window_title, duration=duration, fps=fps
        )
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [TextContent(type="text", text=f"Unexpected error recording GIF: {exc}")]

    parts: list[TextContent | ImageContent] = []

    if result.get("warning"):
        parts.append(TextContent(type="text", text=f"Warning: {result['warning']}"))

    file_path: str = result["file_path"]
    source: str = result["source"]
    frame_count: int = result["frame_count"]

    try:
        size_kb = os.path.getsize(file_path) // 1024
        size_str = f"{size_kb} KB"
    except OSError:
        size_str = "unknown"

    summary = (
        f"Recording saved.\n"
        f"  file_path  : {file_path}\n"
        f"  source     : {source}\n"
        f"  frames     : {frame_count}\n"
        f"  duration   : {duration}s @ {fps} fps\n"
        f"  size       : {size_str}\n"
    )
    parts.append(TextContent(type="text", text=summary))

    if return_inline:
        inline = _make_inline_gif_frame(file_path)
        if inline:
            parts.append(inline)

    return parts


# ---------------------------------------------------------------------------
# browser_open handler
# ---------------------------------------------------------------------------


async def _handle_browser_open(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    url: str = args["url"]
    width: int = int(args.get("width", 1280))
    height: int = int(args.get("height", 900))

    try:
        result = await open_session(url=url, width=width, height=height)
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error opening browser: {exc}")
        ]

    summary = (
        f"Browser session opened.\n"
        f"  url    : {result['url']}\n"
        f"  size   : {result['width']}x{result['height']}\n"
    )
    return [TextContent(type="text", text=summary)]


# ---------------------------------------------------------------------------
# browser_close handler
# ---------------------------------------------------------------------------


async def _handle_browser_close(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    try:
        result = await close_session()
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error closing browser: {exc}")
        ]

    if result["status"] == "no_session":
        return [TextContent(type="text", text="No active browser session to close.")]

    return [TextContent(type="text", text="Browser session closed.")]


# ---------------------------------------------------------------------------
# browser_screenshot handler
# ---------------------------------------------------------------------------


async def _handle_browser_screenshot(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    delay: float = float(args.get("delay", 0))
    return_inline: bool = bool(args.get("return_inline", True))

    page = get_page()
    if page is None:
        return [
            TextContent(
                type="text",
                text="Error: No active browser session. Call browser_open first.",
            )
        ]

    try:
        file_path = await _screenshot_page(page, delay=delay)
    except Exception as exc:
        return [
            TextContent(
                type="text", text=f"Unexpected error taking browser screenshot: {exc}"
            )
        ]

    parts: list[TextContent | ImageContent] = []
    summary = (
        f"Browser screenshot saved.\n"
        f"  file_path : {file_path}\n"
        f"  url       : {page.url}\n"
    )
    parts.append(TextContent(type="text", text=summary))

    if return_inline:
        inline = _make_inline_png(file_path)
        if inline:
            parts.append(inline)

    return parts


# ---------------------------------------------------------------------------
# browser_record handler
# ---------------------------------------------------------------------------


async def _handle_browser_record(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    duration: float = float(args.get("duration", 3))
    fps: int = int(args.get("fps", 5))
    return_inline: bool = bool(args.get("return_inline", True))

    # Clamp to sane limits
    duration = max(0.5, min(duration, 30))
    fps = max(1, min(fps, 30))

    page = get_page()
    if page is None:
        return [
            TextContent(
                type="text",
                text="Error: No active browser session. Call browser_open first.",
            )
        ]

    try:
        file_path = await _record_page(page, duration=duration, fps=fps)
    except Exception as exc:
        return [
            TextContent(
                type="text", text=f"Unexpected error recording browser GIF: {exc}"
            )
        ]

    parts: list[TextContent | ImageContent] = []

    try:
        size_kb = os.path.getsize(file_path) // 1024
        size_str = f"{size_kb} KB"
    except OSError:
        size_str = "unknown"

    frame_count = max(1, int(duration * fps))
    summary = (
        f"Browser recording saved.\n"
        f"  file_path  : {file_path}\n"
        f"  url        : {page.url}\n"
        f"  frames     : {frame_count}\n"
        f"  duration   : {duration}s @ {fps} fps\n"
        f"  size       : {size_str}\n"
    )
    parts.append(TextContent(type="text", text=summary))

    if return_inline:
        inline = _make_inline_gif_frame(file_path)
        if inline:
            parts.append(inline)

    return parts


# ---------------------------------------------------------------------------
# browser_interact handler
# ---------------------------------------------------------------------------


async def _handle_browser_interact(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    action: str = args.get("action", "")
    selector: Optional[str] = args.get("selector")
    x: Optional[float] = args.get("x")
    y: Optional[float] = args.get("y")
    text: Optional[str] = args.get("text")
    key: Optional[str] = args.get("key")
    delta_x: float = float(args.get("delta_x", 0))
    delta_y: float = float(args.get("delta_y", 0))
    timeout: float = float(args.get("timeout", 5000))

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
            timeout=timeout,
        )
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except ValueError as exc:
        return [TextContent(type="text", text=f"Invalid arguments: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error during interaction: {exc}")
        ]

    summary = (
        f"Interaction complete.\n"
        f"  action : {result['action']}\n"
        f"  detail : {result['detail']}\n"
        f"  url    : {result['url']}\n"
    )
    return [TextContent(type="text", text=summary)]


# ---------------------------------------------------------------------------
# browser_evaluate handler
# ---------------------------------------------------------------------------


async def _handle_browser_evaluate(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    expression: Optional[str] = args.get("expression")
    arg = args.get("arg")  # any JSON value; None means "don't pass an arg"

    if not expression:
        return [TextContent(type="text", text="Error: 'expression' is required.")]

    try:
        result = await evaluate(expression=expression, arg=arg)
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error during evaluate: {exc}")
        ]

    if result["error"] is not None:
        summary = (
            f"JavaScript error.\n"
            f"  error : {result['error']}\n"
            f"  url   : {result['url']}\n"
        )
    else:
        import json as _json

        # Pretty-print objects/arrays; keep scalars on one line
        raw = result["result"]
        if isinstance(raw, (dict, list)):
            result_str = _json.dumps(raw, indent=2, ensure_ascii=False)
        else:
            result_str = str(raw) if raw is not None else "null"

        summary = (
            f"JavaScript evaluated successfully.\n"
            f"  result : {result_str}\n"
            f"  type   : {result['type']}\n"
            f"  url    : {result['url']}\n"
        )

    return [TextContent(type="text", text=summary)]


# ---------------------------------------------------------------------------
# screenshot_diff handler
# ---------------------------------------------------------------------------


async def _handle_screenshot_diff(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    before: Optional[str] = args.get("before")
    after: Optional[str] = args.get("after")
    highlight_color: str = args.get("highlight_color", "#ff0000")
    threshold: int = int(args.get("threshold", 10))
    return_inline: bool = bool(args.get("return_inline", True))

    if not before or not after:
        return [
            TextContent(type="text", text="Error: 'before' and 'after' are required.")
        ]

    try:
        result = await screenshot_diff(
            before=before,
            after=after,
            highlight_color=highlight_color,
            threshold=threshold,
        )
    except FileNotFoundError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error computing diff: {exc}")
        ]

    file_path: str = result["file_path"]
    changed: int = result["changed_pixels"]
    total: int = result["total_pixels"]
    pct: float = result["change_percent"]

    summary = (
        f"Diff saved.\n"
        f"  file_path      : {file_path}\n"
        f"  changed_pixels : {changed:,} / {total:,}\n"
        f"  change_percent : {pct}%\n"
    )
    parts: list[TextContent | ImageContent] = [TextContent(type="text", text=summary)]

    if return_inline:
        inline = _make_inline_png(file_path)
        if inline:
            parts.append(inline)

    return parts


# ---------------------------------------------------------------------------
# browser_navigate handler
# ---------------------------------------------------------------------------


async def _handle_browser_navigate(
    args: dict[str, Any],
) -> list[TextContent | ImageContent]:
    url: str = args.get("url", "")
    steps: list = args.get("steps", [])
    screenshot_after: bool = bool(args.get("screenshot_after", True))
    wait_for: str = args.get("wait_for", "networkidle")
    width: int = int(args.get("width", 1280))
    height: int = int(args.get("height", 900))
    return_inline: bool = bool(args.get("return_inline", True))

    if not url:
        return [TextContent(type="text", text="Error: 'url' is required.")]

    try:
        result = await navigate(
            url=url,
            steps=steps,
            screenshot_after=screenshot_after,
            wait_for=wait_for,  # type: ignore[arg-type]
            width=width,
            height=height,
        )
    except RuntimeError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        return [
            TextContent(type="text", text=f"Unexpected error during navigation: {exc}")
        ]

    parts: list[TextContent | ImageContent] = []

    # Build a step-by-step summary
    lines = [f"Navigation complete.\n  url : {result['url']}\n"]
    steps_executed: list[dict] = result.get("steps_executed", [])
    if steps_executed:
        lines.append(f"  steps ({len(steps_executed)}):")
        for step in steps_executed:
            lines.append(f"    [{step['step']}] {step['action']} — {step['detail']}")
    parts.append(TextContent(type="text", text="\n".join(lines)))

    # Inline intermediate screenshots (if any step had screenshot=true)
    if return_inline:
        for step in steps_executed:
            spath = step.get("screenshot_path")
            if spath:
                step_text = TextContent(
                    type="text",
                    text=f"Step {step['step']} screenshot ({step['action']}):",
                )
                parts.append(step_text)
                inline = _make_inline_png(spath)
                if inline:
                    parts.append(inline)

    # Final screenshot
    final_path: Optional[str] = result.get("final_screenshot")
    if final_path:
        if steps_executed:
            parts.append(TextContent(type="text", text="Final screenshot:"))
        inline = _make_inline_png(final_path)
        if inline and return_inline:
            parts.append(inline)
        elif not return_inline:
            parts.append(
                TextContent(type="text", text=f"  final_screenshot : {final_path}")
            )

    return parts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
