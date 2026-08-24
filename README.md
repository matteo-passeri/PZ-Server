# Project Zomboid Server Scripts

Operational scripts for a Project Zomboid Build 42 dedicated server running
with Podman Compose. The repository root is the deployment directory: copy the
whole checkout to the server root and run all commands from there.

## Layout

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Server Compose definition. |
| `entrypoint.sh` | Custom container entrypoint. |
| `generate-mod-list.py` | Builds `PZ_MOD_IDS`, `PZ_MOD_NAMES`, and `PZ_MAP_NAMES` from Steam Workshop collections. |
| `apply-local-fixes.py` and `fix-scripts/` | Idempotent, guarded patches for downloaded Workshop files. |
| `check-mod-updates.py` and `check_mod_updates/` | Detects Workshop updates and safely recreates the server when it is empty. |
| `pz-mod-check.service` and `pz-mod-check.timer` | Optional user-level systemd scheduling templates. |

The generator writes these untracked operational files to the root:
`project-zomboid-mods-compose.yml`, `project-zomboid-mods.env`,
`project-zomboid-mods.json`, and `project-zomboid-mods-report.txt`.

## Setup

```bash
cp .env.example .env
```

Fill in the credentials, deployment paths, and Steam collection configuration.
Keep `.env` private and untracked. `PZ_SERVER_DIR` must be the absolute path to
this repository root and `PZ_LOCAL_FIXES` must point to the root-level
`apply-local-fixes.py`.

Generate the mod lists and start the server from the root:

```bash
python3 generate-mod-list.py --output-dir . --env-file .env
podman-compose up -d
```

The generator preserves collection order except for the explicit rules in
`MOD_LOAD_BEFORE` and `MOD_LOAD_AFTER`. Those rules affect `PZ_MOD_NAMES`/
`Mods=` only; `PZ_MOD_IDS` remains the Workshop ID list used by the update
checker. `PZ_LASTTOLOAD_COLLECTION_ID` moves the selected Workshop collection
to the end while retaining its internal order.

Run local patches after Workshop content downloads:

```bash
python3 apply-local-fixes.py
```

The patcher loads root-level `fix-scripts/*.py` alphabetically. It returns `0`
when no file changed, `10` when it changed files, `1` for an error, and `130`
when interrupted. A modifying run usually requires a Compose recreate.

Run the update check manually with:

```bash
python3 check-mod-updates.py
```

It reads active Workshop IDs from the root `.env`, waits for an empty server,
recreates the Compose project, applies local fixes, and records the new
Workshop state after the stability window.

To schedule it, customize the root-level systemd templates with the absolute
path to this checkout, then install and enable them:

```bash
mkdir -p ~/.config/systemd/user
cp pz-mod-check.service pz-mod-check.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pz-mod-check.timer
sudo loginctl enable-linger "$USER"
```

## Local State

`.env`, generated mod-list outputs, state files, Python caches, and backup
artifacts are ignored by Git. Do not commit operational `.bak`, `.backup`, or
`before-*` files.
