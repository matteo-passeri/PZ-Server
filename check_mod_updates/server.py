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
            "Container not found"
        )

    if not state["running"]:
        raise RuntimeError(
            "Container not running "
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
            "Unable to determine RestartCount"
        )

    if restart_count != 0:
        raise RuntimeError(
            "The new container has already "
            "restarted on its own "
            f"(RestartCount={restart_count}). "
            "Startup considered INVALID."
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
            "Unable to read container IP: "
            + proc.stderr.strip()
        )

    ip = proc.stdout.strip()

    if not ip:
        raise RuntimeError(
            "Container IP unavailable"
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
            "RCON command failed"
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
        "Unrecognized 'players' response format. "
        f"RCON response: {output!r}"
    )


# ------------------------------------------------------------
# Local patches
# ------------------------------------------------------------

def apply_local_fixes():
    """
    Run apply-local-fixes.py.

    Return:
      False -> no file changed
      True  -> patches applied; a new recreate is needed

    Exit code patcher:
      0  = no changes
      10 = one or more changes
      other = error
    """
    if not Path(
        LOCAL_FIXES
    ).is_file():
        raise RuntimeError(
            f"Local patcher not found: "
            f"{LOCAL_FIXES}"
        )

    log(
        "Checking local patches after update..."
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
            "Local patches already correct: "
            "no additional recreate needed."
        )
        return False

    if proc.returncode == 10:
        log(
            "Local patches applied: "
            "an additional recreate is needed "
            "to load the changed files."
        )
        return True

    raise LocalPatchError(
        "apply-local-fixes.py failed "
        f"(exit code {proc.returncode})"
    )


def audit_startup_log():
    """Run the log reporter without affecting the server update workflow."""
    reporter = config.SCRIPT_DIR / "audit-server-log.py"
    if not reporter.is_file():
        log(f"Server log audit unavailable: reporter not found: {reporter}")
        return

    log("Auditing the Project Zomboid startup log...")
    try:
        proc = subprocess.run(
            [sys.executable, str(reporter), "--startup"],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"Server log audit failed (non-blocking): {exc}")
        return

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        log(f"Server log audit failed (non-blocking): exit code {proc.returncode}")


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
                "Project Zomboid ready through RCON: "
                f"{players} connected players."
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
                "Container running with "
                "RestartCount=0, but PZ "
                "is not ready yet. "
                "Waiting for RCON... "
                f"({remaining}s until timeout)"
            )

            next_log = (
                now + 60
            )

        time.sleep(
            SERVER_READY_POLL
        )

    raise RuntimeError(
        "Timeout: Project Zomboid did not "
        "become available through RCON "
        f"within {timeout_seconds}s"
    )


def verify_server_stability(
    stability_seconds=None,
):
    if stability_seconds is None:
        stability_seconds = SERVER_STABILITY_SECONDS

    log(
        "RCON is working. "
        f"Checking stability for "
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
                "RCON became unavailable "
                "during the stability period: "
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
            "Stability OK: "
            f"RestartCount={state['restart_count']}, "
            f"RCON OK, "
            f"players={players}. "
            f"About {remaining}s remaining."
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
        "Stability period completed: "
        f"RestartCount={state['restart_count']}, "
        f"RCON working, "
        f"players={players}, "
        f"successful checks={consecutive_successes}."
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
            "Unable to obtain the list "
            "of stack containers: "
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
            "No old stack containers "
            "to remove."
        )
        return

    log(
        "Explicitly removing "
        f"{len(container_ids)} "
        "stack containers..."
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
            "podman rm -f failed "
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
    Robust stack recreate:
      1. stop the systemd unit
      2. force-remove any remaining containers
      3. start the systemd unit
      4. if startup fails (for example Podman 125), clean up and retry once
      5. verify running + RestartCount == 0
    """
    service = "compose-project-zomboid.service"

    log(f"Stopping stack through systemd: {service}...")
    stop = run_systemctl_user("stop", service)

    if stop.returncode != 0:
        log(
            "WARNING: systemctl --user stop "
            f"{service} returned exit {stop.returncode}; "
            "continuing with force removal anyway."
        )

    # ExecStop already uses podman-compose down, but this explicit removal is
    # intentional and makes the flow resilient to leftover containers.
    remove_compose_containers()

    remaining = inspect_container_state()
    if remaining is not None:
        log(
            "The PZ container is still present; "
            "forcing final removal..."
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
                "Unable to remove the old "
                f"{CONTAINER}: {(proc.stderr or proc.stdout).strip()}"
            )

    log(f"Starting new stack through systemd: {service}...")
    start = run_systemctl_user("start", service)

    if start.returncode != 0:
        log(
            "Initial systemd start failed "
            f"(exit {start.returncode}). "
            "Running full cleanup and ONE retry."
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
                    "Cleanup recovery failed: "
                    f"{(proc.stderr or proc.stdout).strip()}"
                )

        run_systemctl_user("reset-failed", service)
        start = run_systemctl_user("start", service)

        if start.returncode != 0:
            raise RuntimeError(
                "Systemd stack start failed even after cleanup/retry "
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
            detail = "container not found"

        raise RuntimeError(
            "The newly created container did not become running: "
            f"{detail}"
        )

    validate_fresh_container_state(state)

    unit_state = run_systemctl_user("is-active", service)
    if unit_state.returncode != 0 or unit_state.stdout.strip() != "active":
        raise RuntimeError(
            "The container is running but "
            f"{service} is not active."
        )

    log(
        "New container started and systemd unit active: "
        f"status={state['status']} "
        f"running={state['running']} "
        f"RestartCount={state['restart_count']}"
    )


def restart_server():
    """
    Flow for each attempt:

      1. recreate
      2. wait for RCON
      3. apply local patches
      4. if the patcher changes files:
           additional recreate
           wait for RCON
           check patches again
      5. stability check
      6. RestartCount must remain 0

    The patcher is checked a second time after the post-patch recreate to
    prevent silent loops.
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
            # First recreate:
            # SteamCMD/PZ may update Workshop items here.
            recreate_stack()

            log(
                "Container recreated. "
                "Waiting for Project Zomboid "
                "to fully start..."
            )

            wait_for_server_ready()

            audit_startup_log()

            # Updated Workshop files are now present on disk.
            # Apply any local fixes.
            patch_changed = (
                apply_local_fixes()
            )

            if patch_changed:
                log(
                    "Local patches changed "
                    "Workshop files. "
                    "Running an additional recreate "
                    "to load the correct files."
                )

                recreate_stack()

                log(
                    "Container recreated after patches. "
                    "Waiting for Project Zomboid "
                    "again..."
                )

                wait_for_server_ready()

                audit_startup_log()

                # Important check: after the second startup, the patcher must
                # be clean. Do not continue indefinitely if it changes files
                # again.
                patch_changed_again = (
                    apply_local_fixes()
                )

                if patch_changed_again:
                    raise LocalPatchError(
                        "Local patches still need to be "
                        "applied after the post-patch "
                        "recreate. "
                        "Stopping to prevent a loop."
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
                f"{attempt} completed "
                "successfully and verified: "
                f"RestartCount="
                f"{state['restart_count']}."
            )

            return

        except LocalPatchError as exc:
            log(
                "NON-retryable local patch error: "
                f"{exc}"
            )

            log(
                "The container remains in its current state. "
                "No second stop/remove/start performed."
            )

            raise

        except Exception as exc:
            last_error = exc

            log(
                "Restart attempt "
                f"{attempt} failed: "
                f"{exc}"
            )

            if (
                attempt
                >= MAX_START_ATTEMPTS
            ):
                break

            log(
                "Running ONE recovery attempt: full removal "
                "and a new container creation."
            )

            time.sleep(5)

    raise RuntimeError(
        "Project Zomboid failed "
        "to start stably after "
        f"{MAX_START_ATTEMPTS} attempts. "
        f"Last error: {last_error}"
    )
