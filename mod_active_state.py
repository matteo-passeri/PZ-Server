"""Persistent record of the last Project Zomboid configuration that started."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


STATE_VERSION = 1
STATE_FILE_NAME = ".pz-last-successful-mods.json"


def state_file(root: Path) -> Path:
    return root / STATE_FILE_NAME


def read_last_active_mods(path: Path, warn: Callable[[str], None]) -> list[str]:
    """Return trusted prior active IDs; malformed state is never trusted."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state root is not an object")
        mods = data.get("last_active_mods")
        if data.get("version") != STATE_VERSION or not isinstance(mods, list):
            raise ValueError("unsupported version or invalid last_active_mods")
        if not all(isinstance(mod_id, str) and mod_id for mod_id in mods):
            raise ValueError("last_active_mods contains an invalid Mod ID")
        return list(dict.fromkeys(mods))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        warn(f"Ignoring malformed successful-mod state {path}: {exc}")
        return []


def write_last_active_mods(path: Path, mod_ids: list[str]) -> None:
    """Atomically save the IDs from a configuration which reached SERVER STARTED."""
    values = list(dict.fromkeys(mod_id for mod_id in mod_ids if mod_id))
    payload = json.dumps(
        {"version": STATE_VERSION, "last_active_mods": values},
        indent=2,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
