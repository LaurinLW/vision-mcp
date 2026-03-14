"""
diff tool — compute a visual diff between two screenshots.

Given a "before" and "after" image (file paths or URLs), produces a
side-by-side PNG where changed pixels in the "after" image are highlighted
in red.  Returns the diff file path plus statistics about what changed.

Public API
----------
screenshot_diff(before, after, highlight_color, return_inline) -> dict
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Tuple

OUTPUT_DIR = Path(os.environ.get("VISION_OUTPUT_DIR", "/tmp/opencode-vision"))


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _output_path(prefix: str, ext: str) -> Path:
    ts = int(time.time() * 1000)
    return _ensure_output_dir() / f"{prefix}_{ts}.{ext}"


def _parse_hex_color(hex_color: str) -> Tuple[int, int, int]:
    """Parse a #RRGGBB hex string to an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color!r}")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b)


async def _resolve_image(source: str):
    """
    Given a file path or URL, return a PIL Image in RGB mode.
    URLs are screenshotted via Playwright.
    """
    from PIL import Image

    if source.startswith("http://") or source.startswith("https://"):
        # Take a browser screenshot and load it
        from tools.screenshot import _screenshot_browser

        path = await _screenshot_browser(source)
        img = Image.open(path).convert("RGB")
        # Clean up the temp file — we have it in memory
        try:
            os.remove(path)
        except OSError:
            pass
        return img
    else:
        if not os.path.exists(source):
            raise FileNotFoundError(f"Image file not found: {source!r}")
        return Image.open(source).convert("RGB")


async def screenshot_diff(
    before: str,
    after: str,
    highlight_color: str = "#ff0000",
    threshold: int = 10,
) -> dict:
    """
    Compute a visual diff between two images and produce a side-by-side PNG.

    Parameters
    ----------
    before          : file path or URL of the "before" image
    after           : file path or URL of the "after" image
    highlight_color : hex color used to highlight changed pixels (default: red)
    threshold       : per-channel difference threshold (0-255) below which a pixel
                      is considered unchanged. Default 10 avoids JPEG/subpixel noise.

    Returns
    -------
    dict with keys:
        file_path       : absolute path to the side-by-side diff PNG
        changed_pixels  : number of pixels that changed
        total_pixels    : total pixel count
        change_percent  : float percentage of pixels that changed
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFont
    import numpy as np

    hi_color = _parse_hex_color(highlight_color)

    before_img = await _resolve_image(before)
    after_img = await _resolve_image(after)

    # Normalise dimensions — pad smaller image with white to match the larger one
    bw, bh = before_img.size
    aw, ah = after_img.size
    w = max(bw, aw)
    h = max(bh, ah)

    if before_img.size != (w, h):
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(before_img, (0, 0))
        before_img = canvas

    if after_img.size != (w, h):
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(after_img, (0, 0))
        after_img = canvas

    # Per-pixel difference
    diff = ImageChops.difference(before_img, after_img)

    # Build boolean mask: pixel is "changed" if any channel exceeds threshold
    diff_arr = np.array(diff)  # shape (h, w, 3), dtype uint8
    mask = np.any(diff_arr > threshold, axis=2)  # shape (h, w), dtype bool

    changed_pixels = int(mask.sum())
    total_pixels = w * h
    change_percent = (
        round(changed_pixels / total_pixels * 100, 2) if total_pixels else 0.0
    )

    # Create highlighted-after image: blend changed pixels with highlight color
    after_arr = np.array(after_img).copy()
    alpha = 0.55  # how much of the highlight color to mix in
    after_arr[mask] = (
        ((1 - alpha) * after_arr[mask] + alpha * np.array(hi_color, dtype=float))
        .clip(0, 255)
        .astype("uint8")
    )

    highlighted_after = Image.fromarray(after_arr, mode="RGB")

    # --- Side-by-side layout ---
    # Add a header strip above each panel and a thin separator between them
    header_h = 28
    sep_w = 4
    panel_w = w
    panel_h = h

    total_w = panel_w * 2 + sep_w
    total_h = panel_h + header_h

    canvas = Image.new("RGB", (total_w, total_h), (30, 30, 30))

    # Header labels
    draw = ImageDraw.Draw(canvas)
    try:
        # Try to use a default system font (may not be available everywhere)
        from PIL import ImageFont

        font = ImageFont.load_default()
    except Exception:
        font = None

    label_before = "BEFORE"
    label_after = f"AFTER  ({change_percent}% changed)"

    # Draw header text centred in each panel
    for label, x_offset in [(label_before, 0), (label_after, panel_w + sep_w)]:
        # Use textbbox if available (Pillow >= 9.2.0), else fall back to textsize
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(label, font=font)  # type: ignore[attr-defined]
        tx = x_offset + (panel_w - tw) // 2
        ty = (header_h - th) // 2
        draw.text((tx, ty), label, fill=(220, 220, 220), font=font)

    # Paste the before / highlighted-after panels below the headers
    canvas.paste(before_img, (0, header_h))
    canvas.paste(highlighted_after, (panel_w + sep_w, header_h))

    # Separator line (slightly lighter grey)
    for x in range(panel_w, panel_w + sep_w):
        for y in range(total_h):
            canvas.putpixel((x, y), (80, 80, 80))

    out = str(_output_path("diff", "png"))
    canvas.save(out, format="PNG")

    return {
        "file_path": out,
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "change_percent": change_percent,
    }
