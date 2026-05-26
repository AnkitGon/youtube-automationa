"""Package daemon entry point.

The launcher has already changed into the active workspace and loaded .env.
Keep this module as a thin delegate so the installed CLI and repo script share
one daemon implementation.
"""

from agent import main, run_pipeline


__all__ = ["main", "run_pipeline"]


if __name__ == "__main__":
    main()
