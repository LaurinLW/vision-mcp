"""
pdf tool — export the active browser page as a PDF.

Uses Playwright's page.pdf() which renders the page exactly as Chromium would
print it, including CSS print media queries.

Public API
----------
export_pdf(format, landscape, print_background, scale) -> dict
"""

from __future__ import annotations

import os
import time
from pathlib import Path

OUTPUT_DIR = Path(os.environ.get("VISION_OUTPUT_DIR", "/tmp/opencode-vision"))


def _ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _output_path() -> Path:
    ts = int(time.time() * 1000)
    return _ensure_output_dir() / f"pdf_{ts}.pdf"


def _require_page():
    from tools.browser_session import get_page

    page = get_page()
    if page is None:
        raise RuntimeError("No browser session is open. Call browser_open first.")
    return page


async def export_pdf(
    format: str = "A4",
    landscape: bool = False,
    print_background: bool = True,
    scale: float = 1.0,
) -> dict:
    """
    Export the active browser page as a PDF file.

    Parameters
    ----------
    format           : Paper size — "A4", "Letter", or "A3". Default: "A4".
    landscape        : Print in landscape orientation. Default: False.
    print_background : Include background colors and images. Default: True.
    scale            : CSS zoom level, 0.1–2.0. Default: 1.0.

    Returns
    -------
    dict with keys:
        file_path  : absolute path to the PDF file
        size_bytes : file size in bytes
        url        : page URL at time of export
    """
    page = _require_page()

    # Clamp scale to Playwright's supported range
    scale = max(0.1, min(scale, 2.0))

    valid_formats = {"A4", "Letter", "A3"}
    if format not in valid_formats:
        format = "A4"

    out = str(_output_path())

    await page.pdf(
        path=out,
        format=format,
        landscape=landscape,
        print_background=print_background,
        scale=scale,
    )

    size_bytes = os.path.getsize(out)

    return {
        "file_path": out,
        "size_bytes": size_bytes,
        "url": page.url,
    }
