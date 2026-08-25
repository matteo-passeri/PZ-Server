#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_FILE = SCRIPT_DIR / ".env"

APP_ID = None
DEFAULT_COLLECTION_ID = None
MAP_COLLECTION_IDS = None
LAST_TO_LOAD_COLLECTION_IDS = None
COLLECTION_API = None
DETAILS_API = None
USER_AGENT = None
MANAGED_ENV_KEYS = None
BACKUPS_TO_KEEP = None
DEFAULT_WORKSHOP_ROOT = None
MOD_ID_OVERRIDES = None
MOD_BLACKLIST_MODS = None

# Hard Mod ID load-order rules.  These affect PZ_MOD_NAMES (the server Mods=
# value), never PZ_MOD_IDS (the WorkshopItems= value).
#
# Add a pair here when the first Mod ID must load before the second.  Add a
# pair to MOD_LOAD_AFTER when the first Mod ID must load after the second.
# MOD_LOAD_LAST is for the one Mod ID that must load after every other active
# Mod ID.
MOD_LOAD_BEFORE = [
    ("HBVCEFb42", "SWMG"),
    ("NeatUI_Framework", "Neat_Crafting"),
    ("NeatUI_Framework", "Project_Cook"),
    ("Neat_Crafting", "Project_Cook"),
    ("Project_Cook", "Project_Cook_Pixel_Icon_Pack"),
    ("NeatUI_Framework", "Neat_Building"),
    ("damnlib", "rWaterTrailerB42"),
    ("tsarslib", "rWaterTrailerB42"),
    ("82oshkoshM911", "rWaterTrailerB42"),
    ("rSemiTruck", "rWaterTrailerB42"),
    ("rWaterTrailerB42", "rWaterTrailerSemiB42"),
    ("VehicleRepairOverhaul", "VehicleSalvageOverhaulB42"),
    ("VehicleRepairOverhaul", "VRONearbyContainers"),
    ("CompanionDogs", "CompanionDogsRottweiler"),
    ("CompanionDogs", "CompanionDogsDoberman"),
    ("AMMS_Standalone", "errorMagnifier"),
]
MOD_LOAD_AFTER = [
    ("SWMG", "HBVCEFb42"),
    ("MarzVanillaGuns", "SWMG"),
    ("MarzVanillaGuns", "HBVCEFb42"),
]
MOD_LOAD_LAST = "Linux_Animsets_Marz_Mods"
class SteamAPIError(RuntimeError):
    pass


class ModLoadOrderError(RuntimeError):
    """Raised when active hard Mod ID ordering rules are contradictory."""


def normalize_mod_info_order_value(value: str) -> str:
    """Remove one accidental leading backslash from mod.info order metadata."""
    return value[1:] if value.startswith("\\") else value


def parse_mod_info(path: Path) -> dict[str, list[str]]:
    """Read selected mod.info fields, retaining their declared value order."""
    fields = {
        "id": [],
        "loadmodafter": [],
        "loadmodbefore": [],
        "require": [],
    }

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fields

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lower()
        if key not in fields:
            continue

        # PZ commonly separates multi-value metadata fields with semicolons.
        # This metadata is only inspected for now; require= does not create an
        # automatic load-order edge.  An id= value itself remains singular.
        values = [value] if key == "id" else value.split(";")
        for item in values:
            item = item.strip()
            if key != "id":
                item = normalize_mod_info_order_value(item)
            if item and item not in fields[key]:
                fields[key].append(item)

    return fields


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f".env not found: {path}")

    result: dict[str, str] = {}

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
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


def required_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(f"{key} is missing or empty in {CONFIG_ENV_FILE}")

    return value


def positive_int_env(env: dict[str, str], key: str) -> int:
    raw = required_env(env, key)

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{key} must be a positive integer: {raw!r}"
        ) from exc

    if value <= 0:
        raise RuntimeError(f"{key} must be greater than zero: {value}")

    return value


def load_configuration() -> None:
    global APP_ID
    global DEFAULT_COLLECTION_ID
    global MAP_COLLECTION_IDS
    global LAST_TO_LOAD_COLLECTION_IDS
    global COLLECTION_API
    global DETAILS_API
    global USER_AGENT
    global MANAGED_ENV_KEYS
    global BACKUPS_TO_KEEP
    global DEFAULT_WORKSHOP_ROOT
    global MOD_ID_OVERRIDES
    global MOD_BLACKLIST_MODS

    env = read_env(CONFIG_ENV_FILE)

    APP_ID = positive_int_env(env, "PZ_APP_ID")
    DEFAULT_COLLECTION_ID = required_env(env, "PZ_DEFAULT_COLLECTION_ID")
    MAP_COLLECTION_IDS = env.get("PZ_MAP_COLLECTION_IDS", "").strip()
    LAST_TO_LOAD_COLLECTION_IDS = env.get(
        "PZ_LASTTOLOAD_COLLECTION_ID", ""
    ).strip()
    COLLECTION_API = required_env(env, "PZ_COLLECTION_API")
    DETAILS_API = required_env(env, "PZ_DETAILS_API")
    USER_AGENT = required_env(env, "PZ_USER_AGENT")
    BACKUPS_TO_KEEP = positive_int_env(env, "PZ_BACKUPS_TO_KEEP")
    DEFAULT_WORKSHOP_ROOT = (
        Path(
            required_env(env, "PZ_DEDICATED_SERVER_DIR")
        ).expanduser()
        / "steamapps/workshop/content/108600"
    )

    managed_keys = tuple(
        key.strip()
        for key in required_env(env, "PZ_MANAGED_ENV_KEYS").split(",")
        if key.strip()
    )

    if not managed_keys:
        raise RuntimeError("PZ_MANAGED_ENV_KEYS contains no valid variables")

    MANAGED_ENV_KEYS = managed_keys

    try:
        overrides = json.loads(
            required_env(env, "PZ_MOD_ID_OVERRIDES")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "PZ_MOD_ID_OVERRIDES must contain a valid JSON object"
        ) from exc

    if not isinstance(overrides, dict):
        raise RuntimeError("PZ_MOD_ID_OVERRIDES must be a JSON object")

    normalized_overrides: dict[str, list[str]] = {}

    for workshop_id, mod_ids in overrides.items():
        if not isinstance(workshop_id, str) or not workshop_id.isdigit():
            raise RuntimeError(
                "PZ_MOD_ID_OVERRIDES contains an invalid Workshop ID: "
                f"{workshop_id!r}"
            )

        if (
            not isinstance(mod_ids, list)
            or not mod_ids
            or not all(isinstance(mod_id, str) and mod_id for mod_id in mod_ids)
        ):
            raise RuntimeError(
                "PZ_MOD_ID_OVERRIDES must map every Workshop ID "
                "to a non-empty Mod ID list"
            )

        normalized_overrides[workshop_id] = mod_ids

    MOD_ID_OVERRIDES = normalized_overrides
    MOD_BLACKLIST_MODS = {
        mod_id.strip()
        for mod_id in env.get("PZ_MOD_BLACKLIST_MODS", "").split(";")
        if mod_id.strip()
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate and update Project Zomboid mod configuration from one or more Steam collections."
    )
    p.add_argument(
        "collection_ids",
        nargs="*",
        metavar="collection_id",
        help="One or more collection IDs; each argument may contain comma-separated IDs.",
    )
    p.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    p.add_argument("--env-file", type=Path, default=CONFIG_ENV_FILE)
    p.add_argument("--strict", action="store_true", help="Exit 2 when serious issues are found")
    p.add_argument("--no-env-update", action="store_true", help="Do not modify .env")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument(
        "--workshop-root",
        type=Path,
        default=DEFAULT_WORKSHOP_ROOT,
        help=(
            "Local steamapps/workshop/content/108600 directory "
            "used as a fallback to read mod.info"
        ),
    )
    return p.parse_args()


def normalize_collection_ids(raw_values: list[str]) -> list[str]:
    """Validate, de-duplicate, and preserve the order of collection IDs."""
    collection_ids: list[str] = []

    for raw_value in raw_values:
        for collection_id in raw_value.split(","):
            collection_id = collection_id.strip()

            if not collection_id or not collection_id.isdigit():
                raise ValueError(
                    "collection ID must be numeric: "
                    f"{collection_id or raw_value!r}"
                )

            if collection_id not in collection_ids:
                collection_ids.append(collection_id)

    if not collection_ids:
        raise ValueError("specify at least one collection ID")

    return collection_ids


def append_collection_items(
    collection_ids: list[str],
    incoming_ids: list[str],
    move_to_end: bool = False,
) -> list[str]:
    """Append collection items, optionally moving existing IDs to the end."""
    duplicates: list[str] = []

    for workshop_id in incoming_ids:
        if workshop_id in collection_ids:
            duplicates.append(workshop_id)
            if not move_to_end:
                continue
            collection_ids.remove(workshop_id)

        collection_ids.append(workshop_id)

    return duplicates


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def prune_backups(path: Path, keep: int = BACKUPS_TO_KEEP) -> None:
    """Keep only the latest `keep` backups for the specified file."""
    backups = sorted(
        path.parent.glob(f"{path.name}.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError as exc:
            print(
                f"WARNING: unable to delete old backup {old}: {exc}",
                file=sys.stderr,
            )


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.{stamp}.bak")

    shutil.copy2(path, dest)
    prune_backups(path)

    return dest


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def post_json(
    session: requests.Session,
    url: str,
    data: dict[str, str],
    attempts: int = 7,
) -> dict[str, Any]:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            r = session.post(
                url,
                data=data,
                timeout=(15, 90),
            )

            if r.status_code == 429:
                delay = min(5 * attempt, 45)
                print(
                    f"Steam rate limit; retrying in {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue

            r.raise_for_status()

            obj = r.json()

            if not isinstance(obj, dict):
                raise SteamAPIError("Invalid JSON response")

            return obj

        except (requests.RequestException, ValueError, SteamAPIError) as exc:
            last = exc

            if attempt == attempts:
                break

            delay = min(3 * attempt, 30)

            print(
                f"Temporary error: {exc}; retrying in {delay}s...",
                file=sys.stderr,
            )

            time.sleep(delay)

    raise SteamAPIError(f"Steam request failed: {last}")


def get_collection(
    session: requests.Session,
    collection_id: str,
) -> tuple[list[str], list[str]]:
    data = {
        "collectioncount": "1",
        "publishedfileids[0]": collection_id,
    }

    obj = post_json(
        session,
        COLLECTION_API,
        data,
    )

    details = obj.get(
        "response",
        {},
    ).get(
        "collectiondetails",
        [],
    )

    if not details:
        raise SteamAPIError("Collection not returned by Steam")

    collection = details[0]

    if int(collection.get("result", 0)) != 1:
        raise SteamAPIError(
            f"Collection inaccessible, result={collection.get('result')}"
        )

    raw = [
        str(c.get("publishedfileid", "")).strip()
        for c in collection.get("children", [])
    ]

    raw = [
        x
        for x in raw
        if x
    ]

    counts = collections.Counter(raw)

    duplicates = [
        x
        for x, n in counts.items()
        if n > 1
    ]

    unique = list(dict.fromkeys(raw))

    return unique, duplicates


def get_details(
    session: requests.Session,
    ids: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]

        data = {
            "itemcount": str(len(batch))
        }

        for i, wid in enumerate(batch):
            data[f"publishedfileids[{i}]"] = wid

        obj = post_json(
            session,
            DETAILS_API,
            data,
        )

        rows = obj.get(
            "response",
            {},
        ).get(
            "publishedfiledetails",
            [],
        )

        if not isinstance(rows, list):
            raise SteamAPIError("Formato publishedfiledetails inatteso")

        out.extend(rows)

        print(
            f"Letti {min(start + len(batch), len(ids))}/{len(ids)} elementi"
        )

        time.sleep(1)

    return out


def clean_text(raw: str) -> str:
    text = html.unescape(raw or "")

    text = re.sub(
        r"\[/?[^\]]+\]",
        "\n",
        text,
    )

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def extract_values(
    labels: list[str],
    description: str,
) -> list[str]:
    label_re = "|".join(
        re.escape(x)
        for x in labels
    )

    pattern = re.compile(
        rf"^\s*(?:{label_re})\s*:\s*(.+?)\s*$",
        re.I | re.M,
    )

    out: list[str] = []

    for match in pattern.findall(description):
        for part in re.split(
            r"\s*[;|]\s*",
            match,
        ):
            value = html.unescape(part).strip(
                " \t,;|"
            )

            if value and value not in out:
                out.append(value)

    return out


def extract_map_names(
    title: str,
    description: str,
    is_map_collection_item: bool,
) -> list[str]:
    """Return map names only for items explicitly placed in a map collection."""
    if not is_map_collection_item:
        return []

    maps = extract_values(
        [
            "Map Folder",
            "Map Folder Name",
            "Map Name",
        ],
        description,
    )

    if not maps:
        maps = [title]

    return maps



def read_mod_id_from_info(path: Path) -> str | None:
    """Read the first valid id= from a mod.info file."""
    mod_ids = parse_mod_info(path)["id"]
    if not mod_ids:
        return None

    mod_id = mod_ids[0]

    if ";" in mod_id or "\n" in mod_id or len(mod_id) > 200:
        return None

    return mod_id


def active_mod_load_order_edges(
    mod_ids: list[str],
    load_before: list[tuple[str, str]] = MOD_LOAD_BEFORE,
    load_after: list[tuple[str, str]] = MOD_LOAD_AFTER,
    load_last: str = MOD_LOAD_LAST,
) -> list[tuple[str, str]]:
    """Return applicable directed Mod ID ordering edges without duplicates."""
    active = set(mod_ids)
    edges: list[tuple[str, str]] = []

    def add_edge(before: str, after: str) -> None:
        if before in active and after in active and (before, after) not in edges:
            edges.append((before, after))

    for before, after in load_before:
        add_edge(before, after)

    for after, before in load_after:
        add_edge(before, after)

    if load_last in active:
        for mod_id in mod_ids:
            if mod_id != load_last:
                add_edge(mod_id, load_last)

    return edges


def find_mod_load_order_cycle(
    successors: dict[str, list[str]],
    mod_ids: list[str],
) -> list[str]:
    """Return one directed cycle, including the repeated closing Mod ID."""
    state = {mod_id: 0 for mod_id in mod_ids}
    stack: list[str] = []

    def visit(mod_id: str) -> list[str] | None:
        state[mod_id] = 1
        stack.append(mod_id)

        for successor in successors[mod_id]:
            if state[successor] == 0:
                cycle = visit(successor)
                if cycle:
                    return cycle
            elif state[successor] == 1:
                start = stack.index(successor)
                return stack[start:] + [successor]

        stack.pop()
        state[mod_id] = 2
        return None

    for mod_id in mod_ids:
        if state[mod_id] == 0:
            cycle = visit(mod_id)
            if cycle:
                return cycle

    return []


def reorder_mod_ids(
    mod_ids: list[str],
    load_before: list[tuple[str, str]] = MOD_LOAD_BEFORE,
    load_after: list[tuple[str, str]] = MOD_LOAD_AFTER,
    load_last: str = MOD_LOAD_LAST,
) -> list[str]:
    """Apply hard rules with a stable topological sort of active Mod IDs.

    The collection-derived order is used whenever there is no dependency edge,
    so unrelated Mod IDs retain their relative order.  A cycle is an invalid
    administrator configuration rather than an order to guess at.
    """
    ordered_ids = list(dict.fromkeys(mod_ids))
    edges = active_mod_load_order_edges(
        ordered_ids,
        load_before,
        load_after,
        load_last,
    )
    original_index = {mod_id: index for index, mod_id in enumerate(ordered_ids)}
    successors = {mod_id: [] for mod_id in ordered_ids}
    indegree = {mod_id: 0 for mod_id in ordered_ids}

    for before, after in edges:
        successors[before].append(after)
        indegree[after] += 1

    available = [mod_id for mod_id in ordered_ids if indegree[mod_id] == 0]
    result: list[str] = []

    while available:
        available.sort(key=original_index.__getitem__)
        mod_id = available.pop(0)
        result.append(mod_id)

        for successor in successors[mod_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                available.append(successor)

    if len(result) != len(ordered_ids):
        cycle = find_mod_load_order_cycle(successors, ordered_ids)
        raise ModLoadOrderError(
            "Contradictory Mod ID load-order rules (cycle: "
            + " -> ".join(cycle)
            + "). Check MOD_LOAD_BEFORE and MOD_LOAD_AFTER."
        )

    return result


def mod_load_order_adjustments(
    original: list[str],
    load_before: list[tuple[str, str]] = MOD_LOAD_BEFORE,
    load_after: list[tuple[str, str]] = MOD_LOAD_AFTER,
) -> list[str]:
    """Describe only hard-rule changes, keeping normal output concise."""
    original_index = {mod_id: index for index, mod_id in enumerate(original)}
    active = set(original)
    adjustments: list[str] = []
    described_edges: set[tuple[str, str]] = set()

    for before, after in load_before:
        if (
            before in active
            and after in active
            and original_index[before] > original_index[after]
            and (before, after) not in described_edges
        ):
            adjustments.append(f"{before} moved before {after}")
            described_edges.add((before, after))

    for after, before in load_after:
        if (
            before in active
            and after in active
            and original_index[before] > original_index[after]
            and (before, after) not in described_edges
        ):
            adjustments.append(f"{after} moved after {before}")
            described_edges.add((before, after))

    return adjustments


def mod_info_rank(
    path: Path,
    mod_root: Path,
) -> tuple[int, str]:
    """
    B42.20 preference:
      0 -> .../42.20/mod.info
      1 -> .../42/mod.info
      2 -> .../mod.info without a version directory
      3 -> other 42.x directories
      4 -> everything else (for example 41)
    """
    try:
        rel = path.relative_to(mod_root)
    except ValueError:
        return (99, str(path))

    parts = rel.parts[:-1]

    if "42.20" in parts:
        rank = 0
    elif "42" in parts:
        rank = 1
    elif not parts:
        rank = 2
    elif any(
        re.fullmatch(r"42(?:\.\d+)+", part)
        for part in parts
    ):
        rank = 3
    else:
        rank = 4

    return (rank, str(rel))


def extract_local_mod_ids(
    workshop_root: Path,
    workshop_id: str,
) -> list[str]:
    """
    Extract Mod IDs from a Workshop item's local mod.info files.

    Each mods/<mod-name> directory is handled separately. The result is used
    to detect multi-mod Workshop items; it does not by itself activate every
    discovered Mod ID. One variant is selected for each mod, preferring 42.20,
    then 42, then the unversioned variant.
    """
    item_root = workshop_root / workshop_id
    mods_root = item_root / "mods"

    if not mods_root.is_dir():
        return []

    out: list[str] = []

    for mod_root in sorted(
        p
        for p in mods_root.iterdir()
        if p.is_dir()
    ):
        candidates = sorted(
            mod_root.rglob("mod.info"),
            key=lambda p: mod_info_rank(
                p,
                mod_root,
            ),
        )

        if not candidates:
            continue

        best_rank = mod_info_rank(
            candidates[0],
            mod_root,
        )[0]

        # If only incompatible or unrecognized variants exist (typically B41),
        # do not use them as an automatic fallback.
        if best_rank >= 4:
            continue

        mod_id = read_mod_id_from_info(
            candidates[0]
        )

        if mod_id and mod_id not in out:
            out.append(mod_id)

    return out


def select_workshop_mod_ids(
    description_mod_ids: list[str],
    local_mod_ids: list[str],
    override_mod_ids: list[str] | None,
    blacklisted_mod_ids: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Select automatic IDs, returning unresolved multi-mod IDs separately."""
    blacklisted_mod_ids = blacklisted_mod_ids or set()
    if override_mod_ids is not None:
        return [
            mod_id
            for mod_id in override_mod_ids
            if mod_id not in blacklisted_mod_ids
        ], []

    discovered = [
        mod_id
        for mod_id in dict.fromkeys(description_mod_ids + local_mod_ids)
        if mod_id not in blacklisted_mod_ids
    ]
    if len(discovered) > 1:
        return [], discovered

    return discovered, []


def suspicious_build(
    title: str,
    description: str,
) -> list[str]:
    text = f"{title}\n{description}".lower()

    warnings: list[str] = []

    b41 = any(
        x in text
        for x in (
            "build 41 only",
            "b41 only",
            "for build 41",
            "41 only",
        )
    )

    b42 = any(
        x in text
        for x in (
            "build 42",
            "b42",
            "42 stable",
        )
    )

    if b41 and not b42:
        warnings.append(
            "appears intended exclusively for Build 41"
        )

    if (
        "obsolete" in title.lower()
        or "deprecated" in title.lower()
    ):
        warnings.append(
            "title marked obsolete/deprecated"
        )

    return warnings


def read_previous_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        obj = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return obj if isinstance(obj, dict) else None

    except (OSError, ValueError):
        return None


def dotenv_quote(value: str) -> str:
    return '"' + value.replace(
        "\\",
        "\\\\",
    ).replace(
        '"',
        '\\"',
    ) + '"'


def update_env_file(
    path: Path,
    values: dict[str, str],
    make_backup: bool,
) -> Path | None:
    backup = (
        backup_file(path)
        if make_backup
        else None
    )

    existing = (
        path.read_text(
            encoding="utf-8"
        ).splitlines()
        if path.exists()
        else []
    )

    filtered = [
        line
        for line in existing
        if not any(
            line.startswith(k + "=")
            for k in MANAGED_ENV_KEYS
        )
    ]

    filtered_text = "\n".join(filtered).rstrip()

    managed = "\n".join(
        f"{k}={dotenv_quote(values[k])}"
        for k in MANAGED_ENV_KEYS
    )

    content = (
        (filtered_text + "\n\n")
        if filtered_text
        else ""
    ) + managed + "\n"

    atomic_write(
        path,
        content,
    )

    try:
        path.chmod(0o600)
    except OSError:
        pass

    return backup


def main() -> int:
    load_configuration()
    args = parse_args()

    try:
        mod_collection_ids = normalize_collection_ids(
            args.collection_ids or [DEFAULT_COLLECTION_ID]
        )
        map_collection_ids = (
            normalize_collection_ids([MAP_COLLECTION_IDS])
            if MAP_COLLECTION_IDS
            else []
        )
        last_to_load_collection_ids = (
            normalize_collection_ids([LAST_TO_LOAD_COLLECTION_IDS])
            if LAST_TO_LOAD_COLLECTION_IDS
            else []
        )
    except ValueError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    last_to_load_collection_id_set = set(last_to_load_collection_ids)
    selected_collection_ids = list(dict.fromkeys(
        [
            collection_id
            for collection_id in mod_collection_ids + map_collection_ids
            if collection_id not in last_to_load_collection_id_set
        ]
        + last_to_load_collection_ids
    ))
    collections_display = ", ".join(selected_collection_ids)
    map_collection_id_set = set(map_collection_ids)

    outdir = (
        args.output_dir
        .expanduser()
        .resolve()
    )

    env_path = args.env_file.expanduser()

    if not env_path.is_absolute():
        env_path = (
            Path.cwd()
            / env_path
        ).resolve()

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    workshop_root = (
        args.workshop_root
        .expanduser()
        .resolve()
    )

    if workshop_root.is_dir():
        print(
            f"Local Workshop fallback: {workshop_root}"
        )
    else:
        print(
            "WARNING: local Workshop fallback unavailable: "
            f"{workshop_root}",
            file=sys.stderr,
        )

    json_path = (
        outdir
        / "project-zomboid-mods.json"
    )

    env_generated_path = (
        outdir
        / "project-zomboid-mods.env"
    )

    report_path = (
        outdir
        / "project-zomboid-mods-report.txt"
    )

    compose_path = (
        outdir
        / "project-zomboid-mods-compose.yml"
    )

    previous = read_previous_json(
        json_path
    )

    session = requests.Session()

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html",
    })

    collection_ids: list[str] = []
    duplicate_workshop_ids: list[str] = []
    map_workshop_ids: set[str] = set()
    last_to_load_workshop_ids: set[str] = set()

    for collection_id in selected_collection_ids:
        print(
            f"Reading Steam collection {collection_id}..."
        )

        (
            current_collection_ids,
            current_duplicates,
        ) = get_collection(
            session,
            collection_id,
        )

        print(
            "Unique Workshop items in collection: "
            f"{len(current_collection_ids)}"
        )

        if collection_id in map_collection_id_set:
            map_workshop_ids.update(current_collection_ids)

        if collection_id in last_to_load_collection_id_set:
            last_to_load_workshop_ids.update(current_collection_ids)

        duplicate_ids = append_collection_items(
            collection_ids,
            current_duplicates + current_collection_ids,
            move_to_end=collection_id in last_to_load_collection_id_set,
        )

        for workshop_id in duplicate_ids:
            if workshop_id not in duplicate_workshop_ids:
                duplicate_workshop_ids.append(workshop_id)

    details = get_details(
        session,
        collection_ids,
    )

    by_id = {
        str(
            d.get(
                "publishedfileid",
                "",
            )
        ).strip(): d
        for d in details
    }

    workshop_ids: list[str] = []
    mod_ids: list[str] = []
    map_names: list[str] = []

    removed: list[str] = []
    missing_mod_id: list[dict[str, str]] = []
    multi_mod_selection_required: list[dict[str, Any]] = []
    wrong_app: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    malformed: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []

    mod_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    map_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    for wid in collection_ids:
        d = by_id.get(wid)

        if (
            not d
            or int(
                d.get(
                    "result",
                    0,
                )
                or 0
            ) != 1
            or not str(
                d.get(
                    "title",
                    "",
                )
            ).strip()
        ):
            removed.append(wid)
            continue

        title = str(
            d.get(
                "title",
                "",
            )
        ).strip()

        app_id = int(
            d.get(
                "consumer_app_id",
                0,
            )
            or 0
        )

        if app_id != APP_ID:
            wrong_app.append({
                "workshop_id": wid,
                "title": title,
                "consumer_app_id": app_id,
            })
            continue

        desc = clean_text(
            str(
                d.get(
                    "description",
                    "",
                )
                or ""
            )
        )

        description_mids = extract_values(
            [
                "Mod ID",
                "ModID",
            ],
            desc,
        )

        local_mids: list[str] = []
        if workshop_root.is_dir():
            local_mids = extract_local_mod_ids(
                workshop_root,
                wid,
            )

        mids, unresolved_mids = select_workshop_mod_ids(
            description_mids,
            local_mids,
            MOD_ID_OVERRIDES.get(wid),
            MOD_BLACKLIST_MODS,
        )

        if wid in MOD_ID_OVERRIDES:
            print(
                f"Applied authoritative Mod ID override: "
                f"{wid} ({title}) -> {', '.join(mids)}"
            )
        elif unresolved_mids:
            multi_mod_selection_required.append({
                "workshop_id": wid,
                "title": title,
                "mod_ids": unresolved_mids,
            })
            print(
                "WARNING: multi-mod Workshop item requires "
                f"PZ_MOD_ID_OVERRIDES selection: {wid} ({title}) -> "
                f"{', '.join(unresolved_mids)}",
                file=sys.stderr,
            )
        elif local_mids and not description_mids:
            print(
                f"Mod ID read from local mod.info: "
                f"{wid} ({title}) -> {', '.join(mids)}"
            )

        maps = extract_map_names(
            title,
            desc,
            wid in map_workshop_ids,
        )

        valid_mids: list[str] = []
        valid_maps: list[str] = []

        for mid in mids:
            if (
                ";" in mid
                or "\n" in mid
                or len(mid) > 200
                or mid.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ):
                malformed.append({
                    "workshop_id": wid,
                    "title": title,
                    "type": "Mod ID",
                    "value": mid,
                })
            else:
                valid_mids.append(mid)

                mod_owners[mid].append({
                    "workshop_id": wid,
                    "title": title,
                })

        for m in maps:
            if (
                ";" in m
                or "\n" in m
                or len(m) > 200
            ):
                malformed.append({
                    "workshop_id": wid,
                    "title": title,
                    "type": "Map",
                    "value": m,
                })
            else:
                valid_maps.append(m)

                map_owners[m].append({
                    "workshop_id": wid,
                    "title": title,
                })

        warnings = suspicious_build(
            title,
            desc,
        )

        if warnings:
            suspicious.append({
                "workshop_id": wid,
                "title": title,
                "warnings": warnings,
            })

        if not valid_mids:
            missing_mod_id.append({
                "workshop_id": wid,
                "title": title,
            })

        workshop_ids.append(wid)

        for x in valid_mids:
            if x in mod_ids:
                if wid not in last_to_load_workshop_ids:
                    continue
                mod_ids.remove(x)
            mod_ids.append(x)

        for x in valid_maps:
            if x not in map_names:
                map_names.append(x)

        records.append({
            "workshop_id": wid,
            "title": title,
            "mod_ids": valid_mids,
            "map_names": valid_maps,
            "is_map_mod": wid in map_workshop_ids,
            "time_created": d.get("time_created"),
            "time_updated": d.get("time_updated"),
        })

    duplicate_mod_ids = {
        k: v
        for k, v in mod_owners.items()
        if len(
            {
                x["workshop_id"]
                for x in v
            }
        ) > 1
    }

    duplicate_maps = {
        k: v
        for k, v in map_owners.items()
        if len(
            {
                x["workshop_id"]
                for x in v
            }
        ) > 1
    }

    final_maps = list(
        map_names
    )

    if "Muldraugh, KY" not in final_maps:
        final_maps.append(
            "Muldraugh, KY"
        )

    collection_mod_ids = list(mod_ids)
    try:
        mod_ids = reorder_mod_ids(mod_ids)
    except ModLoadOrderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    load_order_adjustments = mod_load_order_adjustments(
        collection_mod_ids,
    )

    if load_order_adjustments:
        print("Mod load-order adjustments:")
        for adjustment in load_order_adjustments:
            print(f"  {adjustment}")

    prev_workshop = (
        set(
            previous.get(
                "workshop_ids",
                [],
            )
        )
        if previous
        else set()
    )

    prev_mods = (
        set(
            previous.get(
                "mod_ids",
                [],
            )
        )
        if previous
        else set()
    )

    changes = {
        "added_workshop_ids": sorted(
            set(workshop_ids)
            - prev_workshop
        ),
        "removed_workshop_ids": sorted(
            prev_workshop
            - set(workshop_ids)
        ),
        "added_mod_ids": sorted(
            set(mod_ids)
            - prev_mods
        ),
        "removed_mod_ids": sorted(
            prev_mods
            - set(mod_ids)
        ),
    }

    generated = now_utc()

    result = {
        "generated_at_utc": generated,
        "collection_id": ",".join(selected_collection_ids),
        "collection_ids": selected_collection_ids,
        "mod_collection_ids": mod_collection_ids,
        "map_collection_ids": map_collection_ids,
        "last_to_load_collection_ids": last_to_load_collection_ids,
        "workshop_ids": workshop_ids,
        "mod_ids": mod_ids,
        "mod_load_order_adjustments": load_order_adjustments,
        "map_names": final_maps,
        "records": records,
        "duplicate_workshop_ids_in_collection": duplicate_workshop_ids,
        "duplicate_mod_ids": duplicate_mod_ids,
        "duplicate_map_names": duplicate_maps,
        "removed_or_inaccessible_items": removed,
        "missing_mod_id_items": missing_mod_id,
        "multi_mod_selection_required": multi_mod_selection_required,
        "wrong_app_items": wrong_app,
        "suspicious_build_items": suspicious,
        "malformed_values": malformed,
        "changes_since_previous_run": changes,
    }

    env_values = {
        "PZ_MOD_IDS": ";".join(
            workshop_ids
        ),
        "PZ_MOD_NAMES": ";".join(
            mod_ids
        ),
        "PZ_MAP_NAMES": ";".join(
            final_maps
        ),
    }

    generated_env = "\n".join([
        "# Automatically generated by generate-mod-list.py",
        f"# Collection Steam: {collections_display}",
        f"# Generated UTC: {generated}",
        *(
            f"{k}={dotenv_quote(v)}"
            for k, v in env_values.items()
        ),
        "",
    ])

    report: list[str] = [
        "PROJECT ZOMBOID MOD COLLECTION REPORT",
        "=" * 38,
        "",
        f"Generated UTC: {generated}",
        f"Collection: {collections_display}",
        (
            "Map collections: "
            + (", ".join(map_collection_ids) or "None")
        ),
        (
            "Collections loaded last: "
            + (", ".join(last_to_load_collection_ids) or "None")
        ),
        f"Valid Workshop items: {len(workshop_ids)}",
        f"Unique Mod IDs: {len(mod_ids)}",
        f"Modded maps: {len(map_names)}",
        f"Removed/inaccessible: {len(removed)}",
        f"Without Mod ID: {len(missing_mod_id)}",
        (
            "Multi-mod items requiring selection: "
            f"{len(multi_mod_selection_required)}"
        ),
        f"Duplicate Mod IDs: {len(duplicate_mod_ids)}",
        f"Duplicate maps: {len(duplicate_maps)}",
        "",
        "CHANGES SINCE PREVIOUS RUN",
        "-" * 39,
        (
            "Workshop items added: "
            + (
                ", ".join(
                    changes[
                        "added_workshop_ids"
                    ]
                )
                or "None"
            )
        ),
        (
            "Workshop items removed: "
            + (
                ", ".join(
                    changes[
                        "removed_workshop_ids"
                    ]
                )
                or "None"
            )
        ),
        (
            "Mod IDs added: "
            + (
                ", ".join(
                    changes[
                        "added_mod_ids"
                    ]
                )
                or "None"
            )
        ),
        (
            "Mod IDs removed: "
            + (
                ", ".join(
                    changes[
                        "removed_mod_ids"
                    ]
                )
                or "None"
            )
        ),
        "",
    ]

    def section(
        title: str,
        lines: list[str],
    ) -> None:
        report.extend([
            title,
            "-" * len(title),
        ])

        report.extend(
            lines or ["None"]
        )

        report.append("")

    section(
        "REMOVED OR INACCESSIBLE ITEMS",
        removed,
    )

    section(
        "ITEMS WITHOUT MOD ID",
        [
            f'{x["workshop_id"]}: {x["title"]}'
            for x in missing_mod_id
        ],
    )

    section(
        "MULTI-MOD WORKSHOP ITEMS REQUIRING SELECTION",
        [
            (
                f'{x["workshop_id"]}: {x["title"]} — '
                f'{", ".join(x["mod_ids"])}'
            )
            for x in multi_mod_selection_required
        ],
    )

    section(
        "DUPLICATE MOD IDS",
        [
            (
                f"{mid}: "
                + ", ".join(
                    f'{o["workshop_id"]} ({o["title"]})'
                    for o in owners
                )
            )
            for mid, owners
            in duplicate_mod_ids.items()
        ],
    )

    section(
        "MOD LOAD-ORDER ADJUSTMENTS",
        load_order_adjustments,
    )

    section(
        "DUPLICATE MAPS",
        [
            (
                f"{name}: "
                + ", ".join(
                    f'{o["workshop_id"]} ({o["title"]})'
                    for o in owners
                )
            )
            for name, owners
            in duplicate_maps.items()
        ],
    )

    section(
        "POSSIBLE B41/OBSOLETE MODS",
        [
            (
                f'{x["workshop_id"]}: '
                f'{x["title"]} — '
                f'{"; ".join(x["warnings"])}'
            )
            for x in suspicious
        ],
    )

    section(
        "MALFORMED VALUES",
        [
            (
                f'{x["workshop_id"]}: '
                f'{x["title"]} — '
                f'{x["type"]}={x["value"]}'
            )
            for x in malformed
        ],
    )

    for path in (
        json_path,
        env_generated_path,
        report_path,
        compose_path,
    ):
        if (
            path.exists()
            and not args.no_backup
        ):
            backup_file(path)

    atomic_write(
        json_path,
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )

    atomic_write(
        env_generated_path,
        generated_env,
    )

    atomic_write(
        report_path,
        "\n".join(report)
        + "\n",
    )

    atomic_write(
        compose_path,
        'MOD_IDS: "${PZ_MOD_IDS}"\n'
        'MOD_NAMES: "${PZ_MOD_NAMES}"\n'
        'MAP_NAMES: "${PZ_MAP_NAMES}"\n',
    )

    env_backup = None

    if not args.no_env_update:
        env_backup = update_env_file(
            env_path,
            env_values,
            not args.no_backup,
        )

    print(
        "\nGeneration complete:"
    )

    print(
        f"  JSON:    {json_path}"
    )

    print(
        f"  ENV:     {env_generated_path}"
    )

    print(
        f"  REPORT:  {report_path}"
    )

    print(
        f"  COMPOSE: {compose_path}"
    )

    if not args.no_env_update:
        print(
            f"  .env:    {env_path} updated"
        )

        if env_backup:
            print(
                f"  backup:  {env_backup}"
            )

    print(
        f"\nValid Workshop items: {len(workshop_ids)}"
    )

    print(
        f"Unique Mod IDs: {len(mod_ids)}"
    )

    print(
        f"Removed/inaccessible: {len(removed)}"
    )

    print(
        f"Without Mod ID: {len(missing_mod_id)}"
    )

    print(
        f"Duplicate Mod IDs: {len(duplicate_mod_ids)}"
    )

    serious = bool(
        removed
        or missing_mod_id
        or multi_mod_selection_required
        or duplicate_mod_ids
        or malformed
    )

    if (
        args.strict
        and serious
    ):
        print(
            "Strict mode: issues requiring correction detected.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:
        print(
            "\nInterrupted.",
            file=sys.stderr,
        )

        raise SystemExit(130)

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)
