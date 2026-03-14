# opencode-vision-mcp

An MCP server for [OpenCode](https://opencode.ai) that gives AI agents the ability to **see** running applications — taking screenshots, recording GIFs, interacting with pages, diffing before/after states, and executing JavaScript — all from within a coding session.

[![CI](https://github.com/LaurinLW/vision-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/LaurinLW/vision-mcp/actions/workflows/ci.yml)

## Why

Agents can read code and run tests, but they can't see the visual result of their changes. This server closes that loop: an agent can open a browser, click around, capture what the app looks like, compare before/after states, read JS state, and iterate — without any human in the loop.

## Supported environments

| Capture target | Supported? |
|---|---|
| Browser URL (any platform) | Yes — headless Chromium via Playwright |
| Desktop full-screen (WSL) | Yes — via PowerShell `CopyFromScreen` on the Windows host |
| Desktop window by title (WSL) | Yes — `MainWindowTitle` substring match via PowerShell |

> Desktop capture requires WSL2 (Windows Subsystem for Linux). Native Linux, macOS, and bare Windows are not supported for desktop capture. Use `url` for browser-based capture on those platforms.

## Tools

### `screenshot`

Capture a PNG of a browser URL or desktop window.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | Open this URL in a headless browser and capture it. Takes priority over `window_title`. |
| `window_title` | string | Substring match against visible window titles (desktop, WSL only). |
| `delay` | number | Seconds to wait before capturing (default: `0`). |
| `return_inline` | boolean | Embed the image inline for vision models (default: `true`). |

### `record`

Record a short animated GIF of a browser URL or desktop window.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | Open this URL in a headless browser and record it. |
| `window_title` | string | Substring match against visible window titles (desktop, WSL only). |
| `duration` | number | Seconds to record (default: `3`, max: `30`). |
| `fps` | integer | Frames per second (default: `5`, max: `30`). Keep low for smaller files. |
| `return_inline` | boolean | Embed the first frame inline (default: `true`). |

### `screenshot_diff`

Compute a visual diff between two images and return a **side-by-side PNG** with changed pixels highlighted. Accepts file paths or URLs as inputs.

| Parameter | Type | Description |
|---|---|---|
| `before` | string | File path or URL of the "before" image. |
| `after` | string | File path or URL of the "after" image. |
| `highlight_color` | string | Hex color for changed pixels (default: `#ff0000`). |
| `threshold` | integer | Per-channel diff threshold 0–255; higher = ignore minor rendering noise (default: `10`). |
| `return_inline` | boolean | Embed the diff image inline (default: `true`). |

Returns the diff `file_path` plus `changed_pixels`, `total_pixels`, and `change_percent`.

---

### Persistent browser session

The following tools share a single long-lived Playwright browser session so you can open a page, interact with it across multiple steps, and close it when done.

#### `browser_open`

Open a persistent Playwright browser session and navigate to a URL. If a session is already open it is replaced.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | URL to navigate to. |
| `width` | integer | Viewport width in pixels (default: `1280`). |
| `height` | integer | Viewport height in pixels (default: `900`). |

#### `browser_close`

Close the active browser session and free all resources.

#### `browser_screenshot`

Take a screenshot of the currently active browser session page.

| Parameter | Type | Description |
|---|---|---|
| `delay` | number | Seconds to wait before capturing (default: `0`). |
| `return_inline` | boolean | Embed the image inline (default: `true`). |

#### `browser_record`

Record a GIF of the currently active browser session page.

| Parameter | Type | Description |
|---|---|---|
| `duration` | number | Seconds to record (default: `3`, max: `30`). |
| `fps` | integer | Frames per second (default: `5`, max: `30`). |
| `return_inline` | boolean | Embed the first frame inline (default: `true`). |

#### `browser_interact`

Perform a single interaction on the active page.

| Parameter | Type | Description |
|---|---|---|
| `action` | enum | `click` \| `type` \| `scroll` \| `hover` \| `wait` \| `keyboard` |
| `selector` | string | CSS selector (takes priority over `x`/`y`). |
| `x`, `y` | number | Page coordinates (when no selector). |
| `text` | string | Text to fill. Required for `type`. |
| `key` | string | Key to press, e.g. `Enter`, `Escape`, `Control+z`. Required for `keyboard`. |
| `delta_x`, `delta_y` | number | Scroll amount in pixels. Used with `scroll`. |
| `timeout` | number | Max wait in ms. Used with `wait` (default: `5000`). |

**`keyboard` key examples:** `Enter`, `Escape`, `Tab`, `Backspace`, `ArrowDown`, `Control+a`, `Control+z`, `Meta+r`, `Shift+Tab`, `F5`.

#### `browser_navigate`

Navigate to a URL and run an optional sequence of interactions in a **single tool call** — replaces the pattern of `browser_open` + N × `browser_interact` + `browser_screenshot`. Reuses an open session if available.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | URL to navigate to. |
| `steps` | array | Ordered interaction steps (same fields as `browser_interact`, plus `screenshot: true` to capture after that step). |
| `screenshot_after` | boolean | Take a final screenshot after all steps (default: `true`). |
| `wait_for` | enum | Page load event: `networkidle` \| `domcontentloaded` \| `load` (default: `networkidle`). |
| `width`, `height` | integer | Viewport size (only used when opening a new session). |
| `return_inline` | boolean | Embed screenshots inline (default: `true`). |

#### `browser_evaluate`

Execute JavaScript in the active page context and return the result. Never crashes the tool call — JS errors are returned in the `error` field.

| Parameter | Type | Description |
|---|---|---|
| `expression` | string | JS expression or function, e.g. `document.title`, `() => localStorage.getItem('token')`. |
| `arg` | any | Optional JSON-serializable argument passed to the function. |

Returns `result`, `type` (`"string"`, `"number"`, `"boolean"`, `"object"`, `"null"`), `error`, and `url`.

---

## Install

### 1. Clone

```bash
git clone https://github.com/LaurinLW/vision-mcp.git opencode-mcp
cd opencode-mcp
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browser

```bash
playwright install chromium
```

## Configure OpenCode

Add to your `opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "vision": {
      "type": "local",
      "command": ["python", "/absolute/path/to/opencode-mcp/server.py"],
      "enabled": true
    }
  }
}
```

Replace `/absolute/path/to/opencode-mcp` with the actual path where you cloned this repo.

## Usage examples

```
Take a screenshot of http://localhost:3000 and tell me if the layout looks correct.
```

```
Open http://localhost:5173, click the login button, fill in the credentials, submit the form,
and show me a screenshot of where I land.
```

```
Screenshot http://localhost:3000 before and after my CSS change, then diff them so I can
see exactly what pixels moved.
```

```
Run document.querySelectorAll('.error').length in the page and tell me how many error
elements are currently visible.
```

```
Record a 3-second GIF of the animation I just implemented at http://localhost:3000/demo.
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `VISION_OUTPUT_DIR` | `/tmp/opencode-vision` | Directory where screenshots and GIFs are saved. |

## WSL (Windows Subsystem for Linux)

The server detects WSL automatically via `/proc/version` and routes desktop capture through **PowerShell on the Windows host** — no X server or VcXsrv required.

- **Browser capture** (`url` param): Playwright runs headless inside WSL. `localhost` in WSL2 resolves to the Windows host, so `http://localhost:3000` works as expected.
- **Desktop full-screen**: captured from the Windows desktop via PowerShell `CopyFromScreen`.
- **Window by title**: PowerShell finds the window by `MainWindowTitle` substring match and captures only that region.

## Running tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

Desktop tests are skipped automatically when not running inside WSL. Browser tests require Playwright + Chromium (`playwright install chromium`). The CI pipeline runs the full suite on every push.

## Project structure

```
opencode-mcp/
├── server.py                   # MCP server entry point + tool definitions + handlers
├── requirements.txt            # Python dependencies
├── .github/workflows/ci.yml   # GitHub Actions CI (Python 3.11 + 3.12)
├── tests/
│   └── test_vision.py          # pytest suite
└── tools/
    ├── __init__.py
    ├── window.py               # Window geometry lookup (WSL/PowerShell)
    ├── screenshot.py           # screenshot tool implementation
    ├── record.py               # record tool implementation
    ├── diff.py                 # screenshot_diff implementation
    └── browser_session.py      # Persistent Playwright session + interact/navigate/evaluate
```
