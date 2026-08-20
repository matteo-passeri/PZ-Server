#!/usr/bin/env python3

from pathlib import Path
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime


BASE = Path("/home/matteo/containers/project-zomboid")
ENV_FILE = BASE / ".env"

STATE_FILE = BASE / ".pz-mod-check-state.json"
LOCK_FILE = Path("/tmp/pz-mod-check.lock")

COMPOSE = "/usr/bin/podman-compose"
CONTAINER = "game-project-zomboid"

LOCAL_FIXES = str(
    BASE / "apply-local-fixes.py"
)

RCON_PORT = 27015
RCON_BIN = "/usr/local/bin/rcon"

SERVER_READY_TIMEOUT = 1200
SERVER_READY_POLL = 15

SERVER_STABILITY_SECONDS = 90
SERVER_STABILITY_POLL = 15

PROJECT_NAME = "project-zomboid"

MAX_START_ATTEMPTS = 2

STEAM_DETAILS_URL = (
    "https://api.steampowered.com/"
    "ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)

LOG_PREFIX = "[PZ-MOD-CHECK]"


class LocalPatchError(RuntimeError):
    """
    Errore deterministico del patcher locale.

    Non deve causare un secondo recreate del server:
    ripetere stop/remove/start non può risolverlo.
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
# .env / lista mod attiva
# ------------------------------------------------------------

def read_env(path):
    result = {}

    if not path.is_file():
        raise RuntimeError(
            f".env non trovato: {path}"
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


def get_configured_workshop_ids(env):
    raw = env.get(
        "PZ_MOD_IDS",
        "",
    ).strip()

    if not raw:
        raise RuntimeError(
            "PZ_MOD_IDS non presente o vuoto nel .env"
        )

    ids = []

    for part in raw.split(";"):
        workshop_id = part.strip()

        if not workshop_id:
            continue

        if not workshop_id.isdigit():
            raise RuntimeError(
                "Workshop ID non valido in PZ_MOD_IDS: "
                f"{workshop_id!r}"
            )

        if workshop_id not in ids:
            ids.append(workshop_id)

    if not ids:
        raise RuntimeError(
            "Nessun Workshop ID valido trovato in PZ_MOD_IDS"
        )

    return ids


# ------------------------------------------------------------
# Stato persistente
# ------------------------------------------------------------

def load_state():
    if not STATE_FILE.is_file():
        return None

    try:
        payload = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            f"Impossibile leggere {STATE_FILE}: {exc}"
        )

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Formato stato non valido: {STATE_FILE}"
        )

    items = payload.get(
        "items",
        {},
    )

    if not isinstance(items, dict):
        raise RuntimeError(
            f"Formato items non valido: {STATE_FILE}"
        )

    return payload


def save_state(
    remote_items,
    active_ids,
):
    items = {}

    for workshop_id in active_ids:
        info = remote_items.get(
            workshop_id
        )

        if not info:
            continue

        result_code = int(
            info.get(
                "result",
                0,
            )
            or 0
        )

        if result_code != 1:
            continue

        remote_time = int(
            info.get(
                "time_updated",
                0,
            )
            or 0
        )

        if remote_time <= 0:
            continue

        items[workshop_id] = {
            "time_updated": remote_time,
            "title": info.get(
                "title",
                "(senza nome)",
            ),
        }

    payload = {
        "updated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "items": items,
    }

    tmp = STATE_FILE.with_suffix(
        STATE_FILE.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(
        STATE_FILE
    )


# ------------------------------------------------------------
# Steam Workshop remoto
# ------------------------------------------------------------

def steam_details(ids):
    result = {}
    batch_size = 50

    for offset in range(
        0,
        len(ids),
        batch_size,
    ):
        batch = ids[
            offset:offset + batch_size
        ]

        fields = {
            "itemcount": str(
                len(batch)
            ),
        }

        for index, workshop_id in enumerate(
            batch
        ):
            fields[
                f"publishedfileids[{index}]"
            ] = workshop_id

        body = urllib.parse.urlencode(
            fields
        ).encode(
            "ascii"
        )

        request = urllib.request.Request(
            STEAM_DETAILS_URL,
            data=body,
            headers={
                "User-Agent":
                    "pz-mod-update-check/4.0",
                "Content-Type":
                    "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=25,
        ) as response:
            payload = json.load(
                response
            )

        details = (
            payload
            .get(
                "response",
                {},
            )
            .get(
                "publishedfiledetails",
                [],
            )
        )

        for item in details:
            workshop_id = str(
                item.get(
                    "publishedfileid",
                    "",
                )
            ).strip()

            if workshop_id:
                result[
                    workshop_id
                ] = item

    return result


def find_updates(
    active_ids,
    remote,
    state,
):
    updates = []
    inaccessible = []

    previous_items = (
        state.get(
            "items",
            {},
        )
        if state
        else {}
    )

    for workshop_id in active_ids:
        info = remote.get(
            workshop_id
        )

        if not info:
            inaccessible.append(
                (
                    workshop_id,
                    "nessuna risposta da Steam",
                )
            )
            continue

        result_code = int(
            info.get(
                "result",
                0,
            )
            or 0
        )

        if result_code != 1:
            inaccessible.append(
                (
                    workshop_id,
                    f"Steam result={result_code}",
                )
            )
            continue

        remote_time = int(
            info.get(
                "time_updated",
                0,
            )
            or 0
        )

        if remote_time <= 0:
            inaccessible.append(
                (
                    workshop_id,
                    "time_updated remoto non valido",
                )
            )
            continue

        previous = previous_items.get(
            workshop_id
        )

        if previous is None:
            updates.append({
                "id": workshop_id,
                "title": info.get(
                    "title",
                    "(senza nome)",
                ),
                "old": None,
                "new": remote_time,
                "reason":
                    "nuovo Workshop item",
            })
            continue

        try:
            old_time = int(
                previous.get(
                    "time_updated",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            old_time = 0

        if remote_time != old_time:
            updates.append({
                "id": workshop_id,
                "title": info.get(
                    "title",
                    "(senza nome)",
                ),
                "old": old_time,
                "new": remote_time,
                "reason":
                    "versione Steam cambiata",
            })

    return (
        updates,
        inaccessible,
    )


# ------------------------------------------------------------
# Container
# ------------------------------------------------------------

def inspect_container_state():
    proc = subprocess.run(
        [
            "podman",
            "inspect",
            CONTAINER,
            "--format",
            "{{.State.Status}}|"
            "{{.State.Running}}|"
            "{{.State.Restarting}}|"
            "{{.State.ExitCode}}|"
            "{{.RestartCount}}",
        ],
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        return None

    parts = (
        proc.stdout
        .strip()
        .split(
            "|",
            4,
        )
    )

    if len(parts) != 5:
        return {
            "status": "unknown",
            "running": False,
            "restarting": False,
            "exit_code": None,
            "restart_count": None,
        }

    (
        status,
        running,
        restarting,
        exit_code,
        restart_count,
    ) = parts

    try:
        exit_code = int(
            exit_code
        )
    except ValueError:
        exit_code = None

    try:
        restart_count = int(
            restart_count
        )
    except ValueError:
        restart_count = None

    return {
        "status": status,
        "running": (
            running.lower()
            == "true"
        ),
        "restarting": (
            restarting.lower()
            == "true"
        ),
        "exit_code":
            exit_code,
        "restart_count":
            restart_count,
    }


def container_running():
    state = (
        inspect_container_state()
    )

    return bool(
        state
        and state["running"]
        and not state["restarting"]
    )


def validate_fresh_container_state(
    state,
):
    if state is None:
        raise RuntimeError(
            "Container non presente"
        )

    if not state["running"]:
        raise RuntimeError(
            "Container non running "
            f"(status={state['status']}, "
            f"restarting={state['restarting']}, "
            f"exit={state['exit_code']})"
        )

    restart_count = (
        state.get(
            "restart_count"
        )
    )

    if restart_count is None:
        raise RuntimeError(
            "Impossibile determinare RestartCount"
        )

    if restart_count != 0:
        raise RuntimeError(
            "Il nuovo container si è già "
            "riavviato autonomamente "
            f"(RestartCount={restart_count}). "
            "Startup considerato NON valido."
        )


# ------------------------------------------------------------
# RCON
# ------------------------------------------------------------

def get_container_ip():
    proc = subprocess.run(
        [
            "podman",
            "inspect",
            CONTAINER,
            "--format",
            "{{range .NetworkSettings.Networks}}"
            "{{.IPAddress}}"
            "{{end}}",
        ],
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "Impossibile leggere IP container: "
            + proc.stderr.strip()
        )

    ip = proc.stdout.strip()

    if not ip:
        raise RuntimeError(
            "IP del container non disponibile"
        )

    return ip


def rcon_command(command):
    rcon_host = (
        get_container_ip()
    )

    shell_command = (
        f'{RCON_BIN} '
        f'-a {rcon_host}:{RCON_PORT} '
        f'-p "$RCON_PASSWORD" '
        f'-T 10s '
        f'{command}'
    )

    proc = subprocess.run(
        [
            "podman",
            "exec",
            CONTAINER,
            "sh",
            "-lc",
            shell_command,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    if proc.returncode != 0:
        detail = (
            proc.stderr
            or proc.stdout
        ).strip()

        raise RuntimeError(
            "Comando RCON fallito"
            + (
                f": {detail}"
                if detail
                else ""
            )
        )

    return (
        proc.stdout.strip()
    )


def get_player_count():
    output = (
        rcon_command(
            "players"
        )
    )

    patterns = (
        r"Players\s+connected\s*"
        r"\(\s*(\d+)\s*\)",

        r"Players\s+connected\s*"
        r":\s*(\d+)",

        r"Players\s*:\s*(\d+)",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            output,
            re.IGNORECASE,
        )

        if match:
            return (
                int(
                    match.group(1)
                ),
                output,
            )

    raise RuntimeError(
        "Formato risposta 'players' "
        "non riconosciuto. "
        f"Risposta RCON: {output!r}"
    )


# ------------------------------------------------------------
# Patch locali
# ------------------------------------------------------------

def apply_local_fixes():
    """
    Esegue apply-local-fixes.py.

    Return:
      False -> nessun file modificato
      True  -> patch applicate, serve un nuovo recreate

    Exit code patcher:
      0  = nessuna modifica
      10 = almeno una modifica
      altro = errore
    """
    if not Path(
        LOCAL_FIXES
    ).is_file():
        raise RuntimeError(
            f"Patcher locale non trovato: "
            f"{LOCAL_FIXES}"
        )

    log(
        "Controllo patch locali post-update..."
    )

    proc = subprocess.run(
        [
            "podman",
            "unshare",
            LOCAL_FIXES,
        ],
        cwd=BASE,
        capture_output=True,
        text=True,
    )

    if proc.stdout:
        print(
            proc.stdout,
            end="",
        )

    if proc.stderr:
        print(
            proc.stderr,
            end="",
            file=sys.stderr,
        )

    if proc.returncode == 0:
        log(
            "Patch locali già corrette: "
            "nessun ulteriore recreate necessario."
        )
        return False

    if proc.returncode == 10:
        log(
            "Patch locali applicate: "
            "serve un ulteriore recreate "
            "per caricare i file modificati."
        )
        return True

    raise LocalPatchError(
        "apply-local-fixes.py fallito "
        f"(exit code {proc.returncode})"
    )


# ------------------------------------------------------------
# Restart / recreate
# ------------------------------------------------------------

def wait_for_container_running(
    timeout_seconds=30,
):
    deadline = (
        time.time()
        + timeout_seconds
    )

    last_state = None

    while time.time() < deadline:
        last_state = (
            inspect_container_state()
        )

        if (
            last_state
            and last_state["running"]
            and not last_state["restarting"]
        ):
            return (
                True,
                last_state,
            )

        time.sleep(1)

    return (
        False,
        last_state,
    )


def wait_for_server_ready(
    timeout_seconds=
        SERVER_READY_TIMEOUT,
):
    deadline = (
        time.time()
        + timeout_seconds
    )

    next_log = 0

    while time.time() < deadline:
        state = (
            inspect_container_state()
        )

        validate_fresh_container_state(
            state
        )

        try:
            players, _ = (
                get_player_count()
            )

            log(
                "Project Zomboid pronto via RCON: "
                f"{players} giocatori connessi."
            )

            return

        except (
            RuntimeError,
            subprocess.TimeoutExpired,
        ):
            pass

        now = time.time()

        if now >= next_log:
            remaining = max(
                0,
                int(
                    deadline - now
                ),
            )

            log(
                "Container running con "
                "RestartCount=0, ma PZ "
                "non è ancora pronto. "
                "Attendo RCON... "
                f"({remaining}s al timeout)"
            )

            next_log = (
                now + 60
            )

        time.sleep(
            SERVER_READY_POLL
        )

    raise RuntimeError(
        "Timeout: Project Zomboid non è "
        "diventato disponibile via RCON "
        f"entro {timeout_seconds}s"
    )


def verify_server_stability(
    stability_seconds=
        SERVER_STABILITY_SECONDS,
):
    log(
        "RCON operativo. "
        f"Verifico stabilità per "
        f"{stability_seconds}s..."
    )

    deadline = (
        time.time()
        + stability_seconds
    )

    consecutive_successes = 0

    while time.time() < deadline:
        state = (
            inspect_container_state()
        )

        validate_fresh_container_state(
            state
        )

        try:
            players, _ = (
                get_player_count()
            )

        except (
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise RuntimeError(
                "RCON è diventato non disponibile "
                "durante il periodo di stabilità: "
                f"{exc}"
            )

        consecutive_successes += 1

        remaining = max(
            0,
            int(
                deadline - time.time()
            ),
        )

        log(
            "Stabilità OK: "
            f"RestartCount={state['restart_count']}, "
            f"RCON OK, "
            f"players={players}. "
            f"Restano circa {remaining}s."
        )

        if remaining <= 0:
            break

        time.sleep(
            min(
                SERVER_STABILITY_POLL,
                remaining,
            )
        )

    state = (
        inspect_container_state()
    )

    validate_fresh_container_state(
        state
    )

    players, _ = (
        get_player_count()
    )

    log(
        "Periodo di stabilità completato: "
        f"RestartCount={state['restart_count']}, "
        f"RCON operativo, "
        f"players={players}, "
        f"controlli riusciti={consecutive_successes}."
    )


def remove_compose_containers():
    proc = subprocess.run(
        [
            "podman",
            "ps",
            "-aq",
            "--filter",
            (
                "label="
                "io.podman.compose.project="
                f"{PROJECT_NAME}"
            ),
        ],
        cwd=BASE,
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "Impossibile ottenere la lista "
            "dei container dello stack: "
            f"{proc.stderr.strip()}"
        )

    container_ids = [
        line.strip()
        for line
        in proc.stdout.splitlines()
        if line.strip()
    ]

    if not container_ids:
        log(
            "Nessun vecchio container dello "
            "stack da rimuovere."
        )
        return

    log(
        "Rimozione esplicita di "
        f"{len(container_ids)} "
        "container dello stack..."
    )

    rm = subprocess.run(
        [
            "podman",
            "rm",
            "-f",
            *container_ids,
        ],
        cwd=BASE,
        capture_output=True,
        text=True,
    )

    if rm.stdout:
        print(
            rm.stdout,
            end="",
        )

    if rm.stderr:
        print(
            rm.stderr,
            end="",
            file=sys.stderr,
        )

    if rm.returncode != 0:
        raise RuntimeError(
            "podman rm -f fallito "
            f"(exit code {rm.returncode})"
        )


def run_systemctl_user(*args):
    proc = subprocess.run(
        [
            "systemctl",
            "--user",
            *args,
        ],
        cwd=BASE,
        capture_output=True,
        text=True,
    )

    if proc.stdout:
        print(proc.stdout, end="")

    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)

    return proc


def recreate_stack():
    """
    Recreate robusto dello stack:
      1. stop della unit systemd
      2. rimozione forzata di eventuali container residui
      3. start della unit systemd
      4. se lo start fallisce (es. Podman 125), cleanup + un retry
      5. verifica running + RestartCount == 0
    """
    service = "compose-project-zomboid.service"

    log(f"Stop dello stack tramite systemd: {service}...")
    stop = run_systemctl_user("stop", service)

    if stop.returncode != 0:
        log(
            "ATTENZIONE: systemctl --user stop "
            f"{service} ha restituito exit {stop.returncode}; "
            "proseguo comunque con la rimozione forzata."
        )

    # ExecStop usa gia podman-compose down, ma questa rimozione esplicita
    # e' intenzionale e rende il flusso resiliente a container residui.
    remove_compose_containers()

    remaining = inspect_container_state()
    if remaining is not None:
        log(
            "Il container PZ risulta ancora presente; "
            "forzo la rimozione finale..."
        )
        proc = subprocess.run(
            ["podman", "rm", "-f", CONTAINER],
            cwd=BASE,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode != 0:
            raise RuntimeError(
                "Impossibile rimuovere il vecchio "
                f"{CONTAINER}: {(proc.stderr or proc.stdout).strip()}"
            )

    log(f"Avvio nuovo stack tramite systemd: {service}...")
    start = run_systemctl_user("start", service)

    if start.returncode != 0:
        log(
            "Primo start systemd fallito "
            f"(exit {start.returncode}). "
            "Eseguo cleanup completo e UN SOLO retry."
        )

        remove_compose_containers()
        remaining = inspect_container_state()

        if remaining is not None:
            proc = subprocess.run(
                ["podman", "rm", "-f", CONTAINER],
                cwd=BASE,
                capture_output=True,
                text=True,
            )
            if proc.stdout:
                print(proc.stdout, end="")
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)
            if proc.returncode != 0:
                raise RuntimeError(
                    "Cleanup recovery fallito: "
                    f"{(proc.stderr or proc.stdout).strip()}"
                )

        run_systemctl_user("reset-failed", service)
        start = run_systemctl_user("start", service)

        if start.returncode != 0:
            raise RuntimeError(
                "Avvio systemd dello stack fallito anche dopo cleanup/retry "
                f"(exit code {start.returncode})"
            )

    running, state = wait_for_container_running(timeout_seconds=30)

    if not running:
        if state:
            detail = (
                f"status={state['status']} "
                f"running={state['running']} "
                f"restarting={state['restarting']} "
                f"exit={state['exit_code']} "
                f"restart_count={state['restart_count']}"
            )
        else:
            detail = "container non presente"

        raise RuntimeError(
            "Il container appena creato non e' diventato running: "
            f"{detail}"
        )

    validate_fresh_container_state(state)

    unit_state = run_systemctl_user("is-active", service)
    if unit_state.returncode != 0 or unit_state.stdout.strip() != "active":
        raise RuntimeError(
            "Il container risulta running ma "
            f"{service} non risulta active."
        )

    log(
        "Nuovo container avviato e unit systemd attiva: "
        f"status={state['status']} "
        f"running={state['running']} "
        f"RestartCount={state['restart_count']}"
    )


def restart_server():
    """
    Flusso di ogni tentativo:

      1. recreate
      2. attesa RCON
      3. applicazione patch locali
      4. se il patcher cambia file:
           recreate aggiuntivo
           attesa RCON
           nuovo controllo patch
      5. stability check
      6. RestartCount deve restare 0

    Il patcher viene controllato una seconda volta dopo
    il recreate post-patch per evitare loop silenziosi.
    """
    last_error = None

    for attempt in range(
        1,
        MAX_START_ATTEMPTS + 1,
    ):
        log(
            "===== RESTART ATTEMPT "
            f"{attempt}/"
            f"{MAX_START_ATTEMPTS} ====="
        )

        try:
            # Primo recreate:
            # qui SteamCMD/PZ può aggiornare i Workshop item.
            recreate_stack()

            log(
                "Container ricreato. "
                "Attendo avvio completo "
                "di Project Zomboid..."
            )

            wait_for_server_ready()

            # Ora i file Workshop aggiornati sono presenti
            # sul disco. Applichiamo eventuali fix locali.
            patch_changed = (
                apply_local_fixes()
            )

            if patch_changed:
                log(
                    "Le patch locali hanno modificato "
                    "file Workshop. "
                    "Eseguo un recreate aggiuntivo "
                    "per caricare i file corretti."
                )

                recreate_stack()

                log(
                    "Container ricreato dopo le patch. "
                    "Attendo nuovamente "
                    "Project Zomboid..."
                )

                wait_for_server_ready()

                # Controllo importante:
                # dopo il secondo startup il patcher deve
                # risultare pulito. Se modifica ancora file,
                # non continuiamo all'infinito.
                patch_changed_again = (
                    apply_local_fixes()
                )

                if patch_changed_again:
                    raise LocalPatchError(
                        "Le patch locali risultano ancora "
                        "da applicare dopo il recreate "
                        "post-patch. "
                        "Interrompo per evitare un loop."
                    )

            verify_server_stability()

            state = (
                inspect_container_state()
            )

            validate_fresh_container_state(
                state
            )

            log(
                "Restart attempt "
                f"{attempt} completato "
                "con successo e verificato: "
                f"RestartCount="
                f"{state['restart_count']}."
            )

            return

        except LocalPatchError as exc:
            log(
                "Errore patch locale NON ritentabile: "
                f"{exc}"
            )

            log(
                "Il container resta nello stato corrente. "
                "Nessun secondo stop/remove/start eseguito."
            )

            raise

        except Exception as exc:
            last_error = exc

            log(
                "Restart attempt "
                f"{attempt} fallito: "
                f"{exc}"
            )

            if (
                attempt
                >= MAX_START_ATTEMPTS
            ):
                break

            log(
                "Eseguo UN SOLO tentativo "
                "di recovery: rimozione completa "
                "e nuova creazione del container."
            )

            time.sleep(5)

    raise RuntimeError(
        "Project Zomboid non è riuscito "
        "ad avviarsi in modo stabile dopo "
        f"{MAX_START_ATTEMPTS} tentativi. "
        f"Ultimo errore: {last_error}"
    )


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

    env = read_env(
        ENV_FILE
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


if __name__ == "__main__":
    try:
        sys.exit(
            main()
        )

    except KeyboardInterrupt:
        log(
            "Interrotto."
        )
        sys.exit(130)

    except Exception as exc:
        log(
            f"ERRORE: {exc}"
        )
        sys.exit(1)
