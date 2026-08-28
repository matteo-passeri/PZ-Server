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
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from mod_active_state import read_last_active_mods, state_file

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_FILE = SCRIPT_DIR / ".env"
RULES_FILE = SCRIPT_DIR / "mod-rules.toml"

APP_ID = None
DEFAULT_COLLECTION_ID = None
MAP_COLLECTION_IDS = None
COLLECTION_API = None
DETAILS_API = None
USER_AGENT = None
MANAGED_ENV_KEYS = None
BACKUPS_TO_KEEP = None
DEFAULT_WORKSHOP_ROOT = None
MOD_ID_OVERRIDES = None
MOD_BLACKLIST_MODS = None
ADMIN_MOD_BLACKLIST: set[str] = set()
ADMIN_MOD_FORCED: list[str] = []
ADMIN_WORKSHOP_BLACKLIST: set[str] = set()
ADMIN_WORKSHOP_FORCED: list[str] = []


class ModRulesError(RuntimeError):
    """Raised when the version-controlled mod rules are invalid."""


@dataclass(frozen=True)
class PreferRule:
    winner: str
    losers: tuple[str, ...]
    reason: str | None = None
    enabled: bool = True
    removed_fallback: str | None = None


@dataclass(frozen=True)
class ConflictRule:
    mods: tuple[str, ...]
    reason: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ModRules:
    always_exclude: tuple[str, ...]
    prefer: tuple[PreferRule, ...]
    conflict: tuple[ConflictRule, ...]

# Hard Mod ID load-order rules.  These affect PZ_MOD_NAMES (the server Mods=
# value), never PZ_MOD_IDS (the WorkshopItems= value).
#
# Add a pair here when the first Mod ID must load before the second.  Add a
# pair to MOD_LOAD_AFTER when the first Mod ID must load after the second.
# MOD_LOAD_FIRST and MOD_LOAD_LAST place active IDs at the beginning and end,
# respectively, in their declared order.
MOD_LOAD_FIRST = (
    "damnlib",
    "tsarslib",
    "NeatUI_Framework",
)
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
    ("85chevyStepVan", "85chevyStepVanexpanded"),
    ("86fordE150", "86fordE150dnd"),
    ("86fordE150", "86fordE150mm"),
    ("86fordE150", "86fordE150pd"),
    ("86fordE150", "86fordE150expanded"),
    ("86fordE150dnd", "86fordE150mm"),
    ("86fordE150dnd", "86fordE150pd"),
    ("86fordE150dnd", "86fordE150expanded"),
    ("86fordE150mm", "86fordE150pd"),
    ("86fordE150mm", "86fordE150expanded"),
    ("86fordE150pd", "86fordE150expanded"),
    ("92amgeneralM998", "92amgeneralM998extra"),
    ("93chevySuburban", "93chevySuburbanExpanded"),
    ("69mini", "69mini_ItalianJob"),
    ("69mini", "69mini_MrBean"),
    ("69mini", "69mini_PitbullSpecial"),
    ("69mini_ItalianJob", "69mini_MrBean"),
    ("69mini_ItalianJob", "69mini_PitbullSpecial"),
    ("69mini_MrBean", "69mini_PitbullSpecial"),
    ("82firebird", "82firebirdKITT"),
    ("81deloreanDMC12", "81deloreanDMC12BTTF"),
    ("92jeepYJ", "92jeepYJJP18"),
    ("73fordFalcon", "73fordFalconPS"),
    ("59meteor", "ECTO1"),
    ("82jeepJ10", "82jeepJ10t"),
    ("78amgeneralM35A2", "78amgeneralM35A2extra"),
    ("78amgeneralM35A2", "78amgeneralM49A2C"),
    ("78amgeneralM35A2", "78amgeneralM50A3"),
    ("78amgeneralM35A2", "78amgeneralM62"),
    ("78amgeneralM35A2extra", "78amgeneralM49A2C"),
    ("78amgeneralM35A2extra", "78amgeneralM50A3"),
    ("78amgeneralM35A2extra", "78amgeneralM62"),
    ("78amgeneralM49A2C", "78amgeneralM50A3"),
    ("78amgeneralM49A2C", "78amgeneralM62"),
    ("78amgeneralM50A3", "78amgeneralM62"),
    ("69fordMustang", "69fordMustangExtra"),
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
MOD_LOAD_LAST = (
    "ChuckleberryFinnAlertSystem",
    "errorMagnifier",
    "Linux_Animsets_Marz_Mods",
)


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


def semicolon_values(env: dict[str, str], key: str) -> list[str]:
    """Return ordered, de-duplicated administrator values from .env."""
    return list(dict.fromkeys(
        value.strip()
        for value in env.get(key, "").split(";")
        if value.strip()
    ))


def _rule_mod_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModRulesError(f"{context}: Mod ID must be a non-empty string")
    return value.strip()


def _optional_rule_text(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModRulesError(f"{context}: reason must be a string")
    return value


def _rule_enabled(value: Any, context: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ModRulesError(f"{context}: enabled must be true or false")
    return value


def _find_prefer_cycle(rules: tuple[PreferRule, ...]) -> list[str]:
    graph: dict[str, list[str]] = collections.defaultdict(list)
    for rule in rules:
        if rule.enabled:
            graph[rule.winner].extend(rule.losers)

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(mod_id: str) -> list[str] | None:
        state[mod_id] = 1
        stack.append(mod_id)
        for next_id in graph[mod_id]:
            if state.get(next_id, 0) == 0:
                cycle = visit(next_id)
                if cycle:
                    return cycle
            elif state[next_id] == 1:
                return stack[stack.index(next_id):] + [next_id]
        stack.pop()
        state[mod_id] = 2
        return None

    for mod_id in list(graph):
        if state.get(mod_id, 0) == 0:
            cycle = visit(mod_id)
            if cycle:
                return cycle
    return []


def load_mod_rules(path: Path = RULES_FILE) -> ModRules:
    """Load and validate the small, declarative project compatibility layer."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ModRulesError(f"mod rules file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ModRulesError(f"{path}: invalid TOML: {exc}") from exc

    if not isinstance(raw, dict) or set(raw) - {"mods", "workshop"}:
        raise ModRulesError(f"{path}: only [mods] and [workshop] are allowed")
    mods = raw.get("mods", {})
    workshop = raw.get("workshop", {})
    if not isinstance(mods, dict) or not isinstance(workshop, dict):
        raise ModRulesError(f"{path}: [mods] and [workshop] must be tables")
    if set(mods) - {"always_exclude", "prefer", "conflict"}:
        raise ModRulesError(f"{path}: unknown [mods] key")
    if set(workshop) - {"always_exclude"}:
        raise ModRulesError(f"{path}: unknown [workshop] key")
    if workshop.get("always_exclude", []) not in ([], None):
        raise ModRulesError(f"{path}: workshop always_exclude is reserved for a future resolver")

    always_raw = mods.get("always_exclude", [])
    if not isinstance(always_raw, list):
        raise ModRulesError(f"{path}: mods.always_exclude must be a list")
    always = tuple(_rule_mod_id(value, f"{path}: always_exclude #{index}")
                   for index, value in enumerate(always_raw, 1))
    duplicates = sorted({value for value in always if always.count(value) > 1})
    if duplicates:
        raise ModRulesError(f"{path}: duplicate always_exclude Mod IDs: {', '.join(duplicates)}")

    def parse_prefer(index: int, value: Any) -> PreferRule:
        context = f"{path}: prefer rule #{index}"
        if not isinstance(value, dict) or set(value) - {"winner", "losers", "reason", "enabled", "removed_fallback"}:
            raise ModRulesError(f"{context}: expected winner, losers, optional reason/enabled/removed_fallback")
        winner = _rule_mod_id(value.get("winner"), context + " winner")
        losers_raw = value.get("losers")
        if not isinstance(losers_raw, list) or not losers_raw:
            raise ModRulesError(f"{context}: losers must be a non-empty list")
        losers = tuple(_rule_mod_id(item, context + " losers") for item in losers_raw)
        if winner in losers:
            raise ModRulesError(f'{context}: winner "{winner}" also appears in losers')
        duplicate_losers = sorted({item for item in losers if losers.count(item) > 1})
        if duplicate_losers:
            raise ModRulesError(f"{context}: duplicate losers: {', '.join(duplicate_losers)}")
        fallback = value.get("removed_fallback")
        if fallback is not None:
            fallback = _rule_mod_id(fallback, context + " removed_fallback")
            if fallback == winner:
                raise ModRulesError(f'{context}: removed_fallback "{fallback}" is the winner')
            if fallback not in losers:
                raise ModRulesError(f'{context}: removed_fallback "{fallback}" must appear in losers')
        return PreferRule(winner, losers, _optional_rule_text(value.get("reason"), context),
                          _rule_enabled(value.get("enabled"), context), fallback)

    prefer_raw = mods.get("prefer", [])
    if not isinstance(prefer_raw, list):
        raise ModRulesError(f"{path}: mods.prefer must be an array of tables")
    prefer = tuple(parse_prefer(index, value) for index, value in enumerate(prefer_raw, 1))
    prefer_keys = [(rule.winner, rule.losers) for rule in prefer]
    duplicate_prefer = [key for key in prefer_keys if prefer_keys.count(key) > 1]
    if duplicate_prefer:
        winner, losers = duplicate_prefer[0]
        raise ModRulesError(f"{path}: duplicate prefer rule: {winner} -> {', '.join(losers)}")
    fallback_winners = [rule.winner for rule in prefer if rule.removed_fallback]
    duplicate_fallback_winners = sorted({winner for winner in fallback_winners if fallback_winners.count(winner) > 1})
    if duplicate_fallback_winners:
        raise ModRulesError(f"{path}: multiple removed_fallback declarations for: {', '.join(duplicate_fallback_winners)}")
    cycle = _find_prefer_cycle(prefer)
    if cycle:
        raise ModRulesError(f"{path}: prefer cycle: {' -> '.join(cycle)}")

    def parse_conflict(index: int, value: Any) -> ConflictRule:
        context = f"{path}: conflict rule #{index}"
        if not isinstance(value, dict) or set(value) - {"mods", "reason", "enabled"}:
            raise ModRulesError(f"{context}: expected mods, optional reason/enabled")
        values = value.get("mods")
        if not isinstance(values, list):
            raise ModRulesError(f"{context}: mods must be a list")
        mod_ids = tuple(_rule_mod_id(item, context + " mods") for item in values)
        if len(mod_ids) < 2:
            raise ModRulesError(f"{context}: conflict requires at least two Mod IDs")
        duplicate_ids = sorted({item for item in mod_ids if mod_ids.count(item) > 1})
        if duplicate_ids:
            raise ModRulesError(f"{context}: duplicate Mod IDs: {', '.join(duplicate_ids)}")
        return ConflictRule(mod_ids, _optional_rule_text(value.get("reason"), context),
                            _rule_enabled(value.get("enabled"), context))

    conflict_raw = mods.get("conflict", [])
    if not isinstance(conflict_raw, list):
        raise ModRulesError(f"{path}: mods.conflict must be an array of tables")
    return ModRules(always, prefer, tuple(parse_conflict(i, value) for i, value in enumerate(conflict_raw, 1)))


def resolve_mod_rules(
    candidates: list[str], rules: ModRules, manual_blacklist: set[str] | None = None,
    forced: list[str] | None = None, previous_active: set[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve project rules in file order; forced IDs are appended afterward."""
    active = list(dict.fromkeys(candidates))
    available = set(active)
    decisions: list[dict[str, Any]] = []
    manual_blacklist = manual_blacklist or set()
    previous_active = previous_active or set()
    for mod_id in list(active):
        if mod_id in rules.always_exclude:
            active.remove(mod_id)
            decisions.append({"mod_id": mod_id, "status": "excluded", "reason": "project always_exclude"})
        elif mod_id in manual_blacklist:
            active.remove(mod_id)
            decisions.append({"mod_id": mod_id, "status": "excluded", "reason": "manual blacklist"})
    for rule in rules.prefer:
        if rule.enabled and rule.winner in active:
            for loser in rule.losers:
                if loser in active:
                    active.remove(loser)
                    decisions.append({"mod_id": loser, "status": "excluded", "reason": "superseded", "superseded_by": rule.winner, "rule_reason": rule.reason})
    # A Removed placeholder is only meaningful after a successfully-started
    # configuration used its winner. It is derived state, never an .env edit.
    excluded_by_reason = {item["mod_id"]: item["reason"] for item in decisions}
    for rule in rules.prefer:
        fallback = rule.removed_fallback
        if not rule.enabled or not fallback or rule.winner not in previous_active or rule.winner in active:
            continue
        details = {
            "mod_id": fallback,
            "original_mod": rule.winner,
            "rule_reason": rule.reason,
        }
        if fallback in manual_blacklist:
            decisions.append({**details, "status": "fallback_blocked_by_admin", "reason": "manual blacklist"})
        elif fallback not in available:
            decisions.append({**details, "status": "fallback_unavailable", "reason": "not available from resolved Workshop items"})
        elif fallback in active:
            decisions.append({**details, "status": "auto_removed_fallback", "reason": "previously active winner is now disabled"})
        elif fallback in excluded_by_reason:
            decisions.append({**details, "status": "fallback_unavailable", "reason": f"excluded by {excluded_by_reason[fallback]}"})
        else:
            active.append(fallback)
            decisions.append({**details, "status": "auto_removed_fallback", "reason": "previously active winner is now disabled"})
    for mod_id in forced or []:
        if mod_id not in active:
            active.append(mod_id)
            decisions.append({"mod_id": mod_id, "status": "included", "reason": "manual forced"})
    conflicts = [
        {"mods": list(rule.mods), "reason": rule.reason}
        for rule in rules.conflict
        if rule.enabled and all(mod_id in active for mod_id in rule.mods)
    ]
    return active, decisions, conflicts


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


def load_configuration(path: Path = CONFIG_ENV_FILE) -> None:
    global APP_ID
    global DEFAULT_COLLECTION_ID
    global MAP_COLLECTION_IDS
    global COLLECTION_API
    global DETAILS_API
    global USER_AGENT
    global MANAGED_ENV_KEYS
    global BACKUPS_TO_KEEP
    global DEFAULT_WORKSHOP_ROOT
    global MOD_ID_OVERRIDES
    global MOD_BLACKLIST_MODS
    global ADMIN_MOD_BLACKLIST
    global ADMIN_MOD_FORCED
    global ADMIN_WORKSHOP_BLACKLIST
    global ADMIN_WORKSHOP_FORCED

    env = read_env(path)

    APP_ID = positive_int_env(env, "PZ_APP_ID")
    DEFAULT_COLLECTION_ID = required_env(env, "PZ_DEFAULT_COLLECTION_ID")
    MAP_COLLECTION_IDS = env.get("PZ_MAP_COLLECTION_IDS", "").strip()
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
    ADMIN_MOD_BLACKLIST = set(semicolon_values(env, "PZ_MOD_BLACKLIST_MODS"))
    ADMIN_MOD_FORCED = semicolon_values(env, "PZ_MOD_FORCED_MODS")
    ADMIN_WORKSHOP_BLACKLIST = set(semicolon_values(env, "PZ_MOD_BLACKLIST_WORKSHOP"))
    ADMIN_WORKSHOP_FORCED = semicolon_values(env, "PZ_MOD_FORCED_WORKSHOP")
    MOD_BLACKLIST_MODS = ADMIN_MOD_BLACKLIST

    for label, blacklisted, forced in (
        ("Mod IDs", ADMIN_MOD_BLACKLIST, set(ADMIN_MOD_FORCED)),
        ("Workshop IDs", ADMIN_WORKSHOP_BLACKLIST, set(ADMIN_WORKSHOP_FORCED)),
    ):
        contradictory = sorted(blacklisted & forced)
        if contradictory:
            print(
                "WARNING: administrator configuration both blacklists and forces "
                f"{label}: {', '.join(contradictory)}. Forced inclusion wins.",
                file=sys.stderr,
            )


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
    p.add_argument("--rules-file", type=Path, default=RULES_FILE)
    p.add_argument("--validate-rules", action="store_true", help="Validate mod-rules.toml without Steam or .env")
    p.add_argument("--list-rules", action="store_true", help="Print validated project mod rules without Steam or .env")
    p.add_argument(
        "--workshop-root",
        type=Path,
        default=None,
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
) -> list[str]:
    """Append collection items while preserving the first collection position."""
    duplicates: list[str] = []

    for workshop_id in incoming_ids:
        if workshop_id in collection_ids:
            duplicates.append(workshop_id)
            continue

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


def normalize_mod_load_group(group: tuple[str, ...] | str) -> tuple[str, ...]:
    """Accept the former single-last-ID helper argument during the transition."""
    return (group,) if isinstance(group, str) else group


def active_mod_load_order_edges(
    mod_ids: list[str],
    load_before: list[tuple[str, str]] = MOD_LOAD_BEFORE,
    load_after: list[tuple[str, str]] = MOD_LOAD_AFTER,
    load_first: tuple[str, ...] = MOD_LOAD_FIRST,
    load_last: tuple[str, ...] | str = MOD_LOAD_LAST,
) -> list[tuple[str, str]]:
    """Return applicable directed Mod ID ordering edges without duplicates."""
    load_first = normalize_mod_load_group(load_first)
    load_last = normalize_mod_load_group(load_last)
    duplicate_first = sorted(
        {mod_id for mod_id in load_first if load_first.count(mod_id) > 1}
    )
    duplicate_last = sorted(
        {mod_id for mod_id in load_last if load_last.count(mod_id) > 1}
    )
    shared_group_ids = sorted(set(load_first) & set(load_last))
    if duplicate_first or duplicate_last or shared_group_ids:
        problems: list[str] = []
        if duplicate_first:
            problems.append(
                "duplicate MOD_LOAD_FIRST IDs: " + ", ".join(duplicate_first)
            )
        if duplicate_last:
            problems.append(
                "duplicate MOD_LOAD_LAST IDs: " + ", ".join(duplicate_last)
            )
        if shared_group_ids:
            problems.append(
                "IDs in both MOD_LOAD_FIRST and MOD_LOAD_LAST: "
                + ", ".join(shared_group_ids)
            )
        raise ModLoadOrderError(
            "Invalid Mod ID load-order group configuration: "
            + "; ".join(problems)
        )

    active = set(mod_ids)
    edges: list[tuple[str, str]] = []

    def add_edge(before: str, after: str) -> None:
        if before in active and after in active and (before, after) not in edges:
            edges.append((before, after))

    for before, after in load_before:
        add_edge(before, after)

    for after, before in load_after:
        add_edge(before, after)

    active_first = [mod_id for mod_id in load_first if mod_id in active]
    first_set = set(active_first)
    for before, after in zip(active_first, active_first[1:]):
        add_edge(before, after)
    for first_mod_id in active_first:
        for mod_id in mod_ids:
            if mod_id not in first_set:
                add_edge(first_mod_id, mod_id)

    active_last = [mod_id for mod_id in load_last if mod_id in active]
    if active_last:
        for mod_id in mod_ids:
            if mod_id not in active_last:
                add_edge(mod_id, active_last[0])
        for before, after in zip(active_last, active_last[1:]):
            add_edge(before, after)

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
    load_first: tuple[str, ...] = MOD_LOAD_FIRST,
    load_last: tuple[str, ...] | str = MOD_LOAD_LAST,
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
        load_first,
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
            + "). Check MOD_LOAD_FIRST, MOD_LOAD_BEFORE, MOD_LOAD_AFTER, "
            "and MOD_LOAD_LAST."
        )

    return result


def mod_load_order_adjustments(
    original: list[str],
    load_before: list[tuple[str, str]] = MOD_LOAD_BEFORE,
    load_after: list[tuple[str, str]] = MOD_LOAD_AFTER,
    load_first: tuple[str, ...] = MOD_LOAD_FIRST,
    load_last: tuple[str, ...] | str = MOD_LOAD_LAST,
) -> list[str]:
    """Describe only hard-rule changes, keeping normal output concise."""
    load_first = normalize_mod_load_group(load_first)
    load_last = normalize_mod_load_group(load_last)
    ordered_original = list(dict.fromkeys(original))
    reordered = reorder_mod_ids(
        ordered_original,
        load_before,
        load_after,
        load_first,
        load_last,
    )
    original_index = {
        mod_id: index for index, mod_id in enumerate(ordered_original)
    }
    reordered_index = {
        mod_id: index for index, mod_id in enumerate(reordered)
    }
    active = set(ordered_original)
    adjustments: list[str] = []
    described_edges: set[tuple[str, str]] = set()

    for mod_id in load_first:
        if mod_id in active and original_index[mod_id] != reordered_index[mod_id]:
            adjustments.append(f"{mod_id} moved to first-load group")

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

    for mod_id in load_last:
        if mod_id not in active or original_index[mod_id] == reordered_index[mod_id]:
            continue
        if mod_id == load_last[-1]:
            adjustments.append(f"{mod_id} moved to absolute last position")
        else:
            adjustments.append(f"{mod_id} moved to last-load group")

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


def print_rules(rules: ModRules) -> None:
    print("ALWAYS EXCLUDE")
    for mod_id in rules.always_exclude:
        print(mod_id)
    print("\nPREFER")
    for rule in rules.prefer:
        state = " (disabled)" if not rule.enabled else ""
        print(f"{rule.winner}{state}\n  -> suppresses {', '.join(rule.losers)}")
        if rule.removed_fallback:
            print(f"  -> removed fallback: {rule.removed_fallback}")
        if rule.reason:
            print(f"  reason: {rule.reason}")
    print("\nCONFLICT")
    for rule in rules.conflict:
        state = " (disabled)" if not rule.enabled else ""
        print(f"{' <-> '.join(rule.mods)}{state}")
        if rule.reason:
            print(f"  reason: {rule.reason}")


def main() -> int:
    args = parse_args()
    rules_path = args.rules_file.expanduser()
    if not rules_path.is_absolute():
        rules_path = (Path.cwd() / rules_path).resolve()
    rules = load_mod_rules(rules_path)
    if args.validate_rules:
        print(f"Rules OK\nalways_exclude: {len(rules.always_exclude)}\nprefer: {len(rules.prefer)}\nconflict: {len(rules.conflict)}")
        return 0
    if args.list_rules:
        print_rules(rules)
        return 0

    env_path = args.env_file.expanduser()
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()
    load_configuration(env_path)

    try:
        mod_collection_ids = normalize_collection_ids(
            args.collection_ids or [DEFAULT_COLLECTION_ID]
        )
        map_collection_ids = (
            normalize_collection_ids([MAP_COLLECTION_IDS])
            if MAP_COLLECTION_IDS
            else []
        )
    except ValueError as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    selected_collection_ids = list(dict.fromkeys(
        mod_collection_ids + map_collection_ids
    ))
    collections_display = ", ".join(selected_collection_ids)
    map_collection_id_set = set(map_collection_ids)

    outdir = (
        args.output_dir
        .expanduser()
        .resolve()
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    workshop_root = (
        (args.workshop_root or DEFAULT_WORKSHOP_ROOT)
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

        duplicate_ids = append_collection_items(
            collection_ids,
            current_duplicates + current_collection_ids,
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
    workshop_decisions: list[dict[str, str]] = []

    mod_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    map_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    for wid in collection_ids:
        if wid in ADMIN_WORKSHOP_BLACKLIST and wid not in ADMIN_WORKSHOP_FORCED:
            workshop_decisions.append({
                "workshop_id": wid,
                "status": "excluded",
                "reason": "manual blacklist",
            })
            print(f"[PZ-MODS] Manual Workshop blacklist removed {wid}")
            continue
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
                continue
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

    # Preserve existing forced Workshop semantics.  A forced item may not have
    # been part of a fetched collection, so its Mod IDs cannot be inferred here.
    for wid in ADMIN_WORKSHOP_FORCED:
        if wid not in workshop_ids:
            workshop_ids.append(wid)
            workshop_decisions.append({
                "workshop_id": wid,
                "status": "included",
                "reason": "manual forced",
            })
            print(f"[PZ-MODS] Manual forced Workshop inclusion added {wid}")

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

    previous_active_mods = read_last_active_mods(
        state_file(SCRIPT_DIR),
        lambda message: print(f"WARNING: [PZ-MODS] {message}", file=sys.stderr),
    )
    collection_mod_ids = list(mod_ids)
    mod_ids, mod_rule_decisions, conflicts = resolve_mod_rules(
        mod_ids,
        rules,
        ADMIN_MOD_BLACKLIST,
        ADMIN_MOD_FORCED,
        set(previous_active_mods),
    )
    for decision in mod_rule_decisions:
        if decision["status"] == "auto_removed_fallback":
            print(f"[PZ-MODS] Activating {decision['mod_id']}: {decision['original_mod']} was active previously and is now disabled")
        elif decision["status"] == "fallback_blocked_by_admin":
            print(f"[PZ-MODS] Removed fallback {decision['mod_id']} blocked by administrator blacklist", file=sys.stderr)
        elif decision["status"] == "fallback_unavailable":
            print(f"[PZ-MODS] Removed fallback required but unavailable: {decision['mod_id']}", file=sys.stderr)
        elif decision["reason"] == "superseded":
            print(f"[PZ-MODS] Excluding {decision['mod_id']}: superseded by {decision['superseded_by']}")
        elif decision["reason"] == "manual blacklist":
            print(f"[PZ-MODS] Manual blacklist removed {decision['mod_id']}")
        elif decision["reason"] == "project always_exclude":
            print(f"[PZ-MODS] Excluding {decision['mod_id']}: project always_exclude")
    for conflict in conflicts:
        print(f"[PZ-MODS] Conflict: {' and '.join(conflict['mods'])} are both active", file=sys.stderr)
    resolved_mod_ids = list(mod_ids)
    try:
        mod_ids = reorder_mod_ids(mod_ids)
    except ModLoadOrderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    load_order_adjustments = mod_load_order_adjustments(resolved_mod_ids)

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
        "workshop_ids": workshop_ids,
        "mod_ids": mod_ids,
        "mod_load_order_adjustments": load_order_adjustments,
        "previous_successful_active_mods": previous_active_mods,
        "mod_rule_decisions": mod_rule_decisions,
        "workshop_decisions": workshop_decisions,
        "conflicts": conflicts,
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
        "AUTOMATIC MOD RULES",
        [
            (
                f"{decision['mod_id']}\n"
                f"  excluded: {decision['reason']}"
                + (f" by {decision['superseded_by']}" if decision.get("superseded_by") else "")
                + (f"\n  rule: {decision['rule_reason']}" if decision.get("rule_reason") else "")
            )
            for decision in mod_rule_decisions
            if decision["status"] == "excluded" and decision["reason"] != "manual blacklist"
        ],
    )

    section(
        "REMOVED FALLBACKS",
        [
            f"{decision['mod_id']}\n  automatically activated\n  original mod: {decision['original_mod']}\n"
            f"  reason: {decision['reason']}"
            + (f"\n  rule: {decision['rule_reason']}" if decision.get("rule_reason") else "")
            for decision in mod_rule_decisions
            if decision["status"] == "auto_removed_fallback"
        ],
    )

    section(
        "REMOVED FALLBACK WARNINGS",
        [
            f"{decision['original_mod']}\n  previously active; now disabled\n  known fallback: {decision['mod_id']}\n"
            "  fallback not activated because it is explicitly blacklisted"
            for decision in mod_rule_decisions
            if decision["status"] == "fallback_blocked_by_admin"
        ],
    )

    section(
        "REMOVED FALLBACK ERRORS",
        [
            f"{decision['original_mod']}\n  previously active; now disabled\n  required fallback: {decision['mod_id']}\n"
            f"  fallback {decision['reason']}"
            for decision in mod_rule_decisions
            if decision["status"] == "fallback_unavailable"
        ],
    )

    section(
        "MANUAL EXCLUSIONS",
        [
            f"{decision['mod_id']}\n  excluded by PZ_MOD_BLACKLIST_MODS"
            for decision in mod_rule_decisions
            if decision["reason"] == "manual blacklist"
        ] + [
            f"{decision['workshop_id']}\n  excluded by PZ_MOD_BLACKLIST_WORKSHOP"
            for decision in workshop_decisions
            if decision["status"] == "excluded"
        ],
    )

    section(
        "CONFLICTS",
        [
            " <-> ".join(conflict["mods"])
            + "\n  both remain active"
            + (f"\n  reason: {conflict['reason']}" if conflict.get("reason") else "")
            for conflict in conflicts
        ],
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
