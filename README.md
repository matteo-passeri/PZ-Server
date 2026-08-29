# Project Zomboid Server Scripts

Operational scripts for a Project Zomboid Build 42 dedicated server running
with Podman Compose. The repository root is the deployment directory: copy the
whole checkout to the server root and run all commands from there.

## Features

- Starts and configures a containerized Project Zomboid dedicated server with
  Podman/Docker Compose.
- Generates Workshop, Mod ID, and map lists from ordered Steam collections,
  including explicit dependency and final-load rules.
- Reorders generated mod lists using configurable load-order rules, so required
  mods can be placed first, before or after other mods, or last.
- Applies safe, idempotent local compatibility fixes to downloaded Workshop
  content, including targeted Linux filesystem case aliases and the narrowly
  scoped RadArchery B42 Bob GLB channel repair (Workshop `3775407541`).
- Detects Workshop updates, waits for an empty server, then performs a guarded
  recreate and verification workflow.
- Audits the latest server DebugLog into readable startup and on-demand runtime
  reports, classifying critical, dependency, animation, and low-noise issues.
- Runs one best-effort startup audit after the server reaches the SERVER STARTED
  marker; runtime audits are manual and consume no background resources.
- Provides optional user-level systemd templates for periodic update checks.

## How It Runs

1. Configure `.env` with the server paths, credentials, and Workshop
   collections, then generate the current mod lists via `generate-mod-lists.py`.
2. Start the Compose service. The entrypoint applies server settings and starts
   Project Zomboid.

         That's it! You can play now.

3. Once the current DebugLog reaches the SERVER STARTED marker, a one-shot
   startup audit writes a report under `reports/` and exits.
4. Run `check-mod-updates.py` manually or through the optional systemd timer to
   check Workshop updates. When the server is empty, it recreates the service,
   applies local fixes, and verifies the new server instance.
5. Run `audit-server-log.py --runtime` whenever a runtime diagnostic snapshot
   is needed; it reads the current log once and does not install a watcher.

## Layout

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Server Compose definition. |
| `entrypoint.sh` | Custom container entrypoint. |
| `generate-mod-list.py` | Resolves collections and mod rules, then builds `PZ_MOD_IDS`, `PZ_MOD_NAMES`, and `PZ_MAP_NAMES`. |
| `mod-rules.toml` | Version-controlled shared Mod-ID compatibility policy. |
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

Collection order supplies the normal stable base order. Verified framework and
dependency exceptions are encoded as hard Mod ID rules in `MOD_LOAD_FIRST`,
`MOD_LOAD_BEFORE`, and `MOD_LOAD_AFTER`; diagnostic and final override mods use
the ordered `MOD_LOAD_LAST` group. These rules affect `PZ_MOD_NAMES`/`Mods=`
only; `PZ_MOD_IDS` remains the normal unique Workshop ID list used by the update
checker. `PZ_LASTTOLOAD_COLLECTION_ID` is no longer supported.

## Maintaining mod rules

`mod-rules.toml` is the shared, version-controlled compatibility layer.
`.env` remains the administrator layer for one server: use
`PZ_MOD_BLACKLIST_WORKSHOP`, `PZ_MOD_BLACKLIST_MODS`,
`PZ_MOD_FORCED_WORKSHOP`, and `PZ_MOD_FORCED_MODS` for explicit local choices.
Do not put generally known compatibility knowledge in `.env`.

To always exclude a known obsolete Mod ID, add one string under
`[mods].always_exclude`:

```toml
[mods]
always_exclude = [
    "ObsoleteMod",
]
```

To select a normal variant when both are available, add a `prefer` rule. A
reason documents non-obvious compatibility knowledge. Set `enabled = false`
to temporarily disable a structured rule, or remove/comment it out.

```toml
[[mods.prefer]]
winner = "WorkingGutters"
losers = ["WorkingGuttersRemoved"]
reason = "These variants are mutually exclusive."
```

Some mods provide a `Removed` placeholder which existing saves must keep after
the original mod is intentionally disabled. Declare it on the same `prefer`
rule; it is not a generic replacement for fresh worlds:

```toml
[[mods.prefer]]
winner = "FunctionalGutters"
losers = ["FunctionalGuttersRemoved"]
removed_fallback = "FunctionalGuttersRemoved"
reason = "Keep placeholder definitions for existing saves after removing the original mod."
```

After the server reaches `SERVER STARTED`, the host-side startup audit records
the resolved `Mods=` IDs in the ignored root-level
`.pz-last-successful-mods.json` state file. On a later generation, if that
successful state contained `FunctionalGutters` and an administrator sets
`PZ_MOD_BLACKLIST_MODS=FunctionalGutters`, the resolver activates
`FunctionalGuttersRemoved` when it is available from the resolved Workshop
items. It never rewrites `.env`: the fallback is derived state, while `.env`
continues to express administrator intent.

With `PZ_MOD_BLACKLIST_MODS=FunctionalGutters;FunctionalGuttersRemoved`,
neither is enabled. The administrator blacklist wins and the generator reports
the blocked fallback. If the placeholder cannot be resolved from current
Workshop content, it reports an unresolved fallback and does not invent a
Workshop ID. On a first run, or when the original mod was never in successful
state, no fallback is automatically added.

### Automatic Removed pairs

When one resolved Workshop item exposes exact, case-sensitive Mod IDs `Foo`
and `FooRemoved`, the generator automatically treats `Foo` as preferred over
`FooRemoved`. The item may expose additional Mod IDs; only the exact pair is
affected. IDs split across Workshop items, and names such as `Foo_Removed` or
`fooRemoved`, are not inferred.

This automatic relationship is a normal `prefer` only. It never creates a
historical-save fallback. Add an explicit rule with `removed_fallback` when
the Removed ID is known to preserve an existing save. Explicit TOML rules take
precedence over inference, including `enabled = false`, which deliberately
suppresses an otherwise inferred pair. Inferred pairs are reported in generated
JSON and under `AUTO-DETECTED REMOVED VARIANTS`; they are never written to
`.env` or `mod-rules.toml`.

Startup and runtime log audits separately identify WorldDictionary removed-mod
diagnostics, including `WorldDictionaryException`, missing dictionary scripts,
world-load dictionary errors, and nearby `removed = true` / `modID = ...`
details. When a Mod ID has a declared fallback, the audit reports it; otherwise
it requests manual investigation. Client-side WorldDictionary failures may not
always appear in the dedicated-server log, so successful-state transition is
the primary compatibility mechanism.

For an incompatibility without a universal winner, report it rather than
silently choosing one:

```toml
[[mods.conflict]]
mods = ["ModA", "ModB"]
reason = "These variants cannot be enabled simultaneously."
```

Validate an edit without Steam, Workshop content, or a server installation:

```bash
python3 generate-mod-list.py --validate-rules
python3 generate-mod-list.py --list-rules
```

Resolution is deterministic: collections are read first; project
`always_exclude` and administrator blacklists remove candidates; enabled
`prefer` rules run in file order against that evolving active set; administrator
Removed fallbacks are considered from previous successful state; administrator
forced additions are appended; conflicts are reported; then the existing
load-order rules run. A preference cycle is rejected during validation.

Forced Mod IDs retain their existing explicit-administrator semantics: they are
appended after project exclusions and preferences, so a forced ID can override
an exclusion. Conflicting blacklist/forced entries are warned about and forced
inclusion wins.

### Build 42 `mod.info` metadata

For each selected local Build 42 `mod.info`, the generator reads `require`,
`incompatible`, `loadModAfter`, and `loadModBefore` in addition to `id`.
Comma- and semicolon-separated values are supported. `loadModAfter` and
`loadModBefore` contribute active edges to the existing stable topological
sort; curated built-in rules such as `NeatUI_Framework -> CleanUI` are merged
and deduplicated with those edges. Curated rules remain useful where upstream
metadata is absent or incomplete.

`require` is dependency validation only: a missing active requirement is
reported but is neither added nor used as a load-order edge. `incompatible`
reports a conflict without selecting a winner. The generated report and JSON
identify these diagnostics and their `mod.info` source path. Administrator
blacklists/forced IDs and `mod-rules.toml` resolution still determine which Mod
IDs are active before this metadata is evaluated.

### Workshop Mod ID selection

Workshop discovery, Mod ID selection, and Mod ID dependency/load ordering are
separate steps. A Workshop item may expose several IDs without all of them
being valid to activate together. The small curated `MOD_SELECTION_RULES`
mapping in `generate-mod-list.py` is reserved for verified item-specific
defaults, optional add-ons, mutually exclusive variants, conditional variants,
and known Removed replacements. It is deliberately separate from the curated
load-order lists and from `mod-rules.toml` compatibility rules.

Administrator choices still take precedence: `PZ_MOD_ID_OVERRIDES` and
`PZ_MOD_FORCED_MODS` can select a valid variant or optional add-on, while a
blacklist prevents a curated or derived default from being re-added. Requesting
two variants in the same curated exclusive group is rejected instead of picking
one arbitrarily. Without a matching selection rule, existing unresolved
multi-Mod-ID behaviour is retained.

Within one Workshop item only, an exact case-sensitive `Foo` / `FooRemoved`
pair is automatically recognized as mutually exclusive. Normal automatic
selection retains `Foo` and excludes `FooRemoved`; names such as
`Foo_Removed`, or IDs in different Workshop items, are not inferred. This name
match does not make `FooRemoved` a historical-save replacement. Activating a
Removed placeholder after a previous successful `Foo` configuration requires
an explicit curated `removed_replacements` entry and only happens when that
base Mod ID is no longer selected.

For example, a collection containing `WorkingGutters` and
`WorkingGuttersRemoved` keeps `WorkingGutters`. With
`PZ_MOD_BLACKLIST_MODS=WorkingGutters`, the winner is removed before preference
evaluation, so `WorkingGuttersRemoved` remains active. Chained rules therefore
behave predictably: `A -> B` followed by `B -> C`, with `A,B,C` active, results
in `A,C` because the first rule removed `B`.

Workshop IDs and Mod IDs are deliberately separate. A Workshop item can expose
several Mod IDs. Excluding one Mod ID never removes its Workshop item, even if
it is currently the only resolved ID: retaining it is conservative for shared
assets, dependencies, and incomplete metadata. Only an explicit administrator
Workshop blacklist removes a Workshop item. The generator is the authoritative
resolver; the container entrypoint consumes its generated lists unchanged.

For a multi-Mod-ID Workshop item with no item-specific selection rule,
`mods.always_exclude` can resolve the item when it leaves exactly one viable
Mod ID. If two or more viable IDs remain, the item stays unresolved rather than
choosing one arbitrarily.

Run local patches after Workshop content downloads:

```bash
python3 apply-local-fixes.py
```

Audit the latest Project Zomboid server DebugLog, or a specific saved log:

```bash
./audit-server-log.py
./audit-server-log.py --log /path/to/DebugLog-server.txt --all
```

Reports are written under the ignored `reports/` directory. Runtime audits are
manual. A separate host-side systemd service runs one startup audit after the
server writes its SERVER STARTED marker, then exits.

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

To install the host-side startup audit service, replace the deployment path
placeholder in `pz-startup-audit.service`, then run:

```bash
sudo cp pz-startup-audit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pz-startup-audit.service
```

`WantedBy=compose-project-zomboid.service` creates a non-failing Wants
relationship when the audit service is enabled. Verify it with:

```bash
systemctl show -p Wants compose-project-zomboid.service
systemctl status pz-startup-audit.service
journalctl -u pz-startup-audit.service -b
```

## Local State

`.env`, generated mod-list outputs, state files, Python caches, and backup
artifacts are ignored by Git. Do not commit operational `.bak`, `.backup`, or
`before-*` files.
