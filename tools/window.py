"""
Window geometry lookup via PowerShell on the Windows host (WSL only).
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def is_wsl() -> bool:
    """Return True if running inside Windows Subsystem for Linux."""
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _powershell_path() -> str:
    """Return the path to powershell.exe, preferring the explicit WSL mount."""
    explicit = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.exists(explicit):
        return explicit
    return "powershell.exe"


def _run_powershell(script: str, timeout: int = 10) -> Optional[str]:
    """Run a PowerShell script and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            [_powershell_path(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# NOTE: uses __TITLE__ as placeholder to avoid Python str.format() conflicts
#       with PowerShell's own curly-brace syntax.
_PS_FIND_WINDOW = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$title = '__TITLE__'
$proc = Get-Process | Where-Object {
    $_.MainWindowTitle -like "*$title*" -and $_.MainWindowHandle -ne 0
} | Select-Object -First 1
if ($null -eq $proc) { Write-Output "0 0 0 0"; exit 1 }
$rect = New-Object Win32+RECT
$ok = [Win32]::GetWindowRect($proc.MainWindowHandle, [ref]$rect)
if (-not $ok) { Write-Output "0 0 0 0"; exit 1 }
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
if ($w -le 0 -or $h -le 0) { Write-Output "0 0 0 0"; exit 1 }
Write-Output "$($rect.Left) $($rect.Top) $w $h"
"""


def get_window_geometry(title: str) -> Optional[tuple[int, int, int, int]]:
    """
    Return (left, top, width, height) for the first Windows window whose
    MainWindowTitle contains `title` (case-insensitive substring match).
    Returns None if not found or PowerShell is unreachable.
    """
    safe_title = title.replace("'", "''")
    script = _PS_FIND_WINDOW.replace("__TITLE__", safe_title)
    out = _run_powershell(script)
    if not out:
        return None
    try:
        parts = out.strip().split()
        left, top, width, height = (
            int(parts[0]),
            int(parts[1]),
            int(parts[2]),
            int(parts[3]),
        )
        if width > 0 and height > 0:
            return (left, top, width, height)
    except (ValueError, IndexError):
        pass
    return None
