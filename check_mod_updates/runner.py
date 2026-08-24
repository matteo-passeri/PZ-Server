import fcntl
import os
import subprocess
import sys

from . import config, server
from .config import get_configured_workshop_ids, log
from .state import load_state, save_state
from .steam import find_updates, steam_details
from .server import (
    container_running,
    get_container_ip,
    get_player_count,
    restart_server,
)


LOCK_FILE = None
RCON_PORT = None


# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------

def acquire_lock():
    lock_handle = (
        LOCK_FILE.open(
            "w"
        )
    )

    try:
        fcntl.flock(
            lock_handle.fileno(),
            (
                fcntl.LOCK_EX
                | fcntl.LOCK_NB
            ),
        )

    except BlockingIOError:
        lock_handle.close()
        return None

    lock_handle.write(
        str(
            os.getpid()
        )
    )

    lock_handle.flush()

    return lock_handle


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    global LOCK_FILE
    global RCON_PORT

    env = config.load_configuration()
    server.configure()
    LOCK_FILE = config.LOCK_FILE
    RCON_PORT = config.RCON_PORT

    lock_handle = (
        acquire_lock()
    )

    if lock_handle is None:
        log(
            "Another check is already running. "
            "No action taken."
        )
        return 0

    log(
        f"Lock acquired: "
        f"{LOCK_FILE}"
    )

    active_ids = (
        get_configured_workshop_ids(
            env
        )
    )

    log(
        "Workshop items configured "
        f"in .env: {len(active_ids)}"
    )

    if not container_running():
        log(
            "Container is not running: "
            "no check or restart performed."
        )
        return 0

    try:
        rcon_host = (
            get_container_ip()
        )

        log(
            "RCON target: "
            f"{rcon_host}:"
            f"{RCON_PORT}"
        )

        players, _ = (
            get_player_count()
        )

    except (
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        log(
            "RCON unavailable or unverifiable: "
            f"{exc}. "
            "Check deferred."
        )
        return 0

    log(
        f"Connected players: "
        f"{players}"
    )

    if players > 0:
        log(
            "Server is occupied: "
            "update check deferred."
        )
        return 0

    log(
        "Server is empty. Querying Steam "
        f"for {len(active_ids)} "
        "Workshop items..."
    )

    try:
        remote = steam_details(
            active_ids
        )

    except Exception as exc:
        log(
            "Steam API unavailable: "
            f"{exc}. "
            "Check deferred."
        )
        return 0

    state = load_state()

    if state is None:
        save_state(
            remote,
            active_ids,
        )

        log(
            "First run: "
            "Workshop baseline created."
        )

        log(
            "No restart performed. "
            "From now on, only new changes "
            "published on Steam will be detected."
        )

        return 0

    (
        updates,
        inaccessible,
    ) = find_updates(
        active_ids,
        remote,
        state,
    )

    for (
        workshop_id,
        reason,
    ) in inaccessible:
        log(
            "WARNING Workshop "
            f"{workshop_id}: "
            f"{reason}"
        )

    if not updates:
        old_ids = set(
            state.get(
                "items",
                {},
            )
        )

        current_ids = set(
            active_ids
        )

        removed_ids = (
            old_ids
            - current_ids
        )

        if removed_ids:
            for workshop_id in sorted(
                removed_ids
            ):
                log(
                    "Removed from state, Workshop "
                    "no longer "
                    "configured: "
                    f"{workshop_id}"
                )

            save_state(
                remote,
                active_ids,
            )

        log(
            "No new Workshop update "
            "available."
        )

        return 0

    log(
        f"Found {len(updates)} "
        "changed Workshop items:"
    )

    for item in updates:
        if item["old"] is None:
            detail = (
                item["reason"]
            )
        else:
            detail = (
                "time_updated "
                f"{item['old']} -> "
                f"{item['new']}"
            )

        log(
            f"  {item['id']} - "
            f"{item['title']} "
            f"({detail})"
        )

    # Check again immediately before restart.
    try:
        players, _ = (
            get_player_count()
        )

    except (
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        log(
            "Restart cancelled: "
            "RCON unverifiable "
            f"({exc})."
        )
        return 0

    if players > 0:
        log(
            "Restart cancelled: "
            f"{players} players joined "
            "in the meantime."
        )
        return 0

    restart_server()

    # IMPORTANT:
    # update the baseline only after:
    # - updated Workshop content
    # - any local patches
    # - any post-patch recreate
    # - working RCON
    # - RestartCount == 0
    # - completed stability check
    save_state(
        remote,
        active_ids,
    )

    log(
        "Restart completed and verified: "
        "RCON is working, "
        "local patches applied/verified, "
        "container stable, "
        "RestartCount=0 e "
        "Workshop state updated."
    )

    return 0


def run():
    try:
        return main()

    except KeyboardInterrupt:
        log(
            "Interrupted."
        )
        return 130

    except Exception as exc:
        log(
            f"ERROR: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
