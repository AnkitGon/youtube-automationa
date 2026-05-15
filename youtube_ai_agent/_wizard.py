"""
Setup wizard entry point for the package launcher.
Runs the wizard from the project root (git clone) or the bundled copy.
"""

import sys
import importlib.util
from pathlib import Path


def main():
    # Prefer root setup.py (git clone / editable install)
    root_wizard = Path(__file__).parent.parent / "wizard.py"
    bundled     = Path(__file__).parent / "_wizard_standalone.py"

    wizard_path = root_wizard if root_wizard.exists() else bundled
    if not wizard_path.exists():
        print("[!] Setup wizard not found. Run: youtube-ai-agent onboard")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("_setup_wizard", wizard_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
