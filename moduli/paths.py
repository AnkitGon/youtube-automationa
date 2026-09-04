"""
Centralised portable-file path resolution.

All config / credential / state files live under CONFIG_DIR.
Default: project root (current working directory) — same as before.
Override: set CONFIG_DIR env var to a folder path.

Usage
-----
    from moduli.paths import config_path
    TOKEN = config_path("token.json")

On a new machine, copy the whole config/ folder and set:
    CONFIG_DIR=config  (relative) or CONFIG_DIR=C:\\Users\\me\\tube-config (absolute)
"""

from __future__ import annotations

import os

_CONFIG_DIR: str | None = None


def _resolve() -> str:
    global _CONFIG_DIR
    if _CONFIG_DIR is not None:
        return _CONFIG_DIR
    raw = os.environ.get("CONFIG_DIR", "").strip()
    if raw:
        _CONFIG_DIR = os.path.abspath(raw)
    else:
        _CONFIG_DIR = ""  # project root
    if _CONFIG_DIR:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
    return _CONFIG_DIR


def config_dir() -> str:
    """Absolute path to the config directory (empty string = project root)."""
    return _resolve()


def config_path(filename: str) -> str:
    """Resolve a portable config file to its full path."""
    base = _resolve()
    if base:
        return os.path.join(base, filename)
    return filename


def env_path() -> str:
    """Path to .env file."""
    return config_path(".env")


# Canonical names for every portable file
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"
STATE_FILE = "state.json"
SHORTS_STATE_FILE = "shorts_state.json"
PREFS_FILE = "preferenze_video.json"
MEMORY_FILE = "memoria_lungo_termine.json"
ENV_FILE = ".env"
