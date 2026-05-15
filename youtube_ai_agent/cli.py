"""
YouTube AI Agent — CLI entry point.

Install:
    pip install .                       # from cloned repo
    pip install git+https://...         # from URL

Usage:
    youtube-ai-agent onboard            # first-time setup wizard
    youtube-ai-agent start              # run the daemon
    youtube-ai-agent run                # one-shot pipeline (no scheduler)
    youtube-ai-agent status             # print workspace and config summary
    youtube-ai-agent workspace          # print workspace path and exit
"""

import os
import sys
import subprocess
import json
from pathlib import Path

from youtube_ai_agent._workspace import get as get_workspace, scaffold


# ── helpers ───────────────────────────────────────────────────────────────────

def _python() -> str:
    return sys.executable


def _launch(workspace: Path, command: str) -> int:
    """Run a command via the internal launcher in the given workspace."""
    return subprocess.run(
        [_python(), "-m", "youtube_ai_agent._launcher", str(workspace), command],
        cwd=str(workspace),
    ).returncode


def _check_setup(workspace: Path) -> bool:
    if not (workspace / ".setup_done").exists():
        print(
            f"\n[!] Workspace not configured: {workspace}\n"
            "    Run: youtube-ai-agent onboard\n"
        )
        return False
    return True


def _print_status(workspace: Path) -> None:
    env_file = workspace / ".env"
    state_file = workspace / "state.json"

    print(f"\n  Workspace : {workspace}")
    print(f"  .env      : {'✓' if env_file.exists() else '✗ missing'}")
    print(f"  creds     : {'✓' if (workspace / 'credentials.json').exists() else '✗ missing'}")
    print(f"  setup     : {'✓ done' if (workspace / '.setup_done').exists() else '✗ run onboard'}")

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
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
    print(f"\n  Setting up workspace: {workspace}\n")
    scaffold(workspace)
    sys.exit(_launch(workspace, "wizard"))


def cmd_start() -> None:
    workspace = get_workspace()
    if not _check_setup(workspace):
        sys.exit(1)
    scaffold(workspace)   # ensure dirs exist after workspace move etc.
    print(f"\n  Starting agent in workspace: {workspace}")
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


# ── entry point ───────────────────────────────────────────────────────────────

_COMMANDS = {
    "onboard":   cmd_onboard,
    "start":     cmd_start,
    "run":       cmd_run,
    "status":    cmd_status,
    "workspace": cmd_workspace,
}

_HELP = """\
YouTube AI Agent

Usage:
  youtube-ai-agent <command>

Commands:
  onboard    First-time setup (AI service, Telegram, YouTube credentials)
  start      Run the agent daemon (24/7, with Telegram bot)
  run        One-shot pipeline — produce and upload one video now
  status     Show workspace path and configuration summary
  workspace  Print workspace path

Environment:
  YOUTUBE_AI_WORKSPACE   Override workspace directory (default: ~/.youtube-ai-agent)
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(_HELP)
        sys.exit(0)

    cmd = args[0].lower()
    if cmd not in _COMMANDS:
        print(f"\n[!] Unknown command: {cmd}")
        print(f"    Available: {', '.join(_COMMANDS)}\n")
        sys.exit(1)

    _COMMANDS[cmd]()
