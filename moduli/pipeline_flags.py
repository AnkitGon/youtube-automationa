"""Feature flags for long-form vs Shorts pipelines (env-driven)."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def long_form_enabled() -> bool:
    """When false, scheduled/catch-up/forced long-form runs are skipped; Shorts unchanged."""
    return _bool_env("LONG_FORM_ENABLED", True)
