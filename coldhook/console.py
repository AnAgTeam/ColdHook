"""Compact, user-facing CLI output.

Diagnostic logging lives in :mod:`coldhook.diagnostics`; this module is only
for progress and results that are useful during a normal ColdHook run.
"""
from __future__ import annotations

import os
import sys


def _colors() -> tuple[str, str, str, str, str]:
    # ColdHook is commonly run through tee while the user still watches the
    # terminal. Keep Theos-style colors in that case; NO_COLOR is the explicit
    # opt-out for plain output and log files.
    enabled = os.name != "nt" and not os.environ.get("NO_COLOR")
    if not enabled:
        return "", "", "", "", ""
    return "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m"


C_CYAN, C_RED, C_GREEN, C_YELL, C_RST = _colors()


def stage(message: str) -> None:
    print(f"{C_CYAN}==> {message}{C_RST}", flush=True)


def progress(current: int, total: int, path: str) -> None:
    width = len(str(total))
    print(f"[{current:>{width}}/{total}] {path}", flush=True)


def detail(message: str) -> None:
    print(f"    {message}")


def applied(message: str) -> None:
    print(f"{C_GREEN}    ✓ {message}{C_RST}")


def not_applied(message: str) -> None:
    print(f"{C_YELL}    - {message}{C_RST}")


def success(message: str) -> None:
    print(f"{C_GREEN}==> {message}{C_RST}")


def warning(message: str) -> None:
    print(f"{C_YELL}warning: {message}{C_RST}", file=sys.stderr)


def error(message: str) -> None:
    _, red, _, _, reset = _colors()
    print(f"{red}error: {message}{reset}", file=sys.stderr)
