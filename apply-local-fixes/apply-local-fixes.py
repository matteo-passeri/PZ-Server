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
PROJECT_DIR = SCRIPT_DIR.parent


def shared_env_file():
    candidates = (
        PROJECT_DIR / ".env",
        PROJECT_DIR / "docker-compose" / ".env",
    )

    for path in candidates:
        if path.is_file():
            return path

    return candidates[0]


ENV_FILE = shared_env_file()

BASE = None
WORKSHOP = None
STATE_FILE = None
CONTAINER = None
FIX_SCRIPTS_DIR = None

LOG_PREFIX = "[PZ-LOCAL-FIX]"


def read_env(path):
    if not path.is_file():
        raise RuntimeError(f".env non trovato: {path}")

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
        raise RuntimeError(f"{key} non presente o vuoto in {ENV_FILE}")

    return Path(value).expanduser()


def required_env(env, key):
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(f"{key} non presente o vuoto in {ENV_FILE}")

    return value


def load_configuration():
    global BASE
    global WORKSHOP
    global STATE_FILE
    global CONTAINER
    global FIX_SCRIPTS_DIR

    env = read_env(ENV_FILE)

    BASE = configured_path(env, "PZ_SERVER_DIR")
    WORKSHOP = (
        configured_path(env, "PZ_DEDICATED_SERVER_DIR")
        / "steamapps/workshop/content/108600"
    )
    STATE_FILE = BASE / ".pz-local-fixes-state.json"
    CONTAINER = required_env(env, "PZ_CONTAINER")
    FIX_SCRIPTS_DIR = BASE / "fix-scripts"


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
# Build 42 usa Base.LimestoneCrushed.
#
# Alcune mod continuano a usare Base.CrushedLimestone.
#
# Cerchiamo SOLO sotto media/scripts, quindi non tocchiamo
# le traduzioni ItemName_Base.CrushedLimestone.
# ------------------------------------------------------------

def discover_fix_scripts():
    """
    Carica i fix esterni in ordine alfabetico.

    Ogni file *.py in fix-scripts deve esportare:
        FIX = {
            "name": "nome leggibile",
            "run": callable,
        }

    La callable riceve un unico argomento `ctx`, un dizionario
    contenente helper, costanti e stato condiviso.
    """
    if not FIX_SCRIPTS_DIR.is_dir():
        raise RuntimeError(
            f"Cartella fix-scripts non presente: {FIX_SCRIPTS_DIR}"
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
                f"Impossibile caricare fix script: {path}"
            )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        fix = getattr(module, "FIX", None)

        if not isinstance(fix, dict):
            raise RuntimeError(
                f"{path.name}: variabile FIX mancante/non valida."
            )

        name = fix.get("name", path.stem)
        run = fix.get("run")

        if not callable(run):
            raise RuntimeError(
                f"{path.name}: FIX['run'] non è callable."
            )

        fixes.append((name, path, run))

    return fixes


def build_context(state):
    return {
        "BASE": BASE,
        "WORKSHOP": WORKSHOP,
        "STATE_FILE": STATE_FILE,
        "CONTAINER": CONTAINER,
        "state": state,
        "log": log,
        "sha256": sha256,
    }


def main():
    load_configuration()
    state = load_state()
    ctx = build_context(state)
    changed = False

    fixes = discover_fix_scripts()

    if not fixes:
        log("Nessun fix trovato in fix-scripts.")

    for name, path, run in fixes:
        log(f"Eseguo fix: {name} ({path.name})")

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
        log("Interrotto.")
        sys.exit(130)

    except Exception as exc:
        log(f"ERRORE: {exc}")
        sys.exit(1)
