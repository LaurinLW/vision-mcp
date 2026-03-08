"""
screenshot tool — capture a PNG of a browser URL or desktop window.

Backends:
  - Browser: Playwright headless Chromium (any platform)
  - Desktop: PowerShell CopyFromScreen on the Windows host (WSL only)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from tools.window import _run_powershell, get_window_geometry

OUTPUT_DIR = Path(os.environ.get("VISION_OUTPUT_DIR", "/tmp/opencode-vision"))


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _output_path(prefix: str, ext: str) -> Path:
    ts = int(time.time() * 1000)
    return _ensure_output_dir() / f"{prefix}_{ts}.{ext}"


# ---------------------------------------------------------------------------
# Browser screenshot via Playwright
# ---------------------------------------------------------------------------


async def _screenshot_browser(url: str, delay: float = 0) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. "
            "Run: pip install playwright && playwright install chromium"
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(url, wait_until="networkidle", timeout=30_000)
        if delay > 0:
            await asyncio.sleep(delay)
        out = str(_output_path("browser", "png"))
        await page.screenshot(path=out, full_page=False)
        await browser.close()
    return out


# ---------------------------------------------------------------------------
# Desktop screenshot via PowerShell CopyFromScreen (WSL)
# ---------------------------------------------------------------------------

# LEFT/TOP/WIDTH/HEIGHT == 0 means "capture full primary screen".
_PS_CAPTURE = r"""
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
$left   = __LEFT__
$top    = __TOP__
$width  = __WIDTH__
$height = __HEIGHT__
if ($width -eq 0 -or $height -eq 0) {
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $left   = $screen.Left
    $top    = $screen.Top
    $width  = $screen.Width
    $height = $screen.Height
}
$bmp = New-Object System.Drawing.Bitmap($width, $height)
$g   = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($left, $top, 0, 0, $bmp.Size)
$g.Dispose()
$tmp = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.png'
$bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output $tmp
"""


def _win_path_to_wsl(win_path: str) -> str:
    """Convert C:\\Users\\foo\\bar.png  →  /mnt/c/Users/foo/bar.png"""
    p = win_path.strip().replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        drive = p[0].lower()
        rest = p[2:].lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return p


def _screenshot_wsl(
    left: int = 0, top: int = 0, width: int = 0, height: int = 0
) -> str:
    """Capture a region (or full screen) via PowerShell; return a local PNG path."""
    script = (
        _PS_CAPTURE.replace("__LEFT__", str(left))
        .replace("__TOP__", str(top))
        .replace("__WIDTH__", str(width))
        .replace("__HEIGHT__", str(height))
    )
    win_path = _run_powershell(script, timeout=15)
    if not win_path:
        raise RuntimeError(
            "PowerShell screen capture failed. "
            "Make sure powershell.exe is accessible from WSL."
        )
    wsl_path = _win_path_to_wsl(win_path)
    if not os.path.exists(wsl_path):
        raise RuntimeError(
            f"PowerShell wrote to '{win_path}' but it is not visible at '{wsl_path}'. "
            "Check that the Windows C: drive is mounted at /mnt/c."
        )
    out = str(_output_path("desktop", "png"))
    shutil.copy2(wsl_path, out)
    try:
        os.remove(wsl_path)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# Session-based screenshot (uses an existing Playwright Page)
# ---------------------------------------------------------------------------


async def _screenshot_page(page: Any, delay: float = 0) -> str:
    """Take a screenshot of an already-open Playwright page."""
    if delay > 0:
        await asyncio.sleep(delay)
    out = str(_output_path("session", "png"))
    await page.screenshot(path=out, full_page=False)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def take_screenshot(
    url: Optional[str] = None,
    window_title: Optional[str] = None,
    delay: float = 0,
) -> dict:
    """
    Capture a screenshot and return:
      file_path : absolute path to the PNG
      source    : "browser" | "desktop"
      warning   : str or None
    """
    warning: Optional[str] = None

    if url is not None:
        file_path = await _screenshot_browser(url, delay=delay)
        source = "browser"
    else:
        if delay > 0:
            time.sleep(delay)

        geom: Optional[tuple[int, int, int, int]] = None
        if window_title is not None:
            geom = get_window_geometry(window_title)
            if geom is None:
                warning = (
                    f"Window '{window_title}' not found — captured full screen instead."
                )

        if geom is not None:
            left, top, width, height = geom
            file_path = _screenshot_wsl(left, top, width, height)
        else:
            file_path = _screenshot_wsl()

        source = "desktop"

    return {"file_path": file_path, "source": source, "warning": warning}
