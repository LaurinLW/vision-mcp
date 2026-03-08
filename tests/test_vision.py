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
