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
