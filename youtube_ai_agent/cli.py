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


def _enable_ansi() -> None:
    """Enable ANSI escape code processing on Windows 10+."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _tui_menu() -> None:
    _enable_ansi()
    try:
        from rich.console import Console
    except ImportError:
        print(_HELP)
        return

    console = Console()
    selected = 0

    # number of lines the menu occupies (used to move cursor back up on redraw)
    # blank + title + blank + N items + blank + hint = N + 5
    _MENU_HEIGHT = len(_MENU_ITEMS) + 5

    def _render(sel: int, first: bool = False) -> None:
        lines = []
        lines.append("")
        lines.append("  [bold red]TubeAssistant[/]")
        lines.append("")
        for i, (label, _) in enumerate(_MENU_ITEMS):
            if i == sel:
                lines.append(f"  [bold cyan]> {label}[/]")
            else:
                lines.append(f"    [dim]{label}[/]")
        lines.append("")
        lines.append("  [dim]↑/↓  enter  esc[/]")

        if not first:
            # move cursor up to overwrite previous render
            sys.stdout.write(f"\033[{_MENU_HEIGHT}A")
            sys.stdout.flush()

        for line in lines:
            # clear the line then print
            sys.stdout.write("\033[2K")
            sys.stdout.flush()
            console.print(line)

    _render(selected, first=True)

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
            print()
            if cmd is None:
                sys.exit(0)
            _COMMANDS[cmd]()
            return
        elif key == "ESC":
            print()
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
        print("\n  Setup required — launching wizard...\n")
        cmd_onboard()
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
