from pathlib import Path
from datetime import datetime


SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env"

BASE = None
STATE_FILE = None
LOCK_FILE = None
CONTAINER = None
LOCAL_FIXES = None
RCON_PORT = None
RCON_BIN = None
RCON_PASSWORD = None
SERVER_READY_TIMEOUT = None
SERVER_READY_POLL = None
SERVER_STABILITY_SECONDS = None
SERVER_STABILITY_POLL = None
PROJECT_NAME = None
MAX_START_ATTEMPTS = None

STEAM_DETAILS_URL = (
    "https://api.steampowered.com/"
    "ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)

LOG_PREFIX = "[PZ-MOD-CHECK]"


class LocalPatchError(RuntimeError):
    """
    Deterministic local patcher error.

    It must not cause a second server recreate: repeating stop/remove/start
    cannot resolve it.
    """
    pass



# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

def log(message):
    print(
        f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S} "
        f"{LOG_PREFIX} {message}",
        flush=True,
    )


# ------------------------------------------------------------
# .env / active mod list
# ------------------------------------------------------------

def read_env(path):
    result = {}

    if not path.is_file():
        raise RuntimeError(
            f".env not found: {path}"
        )

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
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


def required_env(env, key):
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(
            f"{key} is missing or empty in {ENV_FILE}"
        )

    return value


def positive_int_env(env, key):
    raw = required_env(env, key)

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{key} must be a positive integer: {raw!r}"
        ) from exc

    if value <= 0:
        raise RuntimeError(
            f"{key} must be greater than zero: {value}"
        )

    return value


def configured_path(env, key):
    return Path(
        required_env(env, key)
    ).expanduser()


def load_configuration():
    global BASE
    global STATE_FILE
    global LOCK_FILE
    global CONTAINER
    global LOCAL_FIXES
    global RCON_PORT
    global RCON_BIN
    global RCON_PASSWORD
    global SERVER_READY_TIMEOUT
    global SERVER_READY_POLL
    global SERVER_STABILITY_SECONDS
    global SERVER_STABILITY_POLL
    global PROJECT_NAME
    global MAX_START_ATTEMPTS

    env = read_env(ENV_FILE)

    BASE = configured_path(env, "PZ_SERVER_DIR")
    STATE_FILE = BASE / ".pz-mod-check-state.json"
    LOCK_FILE = configured_path(env, "PZ_LOCK_FILE")
    CONTAINER = required_env(env, "PZ_CONTAINER")
    LOCAL_FIXES = configured_path(env, "PZ_LOCAL_FIXES")
    RCON_PORT = positive_int_env(env, "PZ_RCON_PORT")
    RCON_BIN = required_env(env, "PZ_RCON_BIN")
    RCON_PASSWORD = required_env(env, "PZ_RCON_PASSWORD")
    SERVER_READY_TIMEOUT = positive_int_env(
        env,
        "PZ_SERVER_READY_TIMEOUT",
    )
    SERVER_READY_POLL = positive_int_env(
        env,
        "PZ_SERVER_READY_POLL",
    )
    SERVER_STABILITY_SECONDS = positive_int_env(
        env,
        "PZ_SERVER_STABILITY_SECONDS",
    )
    SERVER_STABILITY_POLL = positive_int_env(
        env,
        "PZ_SERVER_STABILITY_POLL",
    )
    PROJECT_NAME = required_env(env, "PZ_PROJECT_NAME")
    MAX_START_ATTEMPTS = positive_int_env(
        env,
        "PZ_MAX_START_ATTEMPTS",
    )

    return env


def get_configured_workshop_ids(env):
    raw = env.get(
        "PZ_MOD_IDS",
        "",
    ).strip()

    if not raw:
        raise RuntimeError(
            "PZ_MOD_IDS is missing or empty in .env"
        )

    ids = []

    for part in raw.split(";"):
        workshop_id = part.strip()

        if not workshop_id:
            continue

        if not workshop_id.isdigit():
            raise RuntimeError(
                "Invalid Workshop ID in PZ_MOD_IDS: "
                f"{workshop_id!r}"
            )

        if workshop_id not in ids:
            ids.append(workshop_id)

    if not ids:
        raise RuntimeError(
            "No valid Workshop ID found in PZ_MOD_IDS"
        )

    return ids
