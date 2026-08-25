#!/usr/bin/env python3

from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"

BASE = None
WORKSHOP = None
LOG_ROOTS = None
ACTIVE_WORKSHOP_IDS = None
STATE_FILE = None
CONTAINER = None
FIX_SCRIPTS_DIR = None

LOG_PREFIX = "[PZ-LOCAL-FIX]"


def read_env(path):
    if not path.is_file():
        raise RuntimeError(f".env not found: {path}")

    result = {}

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in "\"'"
        ):
            value = value[1:-1]

        result[key.strip()] = value

    return result


def configured_path(env, key):
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(f"{key} is missing or empty in {ENV_FILE}")

    return Path(value).expanduser()


def required_env(env, key):
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(f"{key} is missing or empty in {ENV_FILE}")

    return value


def load_configuration():
    global BASE
    global WORKSHOP
    global LOG_ROOTS
    global ACTIVE_WORKSHOP_IDS
    global STATE_FILE
    global CONTAINER
    global FIX_SCRIPTS_DIR

    env = read_env(ENV_FILE)

    BASE = configured_path(env, "PZ_SERVER_DIR")
    dedicated_server = configured_path(env, "PZ_DEDICATED_SERVER_DIR")
    WORKSHOP = dedicated_server / "steamapps/workshop/content/108600"
    zomboid_data = env.get("PZ_ZOMBOID_DATA_DIR", "").strip()
    LOG_ROOTS = [
        dedicated_server / "Logs",
        dedicated_server / "logs",
    ]
    if zomboid_data:
        data_dir = Path(zomboid_data).expanduser()
        LOG_ROOTS[:0] = [
            data_dir / "Logs",
            data_dir / "logs",
        ]

    ACTIVE_WORKSHOP_IDS = {
        workshop_id.strip()
        for workshop_id in env.get("PZ_MOD_IDS", "").split(";")
        if workshop_id.strip().isdigit()
    }
    STATE_FILE = BASE / ".pz-local-fixes-state.json"
    CONTAINER = required_env(env, "PZ_CONTAINER")
    FIX_SCRIPTS_DIR = SCRIPT_DIR / "fix-scripts"


def log(message):
    print(
        f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S} "
        f"{LOG_PREFIX} {message}",
        flush=True,
    )


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def ensure_symlink(source, destination, link_target=None):
    """
    Create or restore a symlink without overwriting real content.

    Returns one of: created, present, replaced, blocked,
    source_missing.
    """
    if link_target is None:
        link_target = source

    if not source.exists():
        return "source_missing"

    if destination.is_symlink():
        try:
            if (
                destination.readlink() == Path(link_target)
                and destination.samefile(source)
            ):
                return "present"
        except OSError:
            pass

        destination.unlink()
        status = "replaced"
    elif destination.exists():
        return "blocked"
    else:
        status = "created"

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.symlink_to(
        link_target,
        target_is_directory=source.is_dir(),
    )

    return status


def latest_pz_server_log():
    """Return the newest persisted PZ server/console log, if one exists."""
    candidates = []

    for root in LOG_ROOTS:
        if not root.is_dir():
            continue

        for pattern in ("*.log", "*console*.txt", "*server*.txt"):
            candidates.extend(path for path in root.glob(pattern) if path.is_file())

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_state():
    if not STATE_FILE.is_file():
        return {
            "managed_files": {},
        }

    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {
            "managed_files": {},
        }

    if not isinstance(data, dict):
        data = {}

    if not isinstance(
        data.get("managed_files"),
        dict,
    ):
        data["managed_files"] = {}

    return data


def save_state(state):
    state["updated_at"] = (
        datetime.now()
        .astimezone()
        .isoformat()
    )

    tmp = STATE_FILE.with_suffix(
        STATE_FILE.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(STATE_FILE)


# ------------------------------------------------------------
# Fix 1:
# Build 42 uses Base.LimestoneCrushed.
#
# Some mods still use Base.CrushedLimestone.
#
# Search ONLY under media/scripts, so ItemName_Base.CrushedLimestone
# translations are left untouched.
# ------------------------------------------------------------

def discover_fix_scripts():
    """
    Load external fixes in alphabetical order.

    Every *.py file in fix-scripts must export:
        FIX = {
            "name": "human-readable name",
            "run": callable,
        }

    The callable receives one `ctx` argument, a dictionary containing
    helpers, constants, and shared state.
    """
    if not FIX_SCRIPTS_DIR.is_dir():
        raise RuntimeError(
            f"fix-scripts directory not found: {FIX_SCRIPTS_DIR}"
        )

    import importlib.util

    fixes = []

    for path in sorted(FIX_SCRIPTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue

        module_name = "pz_local_fix_" + re.sub(
            r"[^A-Za-z0-9_]",
            "_",
            path.stem,
        )

        spec = importlib.util.spec_from_file_location(
            module_name,
            path,
        )

        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Unable to load fix script: {path}"
            )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        fix = getattr(module, "FIX", None)

        if not isinstance(fix, dict):
            raise RuntimeError(
                f"{path.name}: FIX variable is missing or invalid."
            )

        name = fix.get("name", path.stem)
        run = fix.get("run")

        if not callable(run):
            raise RuntimeError(
                f"{path.name}: FIX['run'] is not callable."
            )

        fixes.append((name, path, run))

    return fixes


def build_context(state):
    return {
        "BASE": BASE,
        "WORKSHOP": WORKSHOP,
        "active_workshop_ids": ACTIVE_WORKSHOP_IDS,
        "latest_pz_server_log": latest_pz_server_log,
        "STATE_FILE": STATE_FILE,
        "CONTAINER": CONTAINER,
        "state": state,
        "log": log,
        "sha256": sha256,
        "ensure_symlink": ensure_symlink,
    }


def main():
    load_configuration()
    state = load_state()
    ctx = build_context(state)
    changed = False

    fixes = discover_fix_scripts()

    if not fixes:
        log("No fixes found in fix-scripts.")

    for name, path, run in fixes:
        log(f"Running fix: {name} ({path.name})")

        if run(ctx):
            changed = True

    save_state(state)

    if changed:
        log("PATCH_CHANGED=1")
        return 10

    log("PATCH_CHANGED=0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except KeyboardInterrupt:
        log("Interrupted.")
        sys.exit(130)

    except Exception as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
