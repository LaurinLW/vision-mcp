"""
record tool — capture a short GIF of a browser URL or desktop window.

Capture backends:
  - Browser (any platform): Playwright headless Chromium screenshot loop
  - Desktop, WSL:           PowerShell CopyFromScreen frame loop on the Windows host
"""

from __future__ import annotations

import asyncio
import io
import os
import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from tools.window import get_window_geometry, is_wsl
from tools.screenshot import _screenshot_wsl

OUTPUT_DIR = Path(os.environ.get("VISION_OUTPUT_DIR", "/tmp/opencode-vision"))


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _output_path(prefix: str, ext: str) -> Path:
    ts = int(time.time() * 1000)
    return _ensure_output_dir() / f"{prefix}_{ts}.{ext}"


def _frames_to_gif(frames: list[Image.Image], out: str, fps: int) -> None:
    """Save a list of PIL Images as an animated GIF."""
    if not frames:
        raise ValueError("No frames captured.")
    duration_ms = max(1, int(1000 / fps))
    frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=duration_ms,
        optimize=False,
    )


def _png_path_to_pil(path: str) -> Image.Image:
    """Load a PNG from disk as a quantized PIL Image suitable for GIF assembly."""
    return Image.open(path).convert("RGB").quantize(colors=256)


# ---------------------------------------------------------------------------
# Browser recording via Playwright (screenshot loop)
# ---------------------------------------------------------------------------


async def _record_browser(url: str, duration: float, fps: int) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )

    interval = 1.0 / fps
    frames: list[Image.Image] = []
    out = str(_output_path("browser_rec", "gif"))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(url, wait_until="networkidle", timeout=30_000)

        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            png_bytes = await page.screenshot()
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            frames.append(img.quantize(colors=256))
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(interval, remaining))

        await browser.close()

    _frames_to_gif(frames, out, fps)
    return out


# ---------------------------------------------------------------------------
# Session-based recording (uses an existing Playwright Page)
# ---------------------------------------------------------------------------


async def _record_page(page: Any, duration: float, fps: int) -> str:
    """Record a GIF from an already-open Playwright page."""
    interval = 1.0 / fps
    frames: list[Image.Image] = []
    out = str(_output_path("session_rec", "gif"))

    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        png_bytes = await page.screenshot()
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        frames.append(img.quantize(colors=256))
        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(interval, remaining))

    _frames_to_gif(frames, out, fps)
    return out


# ---------------------------------------------------------------------------
# WSL recording — PowerShell CopyFromScreen frame loop
# ---------------------------------------------------------------------------


def _record_wsl(
    geom: Optional[tuple[int, int, int, int]],
    duration: float,
    fps: int,
) -> str:
    """Capture frames via PowerShell on the Windows host and assemble a GIF."""
    interval = 1.0 / fps
    frames: list[Image.Image] = []
    out = str(_output_path("wsl_rec", "gif"))

    kwargs: dict = {}
    if geom is not None:
        left, top, width, height = geom
        kwargs = {"left": left, "top": top, "width": width, "height": height}

    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        png_path = _screenshot_wsl(**kwargs)
        frames.append(_png_path_to_pil(png_path))
        try:
            os.remove(png_path)
        except OSError:
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))

    _frames_to_gif(frames, out, fps)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def record_gif(
    url: Optional[str] = None,
    window_title: Optional[str] = None,
    duration: float = 3.0,
    fps: int = 5,
) -> dict:
    """
    Record a GIF and return a dict with:
      - file_path: absolute path to the GIF
      - source: "browser" | "wsl"
      - frame_count: number of frames captured
      - warning: optional string if a fallback occurred
    """
    warning: Optional[str] = None

    if url is not None:
        file_path = await _record_browser(url, duration=duration, fps=fps)
        source = "browser"
    else:
        if not is_wsl():
            raise RuntimeError(
                "Desktop recording is only supported in WSL. "
                "Provide a 'url' to use browser recording instead."
            )

        # Resolve window geometry
        geom: Optional[tuple[int, int, int, int]] = None
        if window_title is not None:
            geom = get_window_geometry(window_title)
            if geom is None:
                warning = f"Window '{window_title}' not found — recording full screen instead."

        file_path = _record_wsl(geom, duration=duration, fps=fps)
        source = "wsl"

    frame_count = max(1, int(duration * fps))

    return {
        "file_path": file_path,
        "source": source,
        "frame_count": frame_count,
        "warning": warning,
    }
