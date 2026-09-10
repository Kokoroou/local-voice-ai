"""Persisted Settings-UI overrides: a flat ``{env var: value}`` JSON file.

Applied as environment defaults at startup (see ``__main__._load_env_files``)
and rewritten at runtime by ``SettingsController``. Atomic writes (temp file +
``replace``) so a crash mid-save can't leave a half-written file for the next
boot to choke on.
"""

from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def save(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
