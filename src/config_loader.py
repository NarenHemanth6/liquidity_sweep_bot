"""
config_loader.py

Loads and validates configuration from:
  - config/settings.yaml   (strategy, risk, session, broker settings)
  - config/watchlist.yaml  (tradable symbol universe)
  - environment variables  (anything sensitive: API keys, account IDs,
    live-trading override flags)

No secrets are ever read from YAML. Only from os.environ, optionally
populated from a local .env file via python-dotenv (the .env file is
never committed; see .gitignore).

Live trading gate
------------------
This module intentionally makes it hard to accidentally enable live
trading:

    is_live_trading_enabled() returns True only if BOTH:
      1. settings.yaml -> mode.enable_live_trading == true, AND
      2. environment variable ENABLE_LIVE_TRADING == "true"

v1 of this project has no live broker implementation at all, so even if
both flags were somehow set to true, there is nothing in this codebase
that would place a real order. main.py additionally refuses to start if
this function returns True, as a defensive check for the future.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    _DOTENV_AVAILABLE = True
except ImportError:  # pragma: no cover - dotenv is a listed dependency
    _DOTENV_AVAILABLE = False

DEFAULT_SETTINGS_PATH = "config/settings.yaml"
DEFAULT_WATCHLIST_PATH = "config/watchlist.yaml"

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    """Load variables from a local .env file into os.environ, once.

    This is a no-op if python-dotenv is not installed or no .env file
    is present; in either case, real environment variables set by the
    shell/OS are still available via os.environ.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if _DOTENV_AVAILABLE:
        load_dotenv(override=False)
    _ENV_LOADED = True


def load_settings(path: str = DEFAULT_SETTINGS_PATH) -> dict[str, Any]:
    """Load and parse the strategy/risk/session settings file.

    Args:
        path: Path to the YAML settings file.

    Returns:
        A dict representation of the YAML file.

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If the file is empty or does not parse to a dict,
            or if required top-level sections are missing.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")

    with file_path.open("r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    if not isinstance(settings, dict):
        raise ValueError(f"Settings file {path} did not parse to a mapping")

    required_sections = (
        "mode",
        "session",
        "universe_filters",
        "watchlist",
        "market_levels",
        "candle_features",
        "strategy",
        "position_sizing",
        "risk_controls",
        "broker",
        "logging",
    )
    missing = [s for s in required_sections if s not in settings]
    if missing:
        raise ValueError(f"Settings file {path} is missing sections: {missing}")

    return settings


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> dict[str, Any]:
    """Load and parse the watchlist file.

    Args:
        path: Path to the YAML watchlist file.

    Returns:
        A dict with keys "symbols" (list[str]) and
        "confirmation_symbol" (str).

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If the file is empty, does not parse to a dict, or
            is missing required keys.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Watchlist file not found: {path}")

    with file_path.open("r", encoding="utf-8") as f:
        watchlist = yaml.safe_load(f)

    if not isinstance(watchlist, dict):
        raise ValueError(f"Watchlist file {path} did not parse to a mapping")

    if "symbols" not in watchlist or "confirmation_symbol" not in watchlist:
        raise ValueError(
            f"Watchlist file {path} must define 'symbols' and "
            f"'confirmation_symbol'"
        )

    return watchlist


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an environment variable, loading .env first if needed.

    Args:
        name: Environment variable name.
        default: Value to return if the variable is unset.
        required: If True, raise if the variable is unset and no
            default is provided.

    Returns:
        The environment variable's value, or `default` if unset.

    Raises:
        ValueError: If `required` is True and the variable is unset
            with no default given.
    """
    _ensure_env_loaded()
    value = os.environ.get(name, default)
    if required and value is None:
        raise ValueError(f"Required environment variable '{name}' is not set")
    return value


def is_live_trading_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Determine whether live trading is enabled.

    Live trading requires BOTH the config flag and the environment
    variable to explicitly agree it should be on. Absence of either,
    or any value other than a truthy "true", is treated as disabled.

    Args:
        settings: Pre-loaded settings dict (as returned by
            load_settings()). If None, settings.yaml is loaded using
            the default path.

    Returns:
        True only if settings["mode"]["enable_live_trading"] is True
        AND the ENABLE_LIVE_TRADING environment variable is the string
        "true" (case-insensitive). False otherwise.
    """
    if settings is None:
        settings = load_settings()

    config_flag = bool(settings.get("mode", {}).get("enable_live_trading", False))
    env_flag = (get_env("ENABLE_LIVE_TRADING", default="false") or "false").strip().lower()

    return config_flag and env_flag == "true"
