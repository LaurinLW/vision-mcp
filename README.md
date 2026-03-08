# opencode-vision-mcp

An MCP server for [OpenCode](https://opencode.ai) that gives AI agents the ability to take **screenshots** and record short **animated GIFs** of running applications — both web pages (via headless Chromium) and native desktop windows.

## Why

Agents can read code and run tests, but they can't see the visual result of their changes. This server closes that loop: an agent can capture what the app looks like after a code change, inspect it, and iterate.

## Supported environments

| Capture target | Supported? |
|---|---|
| Browser URL (any platform) | Yes — headless Chromium via Playwright |
| Desktop full-screen (WSL) | Yes — via PowerShell `CopyFromScreen` on the Windows host |
| Desktop window by title (WSL) | Yes — `MainWindowTitle` substring match via PowerShell |

> Desktop capture requires WSL2 (Windows Subsystem for Linux). Native Linux, macOS, and bare Windows are not supported. Use `url` for browser-based capture on those platforms.

## Tools

### `screenshot`

Capture a PNG of a browser URL or desktop window.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | Open this URL in a headless browser and capture it. Takes priority over `window_title`. |
| `window_title` | string | Substring match against visible window titles (desktop, WSL only). |
| `delay` | number | Seconds to wait before capturing (default: `0`). |

Returns the `file_path` to a PNG and embeds the image inline (for vision-capable models).

### `record`

Record a short animated GIF of a browser URL or desktop window.

| Parameter | Type | Description |
|---|---|---|
| `url` | string | Open this URL in a headless browser and record it. |
| `window_title` | string | Substring match against visible window titles (desktop, WSL only). |
| `duration` | number | Seconds to record (default: `3`, max: `30`). |
| `fps` | integer | Frames per second (default: `5`, max: `30`). Keep low for smaller files. |

Returns the `file_path` to a GIF and embeds the first frame inline as a PNG.

## Install

### 1. Clone

```bash
git clone <this-repo> opencode-mcp
cd opencode-mcp
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browser (for web capture)

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

Once configured, reference the tools in your prompts:

```
Take a screenshot of http://localhost:3000 and tell me if the layout looks correct.
```

```
Record a 4-second GIF of the window titled "My App" so I can see the animation I just implemented.
```

```
Screenshot http://localhost:5173 before and after my change, then compare them.
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `VISION_OUTPUT_DIR` | `/tmp/opencode-vision` | Directory where screenshots and GIFs are saved. |

## WSL (Windows Subsystem for Linux)

The server detects WSL automatically via `/proc/version` and routes desktop capture through **PowerShell on the Windows host** using `CopyFromScreen` — no X server, no VcXsrv, no extra setup required.

- **Browser capture** (`url` param): Playwright runs headless inside WSL. `localhost` in WSL2 resolves to the Windows host, so `http://localhost:3000` works as expected.
- **Desktop full-screen**: captured from the Windows desktop via PowerShell.
- **Window by title**: PowerShell finds the window by `MainWindowTitle` substring match and captures only that region.
- **Window by PID**: not supported — WSL PIDs differ from Windows PIDs. Use `window_title` instead.

No additional dependencies are needed: `powershell.exe` is always available at `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`.

## Running tests

```bash
pip install pytest pytest-asyncio
pytest tests/test_vision.py -v
```

Desktop tests are skipped automatically when not running inside WSL. Browser tests require Playwright + Chromium (`playwright install chromium`).

## Project structure

```
opencode-mcp/
├── server.py           # MCP server entry point
├── requirements.txt    # Python dependencies
├── tests/
│   └── test_vision.py  # pytest suite
└── tools/
    ├── __init__.py
    ├── window.py       # Window geometry lookup (WSL/PowerShell)
    ├── screenshot.py   # screenshot tool implementation
    └── record.py       # record tool implementation
```
