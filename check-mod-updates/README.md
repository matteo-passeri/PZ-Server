# Project Zomboid Mod Update Checker

Safely monitors the Steam Workshop items configured for a Project Zomboid
dedicated server. When an update is published, it recreates the server only
while it is empty, applies local compatibility fixes, and verifies that the
new server instance is stable before recording the new Workshop state.

## What It Does

- Reads active Workshop IDs from `PZ_MOD_IDS` in the server `.env` file.
- Queries Steam in batches and persists the latest `time_updated` values.
- Creates a baseline on the first run without restarting the server.
- Skips all work when the container is stopped, RCON is unavailable, or
  players are connected.
- Recreates the Podman Compose stack when a Workshop update is detected.
- Runs `apply-local-fixes.py` after the update and recreates the stack once
  more when a fix changes Workshop files.
- Confirms RCON connectivity and a zero restart count during a stability
  window before committing the updated state.

Only one check can run at a time. The lock is stored at
`/tmp/pz-mod-check.lock`.

## Requirements

- Python 3
- Podman and `podman-compose`
- A running container named `game-project-zomboid`
- A user systemd unit named `compose-project-zomboid.service`
- RCON enabled inside the server container, with `rcon` available at
  `/usr/local/bin/rcon`
- `RCON_PASSWORD` available in the container environment

The script currently targets this server directory:

```text
/home/matteo/containers/project-zomboid
```

Update the constants at the top of `check-mod-updates.py` if your deployment
uses different paths, service names, container names, or RCON settings.

## Server Configuration

The server `.env` must define Workshop IDs as a semicolon-separated list:

```dotenv
PZ_MOD_IDS=1234567890;2345678901;3456789012
```

Install `apply-local-fixes.py` and its `fix-scripts/` directory in the server
directory when local Workshop patches are needed. The patcher returns `10`
when it modifies files, which triggers one additional recreate.

## Run Manually

Make the script executable once, then invoke it directly:

```bash
chmod +x check-mod-updates.py
./check-mod-updates.py
```

Logs are written to standard output with the `[PZ-MOD-CHECK]` prefix. The
first successful run creates `.pz-mod-check-state.json` in the server
directory and does not restart the server.

## Schedule With systemd

Copy and customize the included unit files:

```bash
mkdir -p ~/.config/systemd/user
cp pz-mod-check.service pz-mod-check.timer ~/.config/systemd/user/
```

In `~/.config/systemd/user/pz-mod-check.service`, replace the placeholder
paths in `WorkingDirectory` and `ExecStart` with the absolute path to this
`check-mod-updates` directory.

Then load and enable the timer:

```bash
systemctl --user daemon-reload
systemctl --user enable --now pz-mod-check.timer
```

Useful checks:

```bash
systemctl --user status pz-mod-check.timer
systemctl --user list-timers pz-mod-check.timer
journalctl --user -u pz-mod-check.service -f
```

The supplied timer runs every 15 minutes and catches up after downtime because
`Persistent=true` is enabled.

For a headless server, also enable lingering once so the user service manager
keeps running after logout:

```bash
sudo loginctl enable-linger <your_username>
```
