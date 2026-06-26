"""Colored, well-spaced backend audit log for the Cinch demo terminal.

This is the "proof" feed: every line corresponds to a real Azure call. Colors are
enabled only when stdout is an interactive console (so the live demo window is
colorized, while captured/piped output stays clean plain text).
"""

from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger("cinch")

_USE = sys.stdout.isatty() and os.environ.get("CINCH_NO_COLOR") != "1"
if os.name == "nt" and _USE:
    os.system("")  # enable ANSI escape processing on Windows consoles


def _c(code: str) -> str:
    return code if _USE else ""


RESET = _c("\033[0m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RED = _c("\033[91m")
GRN = _c("\033[92m")
YEL = _c("\033[93m")
BLU = _c("\033[94m")
MAG = _c("\033[95m")
CYN = _c("\033[96m")
GRY = _c("\033[90m")
WHT = _c("\033[97m")


def section(title: str, sub: str = "") -> None:
    _log.info("")
    _log.info(f"{CYN}{BOLD}━━ {title} {RESET}{GRY}{sub}{RESET}")


def tag(name: str, text: str) -> None:
    _log.info(f"{CYN}{BOLD}{name:<5}{RESET} {WHT}{text}{RESET}")


def grant(name: str, scope: str) -> None:
    _log.info(f"   {GRY}•{RESET} {WHT}{name:<32}{RESET} {GRY}{scope}{RESET}")


def usage(op: str, count: int, res: str) -> None:
    _log.info(f"   {GRN}•{RESET} {GRN}{op:<5}{RESET}{DIM}×{count}{RESET}  {GRY}{res}{RESET}")


def keep(name: str, scope: str, ops: str) -> None:
    _log.info(f"   {GRN}✓ keep{RESET}  {WHT}{name:<30}{RESET} {GRY}{scope}{RESET}  {GRN}{ops}{RESET}")


def cut(name: str, scope: str) -> None:
    _log.info(f"   {RED}✗ cut {RESET}  {DIM}{name:<30}{RESET} {GRY}{scope}{RESET}")


def cmd(text: str) -> None:
    _log.info(f"   {DIM}$ {text}{RESET}")


def cmd_result(ok: bool, text: str) -> None:
    sym = f"{GRN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    _log.info(f"     {sym} {GRY}{text}{RESET}")


def result(text: str) -> None:
    _log.info(f"{DIM}{text}{RESET}")
