"""
Internal subprocess launcher.
Usage: python -m youtube_ai_agent._launcher <workspace_path> <command>
Commands: agent | main | dry-run | wizard

IMPORTANT: os.chdir(workspace) MUST happen before any moduli import so that
all module-level relative path constants resolve to the correct workspace dir.
"""

import os
import sys


def _run():
    if len(sys.argv) < 3:
        print("Usage: python -m youtube_ai_agent._launcher <workspace> <command>")
        sys.exit(1)

    workspace = sys.argv[1]
    command   = sys.argv[2]

    # ── 1. Switch to workspace FIRST — all relative paths resolve from here ──
    os.chdir(workspace)

    # ── 2. Load env from workspace .env ──────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(os.path.join(workspace, ".env"))

    # ── 3. Dispatch ──────────────────────────────────────────────────────────
    if command == "agent":
        from youtube_ai_agent._agent_main import main
        main()
    elif command == "main":
        from youtube_ai_agent._one_shot import run
        run()
    elif command == "dry-run":
        from youtube_ai_agent._one_shot import run
        run(dry_run=True)
    elif command == "wizard":
        from youtube_ai_agent._wizard import main
        main()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    _run()
