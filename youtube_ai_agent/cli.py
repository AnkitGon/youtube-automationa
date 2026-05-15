"""
TubeAssistant — CLI entry point.

Usage:
    tube-assistant              # interactive TUI menu
    tube-assistant onboard      # first-time setup wizard
    tube-assistant start        # run the daemon
    tube-assistant run          # one-shot pipeline
    tube-assistant status       # workspace summary
    tube-assistant workspace    # print workspace path
"""

import os
import sys
import subprocess
import json
from pathlib import Path

from youtube_ai_agent._workspace import get as get_workspace, scaffold


# ── cross-platform key reader ─────────────────────────────────────────────────

def _read_key() -> str:
    """Return 'UP', 'DOWN', 'ENTER', or 'ESC'."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H": return "UP"
            if ch2 == "P": return "DOWN"
            return ""
        if ch == "\r":  return "ENTER"
        if ch == "\x1b": return "ESC"
        return ""
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A": return "UP"
                    if ch3 == "B": return "DOWN"
                return "ESC"
            if ch in ("\r", "\n"): return "ENTER"
            if ch == "\x03": raise KeyboardInterrupt
            return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ── TUI menu ──────────────────────────────────────────────────────────────────

_MENU_ITEMS = [
    ("Start daemon",   "start"),
    ("One-shot video", "run"),
    ("Setup wizard",   "onboard"),
    ("Status",         "status"),
    ("Quit",           None),
]


def _tui_menu() -> None:
    try:
        from rich.console import Console
        from rich.text import Text
    except ImportError:
        # rich not available yet — fall back to plain help
        print(_HELP)
        return

    console = Console()
    selected = 0

    def _render(sel: int) -> None:
        console.clear()
        console.print()
        console.print(f"  [bold red]TubeAssistant[/]")
        console.print()
        for i, (label, _) in enumerate(_MENU_ITEMS):
            if i == sel:
                console.print(f"  [bold cyan]> {label}[/]")
            else:
                console.print(f"    [dim]{label}[/]")
        console.print()
        console.print("  [dim]↑/↓  enter  esc[/]")

    _render(selected)

    while True:
        key = _read_key()
        if key == "UP":
            selected = (selected - 1) % len(_MENU_ITEMS)
            _render(selected)
        elif key == "DOWN":
            selected = (selected + 1) % len(_MENU_ITEMS)
            _render(selected)
        elif key == "ENTER":
            _, cmd = _MENU_ITEMS[selected]
            console.clear()
            if cmd is None:
                sys.exit(0)
            _COMMANDS[cmd]()
            return
        elif key == "ESC":
            console.clear()
            sys.exit(0)


# ── helpers ───────────────────────────────────────────────────────────────────

def _python() -> str:
    return sys.executable


def _launch(workspace: Path, command: str) -> int:
    return subprocess.run(
        [_python(), "-m", "youtube_ai_agent._launcher", str(workspace), command],
        cwd=str(workspace),
    ).returncode


def _check_setup(workspace: Path) -> bool:
    if not (workspace / ".setup_done").exists():
        print(
            f"\n[!] Workspace not configured: {workspace}\n"
            "    Run: tube-assistant onboard\n"
        )
        return False
    return True


def _print_status(workspace: Path) -> None:
    env_file   = workspace / ".env"
    state_file = workspace / "state.json"

    print(f"\n  Workspace : {workspace}")
    print(f"  .env      : {'✓' if env_file.exists() else '✗ missing'}")
    print(f"  creds     : {'✓' if (workspace / 'credentials.json').exists() else '✗ missing'}")
    print(f"  setup     : {'✓ done' if (workspace / '.setup_done').exists() else '✗ run onboard'}")

    if state_file.exists():
        try:
            state  = json.loads(state_file.read_text(encoding="utf-8"))
            queue  = state.get("topic_queue", [])
            videos = state.get("video_ids", [])
            vpd    = state.get("videos_per_day", 1)
            print(f"  topics    : {len(queue)} in queue")
            print(f"  videos    : {len(videos)} published")
            print(f"  vpd       : {vpd}")
            if videos:
                print(f"  last      : https://youtu.be/{videos[0]}")
        except Exception:
            pass
    print()


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_onboard() -> None:
    workspace = get_workspace()
    scaffold(workspace)
    sys.exit(_launch(workspace, "wizard"))


def cmd_start() -> None:
    workspace = get_workspace()
    if not _check_setup(workspace):
        sys.exit(1)
    scaffold(workspace)
    print(f"\n  Starting TubeAssistant in: {workspace}")
    print("  Press Ctrl+C to stop.\n")
    sys.exit(_launch(workspace, "agent"))


def cmd_run() -> None:
    workspace = get_workspace()
    if not _check_setup(workspace):
        sys.exit(1)
    scaffold(workspace)
    print(f"\n  Running one-shot pipeline in: {workspace}\n")
    sys.exit(_launch(workspace, "main"))


def cmd_status() -> None:
    workspace = get_workspace()
    _print_status(workspace)


def cmd_workspace() -> None:
    print(get_workspace())


# ── dispatch ──────────────────────────────────────────────────────────────────

_COMMANDS = {
    "onboard":   cmd_onboard,
    "start":     cmd_start,
    "run":       cmd_run,
    "status":    cmd_status,
    "workspace": cmd_workspace,
}

_HELP = """\
TubeAssistant

Usage:
  tube-assistant              interactive menu
  tube-assistant onboard      first-time setup
  tube-assistant start        run the daemon
  tube-assistant run          one-shot pipeline
  tube-assistant status       workspace summary
  tube-assistant workspace    print workspace path

Environment:
  YOUTUBE_AI_WORKSPACE   override workspace directory
"""


def main() -> None:
    args = sys.argv[1:]

    if not args:
        _tui_menu()
        return

    if args[0] in ("-h", "--help", "help"):
        print(_HELP)
        sys.exit(0)

    cmd = args[0].lower()
    if cmd not in _COMMANDS:
        print(f"\n[!] Unknown command: {cmd}")
        print(f"    Run: tube-assistant\n")
        sys.exit(1)

    _COMMANDS[cmd]()
