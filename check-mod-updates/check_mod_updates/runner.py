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
            "Un altro controllo è già "
            "in esecuzione. "
            "Nessuna azione eseguita."
        )
        return 0

    log(
        f"Lock acquisito: "
        f"{LOCK_FILE}"
    )

    active_ids = (
        get_configured_workshop_ids(
            env
        )
    )

    log(
        "Workshop item configurati "
        f"nel .env: {len(active_ids)}"
    )

    if not container_running():
        log(
            "Container non attivo: "
            "nessun controllo/restart eseguito."
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
            "RCON non disponibile/verificabile: "
            f"{exc}. "
            "Controllo rimandato."
        )
        return 0

    log(
        f"Giocatori connessi: "
        f"{players}"
    )

    if players > 0:
        log(
            "Server occupato: "
            "controllo aggiornamenti rimandato."
        )
        return 0

    log(
        "Server vuoto. Interrogo Steam "
        f"per {len(active_ids)} "
        "Workshop item..."
    )

    try:
        remote = steam_details(
            active_ids
        )

    except Exception as exc:
        log(
            "Steam API non disponibile: "
            f"{exc}. "
            "Controllo rimandato."
        )
        return 0

    state = load_state()

    if state is None:
        save_state(
            remote,
            active_ids,
        )

        log(
            "Prima esecuzione: "
            "baseline Workshop creata."
        )

        log(
            "Nessun restart effettuato. "
            "Da ora verranno rilevati "
            "solo nuovi cambiamenti "
            "pubblicati su Steam."
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
            "ATTENZIONE Workshop "
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
                    "Rimosso dallo stato "
                    "Workshop non più "
                    "configurato: "
                    f"{workshop_id}"
                )

            save_state(
                remote,
                active_ids,
            )

        log(
            "Nessun nuovo aggiornamento "
            "Workshop disponibile."
        )

        return 0

    log(
        f"Trovati {len(updates)} "
        "Workshop item cambiati:"
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

    # Ricontrollo immediatamente prima del restart.
    try:
        players, _ = (
            get_player_count()
        )

    except (
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        log(
            "Restart annullato: "
            "RCON non verificabile "
            f"({exc})."
        )
        return 0

    if players > 0:
        log(
            "Restart annullato: "
            "nel frattempo sono entrati "
            f"{players} giocatori."
        )
        return 0

    restart_server()

    # IMPORTANTISSIMO:
    # aggiorniamo la baseline solo dopo:
    # - Workshop aggiornati
    # - eventuali patch locali
    # - eventuale recreate post-patch
    # - RCON operativo
    # - RestartCount == 0
    # - stability check completato
    save_state(
        remote,
        active_ids,
    )

    log(
        "Restart completato e verificato: "
        "RCON operativo, "
        "patch locali applicate/verificate, "
        "container stabile, "
        "RestartCount=0 e "
        "stato Workshop aggiornato."
    )

    return 0


def run():
    try:
        return main()

    except KeyboardInterrupt:
        log(
            "Interrotto."
        )
        return 130

    except Exception as exc:
        log(
            f"ERRORE: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
