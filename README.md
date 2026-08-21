# Project Zomboid Server Scripts
Readme.md temporally created by AI

Operational scripts for a Project Zomboid Build 42 dedicated server running
with Podman Compose. They keep the server's Workshop configuration in sync
with one or more Steam collections, apply narrowly scoped local compatibility patches,
and defer mod-update restarts until the server is empty.

## Repository layout

| Directory | Purpose |
| --- | --- |
| `docker-compose/` | Compose definition and custom container entrypoint. |
| `generate-mod-list/` | Builds `PZ_MOD_IDS`, `PZ_MOD_NAMES`, and `PZ_MAP_NAMES` from Steam Workshop collections. |
| `apply-local-fixes/` | Idempotent, guarded patches for downloaded Workshop files. |
| `check-mod-updates/` | Checks active Workshop items and safely recreates the server when updates are available. |

## Requirements

- Linux host with Python 3.10+ and the `requests` package (`python3 -m pip install requests`)
- Podman and `podman-compose`
- A Project Zomboid dedicated-server installation mounted into the container
- RCON enabled in the server, with the `rcon` client installed in the container
- One or more Steam Workshop collections containing the server's mods

All paths in the examples are placeholders and must be made absolute for the
host on which the server runs. Do not commit `.env` files: they hold passwords
and local paths and are ignored by Git.

## Setup

1. Create the compose configuration:

   ```bash
   cd docker-compose
   cp .env.example .env
   ```

   Fill in server credentials, `PZ_CONTAINER`, the dedicated-server path, the
   Zomboid data path, and `PZ_ENTRYPOINT_FILE`. Keep `PZ_CONTAINER` consistent
   across all three components.

2. Generate the mod lists:

   ```bash
   cd ../generate-mod-list
   cp .env.example .env
   python3 generate-mod-list.py --output-dir ../docker-compose --env-file ../docker-compose/.env
   ```

   Set `PZ_DEFAULT_COLLECTION_ID` to one or more comma-separated Steam
   collection IDs. Set `PZ_MAP_COLLECTION_IDS` to the comma-separated
   collection IDs that contain only map mods; those collections are included in
   the Workshop list automatically. The generator does not use Steam tags or
   descriptions to classify maps. It uses an explicit map-folder value where
   available, otherwise the Workshop title, and writes the three `PZ_*`
   mod-list values to the Compose `.env`. Map mods are written before
   `Muldraugh, KY`. It also creates JSON, text, environment, and Compose reports
   in the output directory. Use `--strict` to make serious collection problems
   return exit code 2.
   Collection IDs can also be provided on the command line, separated by spaces
   or commas; their order determines the resulting mod order. Duplicate Workshop
   items are included only once.

3. Configure the local patcher:

   ```bash
   cd ../apply-local-fixes
   cp .env.example .env
   ```

   Its `.env` needs these values:

   ```dotenv
   PZ_SERVER_DIR=/absolute/path/to/this-repository/apply-local-fixes
   PZ_DEDICATED_SERVER_DIR=/absolute/path/to/DedicatedServer
   PZ_CONTAINER=game-project-zomboid
   ```

4. Configure the update checker:

   ```bash
   cd ../check-mod-updates
   cp .env.example .env
   ```

   In addition to the sample values, define `PZ_CONTAINER`, `PZ_RCON_PORT`, and
   `PZ_RCON_PASSWORD`. `PZ_SERVER_DIR` points to the directory containing this
   component's `docker-compose.yml` and `.env`; `PZ_LOCAL_FIXES` points to
   `apply-local-fixes.py`.

5. Start the server:

   ```bash
   cd ../docker-compose
   podman-compose up -d
   ```

## Normal operation

Regenerate the mod configuration whenever a collection changes:

```bash
cd generate-mod-list
python3 generate-mod-list.py --output-dir ../docker-compose --env-file ../docker-compose/.env
cd ../docker-compose
podman-compose up -d
```

Run local patches after the Workshop content has been downloaded:

```bash
cd apply-local-fixes
python3 apply-local-fixes.py
```

The patcher returns `0` when no file changed, `10` when it changed one or more
files, `1` for an error, and `130` when interrupted. A successful modifying run
usually requires one Compose recreate before players use the patched content.

Run the update check manually with:

```bash
cd check-mod-updates
python3 check-mod-updates.py
```

It reads active Workshop IDs from `PZ_MOD_IDS`, establishes a no-restart
baseline on its first successful run, and only acts on updates when the
container is running, RCON is available, and no players are connected. It
recreates the Compose project, applies local fixes, waits for the server to be
healthy, and records the new Workshop state only after the stability window
passes.

To schedule it, customize the supplied user-level systemd service and timer
with the absolute paths for this checkout, then install and enable them:

```bash
cd check-mod-updates
mkdir -p ~/.config/systemd/user
cp pz-mod-check.service pz-mod-check.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pz-mod-check.timer
sudo loginctl enable-linger "$USER"
```

The timer runs every 15 minutes and catches up after downtime.

## Local Workshop fixes

`apply-local-fixes.py` loads `fix-scripts/*.py` alphabetically; numeric prefixes
therefore define the order. Each fix is designed to be idempotent and refuses
to patch an unexpected upstream structure rather than guessing. Backups use a
`.pz-local-fix*.bak` suffix, and the patcher stores managed-file state in
`.pz-local-fixes-state.json`.

The current fixes are:

- `10-weldingrodmod-craft-plaster.py`: replaces the obsolete
  `Base.CrushedLimestone` item name in WeldingRodMod and Craft Plaster scripts.
- `20-companion-dogs.py`: maintains compatible shared `TimedActions` copies for
  Companion Dogs, while relinquishing ownership when an upstream implementation
  appears.
- `30-vro-nearby-containers.py`: integrates Vehicle Repair Overhaul (VRO) with
  an optional nearby-containers companion API; it backs up and verifies the
  container-visible file before retaining the ten newest backups.
- `40-vro-trunk-capacity.py`: corrects VRO's legacy trunk-capacity sweep only
  for its known upstream file hash.
- `50-vro-material-list-order.py`: sorts VRO repair materials from highest to
  lowest potential condition repair, for both vehicle and inventory repair
  submenus. Existing vanilla entries retain their positions, ties preserve the
  original order, and a dedicated backup is created before the patch is written.

When a Workshop author changes a patched file, inspect the upstream change and
update the corresponding exact-match patch before running it again. Do not
remove the marker or backup merely to force a patch through.

## Generated state and backups

The scripts intentionally create local operational files:

- `.pz-mod-check-state.json` from the update checker
- `.pz-local-fixes-state.json` from the patcher
- timestamped and `.pz-local-fix*.bak` backups

The state files and backups are ignored by Git and make repeated runs safe.
The mod-list generator also writes `project-zomboid-mods.*` reports to its
chosen output directory; retain or version those reports according to the
deployment's own change-management practice.
