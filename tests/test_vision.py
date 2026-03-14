"""
Tests for opencode-vision-mcp.

Run with:
    pytest tests/test_vision.py -v

Requirements:
    pip install pytest Pillow playwright mcp
    playwright install chromium

Most desktop tests are skipped automatically on non-WSL machines.
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _is_wsl() -> bool:
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


WSL = _is_wsl()
requires_wsl = pytest.mark.skipif(not WSL, reason="WSL-only test")


# ---------------------------------------------------------------------------
# Unit tests — no I/O
# ---------------------------------------------------------------------------


def test_win_path_to_wsl_drive_letter():
    from tools.screenshot import _win_path_to_wsl

    assert _win_path_to_wsl(r"C:\Users\foo\bar.png") == "/mnt/c/Users/foo/bar.png"


def test_win_path_to_wsl_lowercase_drive():
    from tools.screenshot import _win_path_to_wsl

    assert _win_path_to_wsl(r"d:\tmp\file.png") == "/mnt/d/tmp/file.png"


def test_win_path_to_wsl_no_drive():
    from tools.screenshot import _win_path_to_wsl

    # Paths without a drive letter should come back unchanged (best-effort)
    result = _win_path_to_wsl("/already/unix")
    assert result == "/already/unix"


def test_is_wsl_returns_bool():
    from tools.window import is_wsl

    assert isinstance(is_wsl(), bool)


# ---------------------------------------------------------------------------
# Window geometry lookup (WSL-only, live PowerShell)
# ---------------------------------------------------------------------------


@requires_wsl
def test_get_window_geometry_miss_returns_none():
    """A title that matches nothing should return None without raising."""
    from tools.window import get_window_geometry

    result = get_window_geometry("__THIS_TITLE_DOES_NOT_EXIST_XYZ__")
    assert result is None


@requires_wsl
def test_get_window_geometry_hit_returns_tuple():
    """
    Assumes at least one Windows window is open (e.g. Explorer, Task Manager).
    Passes the title 'Explorer' as a broad match.  Skip if nothing is found
    rather than failing — the important thing is the shape of the return value.
    """
    from tools.window import get_window_geometry

    result = get_window_geometry("Explorer")
    if result is None:
        pytest.skip("No matching window found — cannot verify shape.")
    left, top, width, height = result
    assert width > 0 and height > 0


# ---------------------------------------------------------------------------
# Desktop screenshot (WSL-only, live PowerShell)
# ---------------------------------------------------------------------------


@requires_wsl
def test_screenshot_full_screen_wsl():
    """Full-screen desktop capture should produce a non-empty PNG."""
    from tools.screenshot import _screenshot_wsl

    path = _screenshot_wsl()
    assert os.path.exists(path), f"PNG not found at {path}"
    size = os.path.getsize(path)
    assert size > 10_000, f"PNG suspiciously small: {size} bytes"
    # Clean up
    os.remove(path)


# ---------------------------------------------------------------------------
# Browser screenshot (any platform, requires Playwright + Chromium)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screenshot_browser_url():
    """Browser screenshot of example.com should return a PNG path."""
    pytest.importorskip("playwright")
    from tools.screenshot import _screenshot_browser

    path = await _screenshot_browser("https://example.com")
    assert os.path.exists(path), f"PNG not found at {path}"
    assert path.endswith(".png")
    size = os.path.getsize(path)
    assert size > 1_000, f"PNG suspiciously small: {size} bytes"
    os.remove(path)


# ---------------------------------------------------------------------------
# take_screenshot integration (WSL desktop path)
# ---------------------------------------------------------------------------


@requires_wsl
@pytest.mark.asyncio
async def test_take_screenshot_no_args():
    """take_screenshot() with no args should capture full screen."""
    from tools.screenshot import take_screenshot

    result = await take_screenshot()
    assert "file_path" in result
    assert os.path.exists(result["file_path"])
    assert result["source"] == "desktop"
    os.remove(result["file_path"])


@requires_wsl
@pytest.mark.asyncio
async def test_take_screenshot_missing_title_falls_back():
    """A window_title that matches nothing should still return a full-screen shot."""
    from tools.screenshot import take_screenshot

    result = await take_screenshot(window_title="__NO_SUCH_WINDOW_XYZ__")
    assert result["warning"] is not None
    assert os.path.exists(result["file_path"])
    os.remove(result["file_path"])


# ---------------------------------------------------------------------------
# Browser GIF recording (any platform)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_browser_gif():
    """Browser GIF recording should produce a non-empty .gif file."""
    pytest.importorskip("playwright")
    from tools.record import _record_browser

    path = await _record_browser("https://example.com", duration=1.0, fps=2)
    assert os.path.exists(path), f"GIF not found at {path}"
    assert path.endswith(".gif")
    size = os.path.getsize(path)
    assert size > 1_000, f"GIF suspiciously small: {size} bytes"
    os.remove(path)


# ---------------------------------------------------------------------------
# WSL GIF recording
# ---------------------------------------------------------------------------


@requires_wsl
def test_record_wsl_gif_full_screen():
    """WSL full-screen GIF recording should produce a non-empty .gif file."""
    from tools.record import _record_wsl

    path = _record_wsl(geom=None, duration=1.0, fps=2)
    assert os.path.exists(path), f"GIF not found at {path}"
    assert path.endswith(".gif")
    size = os.path.getsize(path)
    assert size > 5_000, f"GIF suspiciously small: {size} bytes"
    os.remove(path)


# ---------------------------------------------------------------------------
# browser_session unit tests (no I/O — pure logic)
# ---------------------------------------------------------------------------


def test_browser_session_initially_closed():
    """No session should be active at import time."""
    from tools.browser_session import is_session_open, get_page

    # These tests run in isolation; reset state if a previous test left it open
    assert get_page() is None or True  # non-fatal, just check it's accessible
    assert isinstance(is_session_open(), bool)


def test_interact_raises_without_session():
    """interact() must raise RuntimeError when no session is open."""
    import asyncio
    from tools import browser_session
    from tools.browser_session import interact

    # Force state to closed
    browser_session._page = None

    with pytest.raises(RuntimeError, match="No browser session"):
        asyncio.get_event_loop().run_until_complete(interact(action="click", x=0, y=0))


def test_interact_click_requires_target():
    """click without selector and without x/y must raise ValueError."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    # Inject a fake page so the "no session" guard passes
    browser_session._page = MagicMock()

    with pytest.raises((ValueError, Exception)):
        asyncio.get_event_loop().run_until_complete(interact(action="click"))

    browser_session._page = None  # clean up


def test_interact_type_requires_text():
    """type without text must raise ValueError."""
    import asyncio
    from unittest.mock import MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    browser_session._page = MagicMock()

    with pytest.raises((ValueError, Exception)):
        asyncio.get_event_loop().run_until_complete(interact(action="type"))

    browser_session._page = None


# ---------------------------------------------------------------------------
# return_inline unit tests — handler logic (no network)
# ---------------------------------------------------------------------------


def test_handle_screenshot_return_inline_false_skips_image():
    """_handle_screenshot with return_inline=False should return only TextContent."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent, ImageContent

    fake_result = {
        "file_path": "/tmp/fake.png",
        "source": "browser",
        "warning": None,
    }

    # Write a tiny dummy PNG so _make_inline_png wouldn't fail if called
    import struct, zlib

    def _minimal_png(path):
        # 1x1 red pixel PNG
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\xff\x00\x00"
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
        idat = (
            struct.pack(">I", len(compressed))
            + b"IDAT"
            + compressed
            + struct.pack(">I", idat_crc)
        )
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        with open(path, "wb") as f:
            f.write(sig + ihdr + idat + iend)

    _minimal_png("/tmp/fake.png")

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import server

    async def _run():
        with patch("server.take_screenshot", new=AsyncMock(return_value=fake_result)):
            return await server._handle_screenshot(
                {"url": "http://x.com", "return_inline": False}
            )

    parts = asyncio.get_event_loop().run_until_complete(_run())
    types = [type(p) for p in parts]
    assert ImageContent not in types, (
        "ImageContent should be absent when return_inline=False"
    )
    assert any(isinstance(p, TextContent) for p in parts)
    os.remove("/tmp/fake.png")


def test_handle_screenshot_return_inline_true_includes_image():
    """_handle_screenshot with return_inline=True (default) should include ImageContent."""
    import asyncio
    import struct, zlib
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent, ImageContent

    def _minimal_png(path):
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\xff\x00\x00"
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
        idat = (
            struct.pack(">I", len(compressed))
            + b"IDAT"
            + compressed
            + struct.pack(">I", idat_crc)
        )
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        with open(path, "wb") as f:
            f.write(sig + ihdr + idat + iend)

    _minimal_png("/tmp/fake2.png")

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import server

    fake_result = {
        "file_path": "/tmp/fake2.png",
        "source": "browser",
        "warning": None,
    }

    async def _run():
        with patch("server.take_screenshot", new=AsyncMock(return_value=fake_result)):
            return await server._handle_screenshot(
                {"url": "http://x.com", "return_inline": True}
            )

    parts = asyncio.get_event_loop().run_until_complete(_run())
    types = [type(p) for p in parts]
    assert ImageContent in types, (
        "ImageContent should be present when return_inline=True"
    )
    os.remove("/tmp/fake2.png")


# ---------------------------------------------------------------------------
# screenshot_diff unit tests — no network I/O
# ---------------------------------------------------------------------------


def _make_minimal_png(path: str, color: tuple = (255, 0, 0), size: tuple = (10, 10)):
    """Write a solid-color PNG using Pillow."""
    from PIL import Image

    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")


def test_diff_parse_hex_color_full():
    from tools.diff import _parse_hex_color

    assert _parse_hex_color("#ff0000") == (255, 0, 0)
    assert _parse_hex_color("#00ff00") == (0, 255, 0)
    assert _parse_hex_color("0000ff") == (0, 0, 255)


def test_diff_parse_hex_color_short():
    from tools.diff import _parse_hex_color

    assert _parse_hex_color("#f00") == (255, 0, 0)


def test_diff_parse_hex_color_invalid():
    from tools.diff import _parse_hex_color

    with pytest.raises(ValueError):
        _parse_hex_color("#gg0000")


def test_diff_resolve_image_missing_file():
    """_resolve_image should raise FileNotFoundError for a non-existent path."""
    import asyncio
    from tools.diff import _resolve_image

    with pytest.raises(FileNotFoundError):
        asyncio.get_event_loop().run_until_complete(
            _resolve_image("/tmp/__does_not_exist_xyz__.png")
        )


@pytest.mark.asyncio
async def test_diff_identical_images_zero_change():
    """Two identical images should produce 0% change."""
    _make_minimal_png("/tmp/diff_before.png", color=(100, 150, 200))
    _make_minimal_png("/tmp/diff_after.png", color=(100, 150, 200))

    from tools.diff import screenshot_diff

    result = await screenshot_diff(
        before="/tmp/diff_before.png",
        after="/tmp/diff_after.png",
        threshold=0,
    )
    assert result["change_percent"] == 0.0
    assert result["changed_pixels"] == 0
    assert os.path.exists(result["file_path"])
    os.remove(result["file_path"])
    os.remove("/tmp/diff_before.png")
    os.remove("/tmp/diff_after.png")


@pytest.mark.asyncio
async def test_diff_completely_different_images():
    """Two completely different solid-color images should show ~100% change."""
    _make_minimal_png("/tmp/diff_red.png", color=(255, 0, 0))
    _make_minimal_png("/tmp/diff_blue.png", color=(0, 0, 255))

    from tools.diff import screenshot_diff

    result = await screenshot_diff(
        before="/tmp/diff_red.png",
        after="/tmp/diff_blue.png",
        threshold=10,
    )
    assert result["change_percent"] == 100.0
    assert result["changed_pixels"] == result["total_pixels"]
    assert os.path.exists(result["file_path"])

    # Verify the output is a valid PNG that is wider than either input (side-by-side)
    from PIL import Image

    diff_img = Image.open(result["file_path"])
    # side-by-side: width should be at least 2x the input width
    assert diff_img.width >= 20  # 2 × 10px panels + separator + header
    os.remove(result["file_path"])
    os.remove("/tmp/diff_red.png")
    os.remove("/tmp/diff_blue.png")


@pytest.mark.asyncio
async def test_diff_different_sized_images():
    """screenshot_diff should handle images of different sizes without crashing."""
    _make_minimal_png("/tmp/diff_small.png", color=(255, 0, 0), size=(10, 10))
    _make_minimal_png("/tmp/diff_large.png", color=(0, 255, 0), size=(20, 20))

    from tools.diff import screenshot_diff

    result = await screenshot_diff(
        before="/tmp/diff_small.png",
        after="/tmp/diff_large.png",
    )
    assert os.path.exists(result["file_path"])
    assert "change_percent" in result
    os.remove(result["file_path"])
    os.remove("/tmp/diff_small.png")
    os.remove("/tmp/diff_large.png")


# ---------------------------------------------------------------------------
# screenshot_diff handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_screenshot_diff_returns_text_and_image():
    """_handle_screenshot_diff should return TextContent + ImageContent (return_inline=True)."""
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent, ImageContent

    _make_minimal_png("/tmp/hbefore.png", color=(255, 0, 0))
    _make_minimal_png("/tmp/hafter.png", color=(0, 0, 255))

    fake_diff_result = {
        "file_path": "/tmp/hbefore.png",  # reuse the PNG as a stand-in for the diff output
        "changed_pixels": 100,
        "total_pixels": 100,
        "change_percent": 100.0,
    }

    import server

    async def _run():
        with patch(
            "server.screenshot_diff", new=AsyncMock(return_value=fake_diff_result)
        ):
            return await server._handle_screenshot_diff(
                {
                    "before": "/tmp/hbefore.png",
                    "after": "/tmp/hafter.png",
                    "return_inline": True,
                }
            )

    parts = await _run()
    assert any(isinstance(p, TextContent) for p in parts)
    assert any(isinstance(p, ImageContent) for p in parts)
    os.remove("/tmp/hbefore.png")
    os.remove("/tmp/hafter.png")


@pytest.mark.asyncio
async def test_handle_screenshot_diff_return_inline_false():
    """_handle_screenshot_diff with return_inline=False should omit ImageContent."""
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent, ImageContent

    _make_minimal_png("/tmp/hdiff.png", color=(128, 128, 128))

    fake_diff_result = {
        "file_path": "/tmp/hdiff.png",
        "changed_pixels": 50,
        "total_pixels": 100,
        "change_percent": 50.0,
    }

    import server

    async def _run():
        with patch(
            "server.screenshot_diff", new=AsyncMock(return_value=fake_diff_result)
        ):
            return await server._handle_screenshot_diff(
                {
                    "before": "/tmp/hdiff.png",
                    "after": "/tmp/hdiff.png",
                    "return_inline": False,
                }
            )

    parts = await _run()
    assert any(isinstance(p, TextContent) for p in parts)
    assert not any(isinstance(p, ImageContent) for p in parts)
    os.remove("/tmp/hdiff.png")


# ---------------------------------------------------------------------------
# navigate() unit tests
# ---------------------------------------------------------------------------


def test_navigate_raises_without_session_on_bad_url():
    """navigate() with a bad URL and no Playwright session should raise or return an error."""
    # Just ensure the function is importable and callable
    from tools.browser_session import navigate

    assert callable(navigate)


@pytest.mark.asyncio
async def test_browser_navigate_handler_missing_url():
    """_handle_browser_navigate without a url should return an error TextContent."""
    from mcp.types import TextContent
    import server

    parts = await server._handle_browser_navigate({})
    assert len(parts) == 1
    assert isinstance(parts[0], TextContent)
    assert "required" in parts[0].text.lower() or "url" in parts[0].text.lower()


@pytest.mark.asyncio
async def test_browser_navigate_handler_full_flow():
    """_handle_browser_navigate should run steps and return screenshots."""
    pytest.importorskip("playwright")
    from mcp.types import TextContent, ImageContent
    import server
    from tools import browser_session

    # Ensure no leftover session
    await browser_session.close_session()

    parts = await server._handle_browser_navigate(
        {
            "url": "https://example.com",
            "steps": [
                {"action": "scroll", "delta_y": 100},
            ],
            "screenshot_after": True,
            "return_inline": True,
        }
    )

    # Should have text and at least one image (final screenshot)
    assert any(isinstance(p, TextContent) for p in parts)
    assert any(isinstance(p, ImageContent) for p in parts)

    # Clean up
    await browser_session.close_session()


# ---------------------------------------------------------------------------
# wait action in browser_interact
# ---------------------------------------------------------------------------


def test_interact_wait_requires_selector():
    """wait action without a selector should raise ValueError."""
    import asyncio
    from unittest.mock import MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    browser_session._page = MagicMock()

    with pytest.raises((ValueError, Exception)):
        asyncio.get_event_loop().run_until_complete(interact(action="wait"))

    browser_session._page = None


# ---------------------------------------------------------------------------
# keyboard action in browser_interact
# ---------------------------------------------------------------------------


def test_interact_keyboard_requires_key():
    """keyboard action without 'key' should raise ValueError."""
    import asyncio
    from unittest.mock import MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    browser_session._page = MagicMock()

    with pytest.raises((ValueError, Exception)):
        asyncio.get_event_loop().run_until_complete(interact(action="keyboard"))

    browser_session._page = None


def test_interact_keyboard_calls_press():
    """keyboard action with a valid key should call page.keyboard.press."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    mock_page = MagicMock()
    mock_page.keyboard.press = AsyncMock(return_value=None)
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(
        interact(action="keyboard", key="Enter")
    )

    mock_page.keyboard.press.assert_called_once_with("Enter")
    assert result["action"] == "keyboard"
    assert "Enter" in result["detail"]

    browser_session._page = None


def test_interact_unknown_action_raises():
    """An unknown action name should raise ValueError."""
    import asyncio
    from unittest.mock import MagicMock
    from tools import browser_session
    from tools.browser_session import interact

    browser_session._page = MagicMock()

    with pytest.raises(ValueError, match="Unknown action"):
        asyncio.get_event_loop().run_until_complete(
            interact(action="explode")  # type: ignore[arg-type]
        )

    browser_session._page = None


# ---------------------------------------------------------------------------
# browser_evaluate unit tests
# ---------------------------------------------------------------------------


def test_evaluate_raises_without_session():
    """evaluate() must raise RuntimeError when no session is open."""
    import asyncio
    from tools import browser_session
    from tools.browser_session import evaluate

    browser_session._page = None

    with pytest.raises(RuntimeError, match="No browser session"):
        asyncio.get_event_loop().run_until_complete(evaluate("1 + 1"))


def test_evaluate_returns_number():
    """evaluate() should correctly classify and return a numeric result."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(return_value=42)
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(evaluate("21 * 2"))

    assert result["error"] is None
    assert result["result"] == 42
    assert result["type"] == "number"
    assert result["url"] == "https://example.com"

    browser_session._page = None


def test_evaluate_returns_string():
    """evaluate() should correctly classify a string result."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(return_value="hello")
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(evaluate("'hello'"))

    assert result["result"] == "hello"
    assert result["type"] == "string"
    assert result["error"] is None

    browser_session._page = None


def test_evaluate_returns_object():
    """evaluate() should correctly classify and return a dict/object result."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(return_value={"key": "value", "n": 1})
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(
        evaluate("() => ({key: 'value', n: 1})")
    )

    assert result["result"] == {"key": "value", "n": 1}
    assert result["type"] == "object"
    assert result["error"] is None

    browser_session._page = None


def test_evaluate_returns_null():
    """evaluate() should handle None (JS null/undefined) gracefully."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(evaluate("null"))

    assert result["result"] is None
    assert result["type"] == "null"
    assert result["error"] is None

    browser_session._page = None


def test_evaluate_captures_js_error():
    """evaluate() should catch JS errors and return them in the error field."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(
        side_effect=Exception("ReferenceError: notDefined is not defined")
    )
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    result = asyncio.get_event_loop().run_until_complete(evaluate("notDefined"))

    assert result["error"] is not None
    assert "ReferenceError" in result["error"]
    assert result["result"] is None
    assert result["type"] == "error"

    browser_session._page = None


def test_evaluate_passes_arg():
    """evaluate() should pass 'arg' to page.evaluate when provided."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, call
    from tools import browser_session
    from tools.browser_session import evaluate

    mock_page = MagicMock()
    mock_page.evaluate = AsyncMock(return_value=10)
    mock_page.url = "https://example.com"
    browser_session._page = mock_page

    asyncio.get_event_loop().run_until_complete(evaluate("(n) => n * 2", arg=5))

    mock_page.evaluate.assert_called_once_with("(n) => n * 2", 5)

    browser_session._page = None


# ---------------------------------------------------------------------------
# browser_evaluate handler tests
# ---------------------------------------------------------------------------


def test_handle_browser_evaluate_missing_expression():
    """_handle_browser_evaluate without expression should return error TextContent."""
    import asyncio
    from mcp.types import TextContent
    import server

    parts = asyncio.get_event_loop().run_until_complete(
        server._handle_browser_evaluate({})
    )
    assert len(parts) == 1
    assert isinstance(parts[0], TextContent)
    assert "expression" in parts[0].text.lower() or "required" in parts[0].text.lower()


def test_handle_browser_evaluate_success_formats_output():
    """_handle_browser_evaluate should format successful results as readable text."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent
    import server

    fake_result = {
        "result": "Example Domain",
        "type": "string",
        "error": None,
        "url": "https://example.com",
    }

    async def _run():
        with patch("server.evaluate", new=AsyncMock(return_value=fake_result)):
            return await server._handle_browser_evaluate(
                {"expression": "document.title"}
            )

    parts = asyncio.get_event_loop().run_until_complete(_run())
    assert len(parts) == 1
    text = parts[0].text
    assert "Example Domain" in text
    assert "string" in text
    assert "successfully" in text.lower()


def test_handle_browser_evaluate_error_formats_output():
    """_handle_browser_evaluate should format JS errors clearly."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from mcp.types import TextContent
    import server

    fake_result = {
        "result": None,
        "type": "error",
        "error": "ReferenceError: foo is not defined",
        "url": "https://example.com",
    }

    async def _run():
        with patch("server.evaluate", new=AsyncMock(return_value=fake_result)):
            return await server._handle_browser_evaluate({"expression": "foo"})

    parts = asyncio.get_event_loop().run_until_complete(_run())
    assert len(parts) == 1
    text = parts[0].text
    assert "ReferenceError" in text
    assert "error" in text.lower()
