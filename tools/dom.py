"""
dom tool — extract structured content from the active browser page.

Reads the DOM via Playwright and returns:
  - page title
  - plain text body content (truncated to max_text_length)
  - all links (text + href)
  - all form inputs (tag, name, type, placeholder, value, id)
  - headings h1–h3 (level + text)

Public API
----------
get_dom(selector_scope, max_text_length) -> dict
"""

from __future__ import annotations

from typing import Any


def _require_page() -> Any:
    from tools.browser_session import get_page

    page = get_page()
    if page is None:
        raise RuntimeError("No browser session is open. Call browser_open first.")
    return page


async def get_dom(
    selector_scope: str = "body",
    max_text_length: int = 5000,
) -> dict:
    """
    Extract structured DOM content from the active browser page.

    Parameters
    ----------
    selector_scope  : CSS selector that scopes all extraction. Default: "body".
                      Use "main", "#content", etc. to narrow to a specific region.
    max_text_length : Maximum characters of plain text to return. Text beyond this
                      limit is truncated and a note is appended. Default: 5000.

    Returns
    -------
    dict with keys:
        url       : current page URL
        title     : page <title> text
        text      : plain text content of the scoped element, possibly truncated
        truncated : True if the text was truncated
        links     : list of {text, href} dicts for all <a> tags in scope
        inputs    : list of {tag, name, type, placeholder, value, id} for form fields
        headings  : list of {level, text} for h1–h3 in scope
    """
    page = _require_page()

    title: str = await page.title()

    # Plain text — inner_text() strips HTML tags and collapses whitespace
    try:
        raw_text: str = await page.inner_text(selector_scope)
    except Exception:
        raw_text = ""

    truncated = False
    if len(raw_text) > max_text_length:
        raw_text = raw_text[:max_text_length]
        truncated = True

    # Links — evaluate JS in page context for speed (one round-trip)
    links: list[dict] = await page.evaluate(
        """(scope) => {
            const root = document.querySelector(scope) || document.body;
            return Array.from(root.querySelectorAll('a[href]'))
                .map(a => ({
                    text: (a.innerText || a.textContent || '').trim(),
                    href: a.href,
                }))
                .filter(l => l.href && !l.href.startsWith('javascript:'));
        }""",
        selector_scope,
    )

    # Form inputs — input, textarea, select
    inputs: list[dict] = await page.evaluate(
        """(scope) => {
            const root = document.querySelector(scope) || document.body;
            return Array.from(root.querySelectorAll('input, textarea, select'))
                .map(el => ({
                    tag:         el.tagName.toLowerCase(),
                    name:        el.name        || '',
                    type:        el.type        || '',
                    placeholder: el.placeholder || '',
                    value:       el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                                     ? (el.value || '') : '',
                    id:          el.id          || '',
                }));
        }""",
        selector_scope,
    )

    # Headings h1–h3
    headings: list[dict] = await page.evaluate(
        """(scope) => {
            const root = document.querySelector(scope) || document.body;
            return Array.from(root.querySelectorAll('h1, h2, h3'))
                .map(h => ({
                    level: parseInt(h.tagName[1]),
                    text:  (h.innerText || h.textContent || '').trim(),
                }))
                .filter(h => h.text);
        }""",
        selector_scope,
    )

    return {
        "url": page.url,
        "title": title,
        "text": raw_text,
        "truncated": truncated,
        "links": links,
        "inputs": inputs,
        "headings": headings,
    }
