#!/usr/bin/env python3
"""Wait for the current PZ startup log, then generate one host-side report."""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
STARTED_MARKER = "*** SERVER STARTED ****"
DEFAULT_TIMEOUT = 20 * 60
TOLERANCE_SECONDS = 3


def log(message):
    print(f"[PZ-STARTUP-AUDIT] {message}", flush=True)


def read_env(path):
    values = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def container_start_time(container):
    result = subprocess.run(
        ["podman", "inspect", container, "--format", "{{.State.StartedAt}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw or raw.startswith("0001-"):
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


def select_current_log(logs_dir, started_at):
    candidates = [
        path
        for path in logs_dir.glob("*DebugLog-server.txt")
        if path.is_file() and path.stat().st_mtime >= started_at - TOLERANCE_SECONDS
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def has_started_marker(path):
    return STARTED_MARKER in path.read_text(encoding="utf-8", errors="replace")


def wait_for_startup_log(logs_dir, started_at, timeout, poll_interval, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    log("Waiting for current PZ startup log...")
    selected = None
    while clock() < deadline:
        candidate = select_current_log(logs_dir, started_at)
        if candidate and candidate != selected:
            selected = candidate
            log(f"Current startup log detected: {selected}")
            log("Waiting for SERVER STARTED...")
        if selected and has_started_marker(selected):
            log("SERVER STARTED detected.")
            return selected
        sleep(poll_interval)
    return None


def run_reporter(log_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "audit-server-log.py"), "--log", str(log_path), "--startup"],
        check=False,
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Run one host-side PZ startup audit.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--poll-interval", type=int, default=3)
    args = parser.parse_args()
    env = read_env(ENV_FILE)
    data_dir = Path(env["PZ_ZOMBOID_DATA_DIR"]).expanduser()
    container = env["PZ_CONTAINER"]
    deadline = time.monotonic() + args.timeout
    started_at = None
    while time.monotonic() < deadline and started_at is None:
        started_at = container_start_time(container)
        if started_at is None:
            log("Waiting for Project Zomboid container start...")
            time.sleep(args.poll_interval)
    if started_at is None:
        log("Startup audit timed out waiting for the container start time.")
        return 1
    log_path = wait_for_startup_log(
        data_dir / "Logs", started_at, max(0, deadline - time.monotonic()), args.poll_interval
    )
    if log_path is None:
        log("Startup audit timed out waiting for SERVER STARTED.")
        return 1
    if not run_reporter(log_path):
        log("Startup audit reporter failed; the Project Zomboid service is unaffected.")
        return 1
    log("Startup audit report created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
