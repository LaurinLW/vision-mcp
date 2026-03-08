"""
opencode-vision-mcp — MCP server exposing screenshot and record tools.

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

from tools.record import record_gif
from tools.screenshot import take_screenshot

app = Server("opencode-vision")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

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
        },
    },
)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [SCREENSHOT_TOOL, RECORD_TOOL]


@app.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[TextContent | ImageContent]:
    if name == "screenshot":
        return await _handle_screenshot(arguments)
    elif name == "record":
        return await _handle_record(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_screenshot(args: dict[str, Any]) -> list[TextContent | ImageContent]:
    url: Optional[str] = args.get("url")
    window_title: Optional[str] = args.get("window_title")
    delay: float = float(args.get("delay", 0))

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

    # Also return the image inline so vision-capable models can see it directly
    try:
        import base64

        with open(file_path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        parts.append(ImageContent(type="image", data=data, mimeType="image/png"))
    except Exception:
        pass  # Inline image is best-effort; the file path is always returned

    return parts


async def _handle_record(args: dict[str, Any]) -> list[TextContent | ImageContent]:
    url: Optional[str] = args.get("url")
    window_title: Optional[str] = args.get("window_title")
    duration: float = float(args.get("duration", 3))
    fps: int = int(args.get("fps", 5))

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

    import os

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

    # Return first frame inline as PNG for models that support image content
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
        parts.append(ImageContent(type="image", data=data, mimeType="image/png"))
    except Exception:
        pass  # Best-effort

    return parts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
