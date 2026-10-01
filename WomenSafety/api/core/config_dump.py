"""Effective-config dump (Phase 1c follow-up 2, item 3): reports every
Settings field's current value AND where it came from -- "default"
(the class-declared default, untouched), "env_var" (an OS environment
variable with that exact name was set, e.g. by a shell export or a
measurement script's os.environ[...] = ...), "config_file" (present in
the .env file but not as a live OS env var at process start), or "cli"
(passed via a recognized CLI flag -- this project's scripts accept a
few settings as --flags; mapped explicitly below since pydantic-settings
itself has no CLI layer here).

Secrets are redacted by NAME PATTERN (anything containing TOKEN, KEY,
SECRET, PASSWORD, API_KEY case-insensitively) -- this project's actual
secrets (TELEGRAM_BOT_TOKEN, OMNIDIM_API_KEY, etc.) live in os.environ/
.env directly, read by Telebot_Alert.py/Call_Alert.py, not as Settings
fields -- but this redaction is applied defensively to Settings too, in
case a future field ever holds one, rather than assuming none ever will.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from api.core.config import Settings, settings

SECRET_NAME_PATTERN = ("TOKEN", "KEY", "SECRET", "PASSWORD")

# Settings fields that can ALSO be overridden by a recognized CLI flag in
# one of this project's own scripts -- mapped explicitly since
# pydantic-settings has no CLI-source concept built in. Populated by
# dump_effective_config()'s caller via cli_overrides= when applicable
# (e.g. scripts/eval_detectors.py's --sample-interval-s).


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(p in upper for p in SECRET_NAME_PATTERN)


def _redact(name: str, value: Any) -> Any:
    if _is_secret_name(name) and value:
        return "***REDACTED***"
    return value


def _env_file_keys(env_file_path: Path) -> set[str]:
    if not env_file_path.exists():
        return set()
    keys = set()
    for line in env_file_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        keys.add(key)
    return keys


def dump_effective_config(cli_overrides: Optional[dict[str, str]] = None) -> list[dict]:
    """Returns one row per Settings field: {name, value, source}.
    source is one of 'cli', 'env_var', 'config_file', 'default'
    -- checked in that precedence order, matching pydantic-settings'
    own actual precedence (explicit init args > env vars > .env file >
    class default; this project never passes explicit init args to
    Settings(), so that tier is collapsed into 'cli' for the few
    fields a calling script re-applies from its own argparse flags)."""
    cli_overrides = cli_overrides or {}
    env_file_path = Path(Settings.Config.env_file)
    if not env_file_path.is_absolute():
        env_file_path = Path(__file__).parent.parent.parent / env_file_path
    dotenv_keys = _env_file_keys(env_file_path)

    class_defaults = Settings.model_fields
    rows = []
    for name, field_info in class_defaults.items():
        if name in cli_overrides:
            value = cli_overrides[name]
            source = "cli"
        else:
            value = getattr(settings, name)
            if name in os.environ:
                source = "env_var"
            elif name in dotenv_keys:
                source = "config_file"
            else:
                source = "default"
        rows.append({"name": name, "value": _redact(name, value), "source": source})
    return rows


def print_effective_config(cli_overrides: Optional[dict[str, str]] = None, label: str = "startup") -> None:
    rows = dump_effective_config(cli_overrides)
    print(f"[Config:{label}] effective settings (name=value [source]):")
    for row in rows:
        print(f"  {row['name']}={row['value']} [{row['source']}]")
