"""
Centralized, environment-driven configuration.

Nothing in this project should hard-code secrets or environment-specific
values. All configuration is read from environment variables (optionally
loaded from a local .env file via python-dotenv), with sane defaults for
local development.

See .env.example for the full list of supported variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load a local .env file if present. This is a no-op in environments where
# configuration is injected directly (e.g. a real deployment), and never
# overrides variables that are already set in the process environment.
load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of application configuration."""

    database_url: str
    operational_day_cutoff_hour: int
    reseed_on_start: bool


def load_settings() -> Settings:
    """Read settings from the environment. Safe to call repeatedly."""
    cutoff = _get_int("OPERATIONAL_DAY_CUTOFF_HOUR", 6)
    # Guard against a nonsensical value in the environment rather than
    # crashing the whole dashboard.
    if not 0 <= cutoff <= 23:
        cutoff = 6

    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///icu_dashboard.db"),
        operational_day_cutoff_hour=cutoff,
        reseed_on_start=_get_bool("ICU_RESEED_ON_START", False),
    )


settings = load_settings()
