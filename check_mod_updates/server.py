import re
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .config import LocalPatchError, log


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


def configure():
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

    BASE = config.BASE
    STATE_FILE = config.STATE_FILE
    LOCK_FILE = config.LOCK_FILE
    CONTAINER = config.CONTAINER
    LOCAL_FIXES = config.LOCAL_FIXES
    RCON_PORT = config.RCON_PORT
    RCON_BIN = config.RCON_BIN
    RCON_PASSWORD = config.RCON_PASSWORD
    SERVER_READY_TIMEOUT = config.SERVER_READY_TIMEOUT
    SERVER_READY_POLL = config.SERVER_READY_POLL
    SERVER_STABILITY_SECONDS = config.SERVER_STABILITY_SECONDS
    SERVER_STABILITY_POLL = config.SERVER_STABILITY_POLL
    PROJECT_NAME = config.PROJECT_NAME
    MAX_START_ATTEMPTS = config.MAX_START_ATTEMPTS


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

    proc = subprocess.run(
        [
            "podman",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-lc",
            (
                'RCON_PASSWORD="$(cat)"; '
                "export RCON_PASSWORD; "
                'exec "$1" -a "$2" -p "$RCON_PASSWORD" -T "$3" "$4"'
            ),
            "rcon",
            RCON_BIN,
            f"{rcon_host}:{RCON_PORT}",
            "10s",
            command,
        ],
        input=RCON_PASSWORD,
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
    timeout_seconds=None,
):
    if timeout_seconds is None:
        timeout_seconds = SERVER_READY_TIMEOUT

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
    stability_seconds=None,
):
    if stability_seconds is None:
        stability_seconds = SERVER_STABILITY_SECONDS

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
