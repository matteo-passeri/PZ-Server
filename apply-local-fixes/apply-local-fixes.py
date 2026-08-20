#!/usr/bin/env python3

from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime


BASE = Path(
    "/home/matteo/containers/project-zomboid"
)

WORKSHOP = Path(
    "/mnt/media_hd/ProjectZomboidServer/"
    "DedicatedServer/steamapps/workshop/content/108600"
)

VRO_NC_PATCH_SOURCE = (
    BASE
    / "local-patches"
    / "vro-nearby-containers"
    / "zzz_VRO_Fixing.lua"
)

VRO_ORIGINAL_SHA256 = (
    "c39df1a393d07f21e341fe883d05e775"
    "ec14471e8ecde8db1bcf2ad1fd6dc9d9"
)

VRO_PATCHED_SHA256 = (
    "b734165b0820a0793ceb89697b5f7d03"
    "f0b707cd538e3ec8d37838485772a2c9"
)

VRO_NC_MARKER = (
    "Nearby-container integration (optional companion mod)"
)

STATE_FILE = Path(
    "/home/matteo/containers/project-zomboid/"
    ".pz-local-fixes-state.json"
)

CONTAINER = "game-project-zomboid"
VRO_BACKUP_KEEP = 10

VRO_CONTAINER_TARGET = (
    "/home/steam/zomboid/steamapps/workshop/content/108600/"
    "2757712197/mods/Vehicle Repair Overhaul/42/media/lua/client/"
    "zzz_VRO_Fixing.lua"
)

LOG_PREFIX = "[PZ-LOCAL-FIX]"


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

FIX_SCRIPTS_DIR = BASE / "fix-scripts"


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
        "VRO_BACKUP_KEEP": VRO_BACKUP_KEEP,
        "VRO_CONTAINER_TARGET": VRO_CONTAINER_TARGET,
        "VRO_NC_PATCH_SOURCE": VRO_NC_PATCH_SOURCE,
        "VRO_ORIGINAL_SHA256": VRO_ORIGINAL_SHA256,
        "VRO_PATCHED_SHA256": VRO_PATCHED_SHA256,
        "VRO_NC_MARKER": VRO_NC_MARKER,
        "state": state,
        "log": log,
        "sha256": sha256,
    }


def main():
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
