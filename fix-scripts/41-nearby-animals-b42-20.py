#!/usr/bin/env python3
"""Apply the NearbyAnimals B42.20 fix directly to installed Workshop content."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


MOD_ID = "DBD_NearbyAnimals"
TARGET_VERSION = (42, 20)
TARGET_VERSION_NAME = "42.20"
LUA_RELATIVE = Path("common/media/lua/client/DBD_NearbyAnimals.lua")
PATCH_PATH = Path(__file__).with_name("data") / "nearby-animals-b42-20.patch"
TRANSLATION_GLOB = "media/lua/shared/Translate/*/IG_UI.json"
REQUIRED_TRANSLATION_KEYS = {
    "IGUI_DBD_NearbyAnimals_Title",
    "IGUI_DBD_NearbyAnimals_NoAnimals",
    "IGUI_DBD_NearbyAnimals_Toggle",
}


class CompatibilityMismatch(Exception):
    """Installed content does not match a narrowly guarded compatibility state."""


def rewrite_atomically(path, text):
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        if path.exists():
            os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary:
            descriptor = None
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def mod_info_id(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"(?m)^\s*id\s*=\s*([^\r\n]+?)\s*$", text)
    return matches[0] if len(matches) == 1 else None


def matching_mod_roots(ctx):
    """Find active Workshop mod roots by authoritative mod.info ID."""
    workshop = ctx["WORKSHOP"]
    active_ids = set(ctx.get("active_workshop_ids", ()))
    if not workshop.is_dir():
        return []

    roots = set()
    for item in sorted(path for path in workshop.iterdir() if path.is_dir()):
        if active_ids and item.name not in active_ids:
            continue
        mods = item / "mods"
        if not mods.is_dir():
            continue
        for info in sorted(mods.glob("*/mod.info")):
            if mod_info_id(info) == MOD_ID:
                roots.add(info.parent)
        for info in sorted(mods.glob("*/*/mod.info")):
            if mod_info_id(info) == MOD_ID:
                roots.add(info.parent.parent)
    return sorted(roots)


def version_tuple(name):
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?", name)
    if not match or int(match.group(1)) != TARGET_VERSION[0]:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def select_active_source_tree(mod_root):
    """Select one B42 tree, preferring exact 42.20 and then generic 42."""
    candidates = []
    for info in sorted(mod_root.glob("*/mod.info")):
        if mod_info_id(info) != MOD_ID:
            continue
        version = version_tuple(info.parent.name)
        if version is None or version > TARGET_VERSION:
            continue
        if version == TARGET_VERSION:
            rank = (0, 0)
        elif info.parent.name == "42":
            rank = (1, 0)
        else:
            rank = (2, -version[1])
        candidates.append((rank, info.parent))
    return min(candidates)[1] if candidates else None


def parse_patch_hunks(patch_text):
    """Return exact old/new text pairs from the repository-owned unified patch."""
    hunks = []
    old_lines = None
    new_lines = None
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("@@ "):
            if old_lines is not None:
                hunks.append(("".join(old_lines), "".join(new_lines)))
            old_lines, new_lines = [], []
            continue
        if old_lines is None or line.startswith("\\ No newline"):
            continue
        prefix, content = line[:1], line[1:]
        if prefix in (" ", "-"):
            old_lines.append(content)
        if prefix in (" ", "+"):
            new_lines.append(content)
    if old_lines is not None:
        hunks.append(("".join(old_lines), "".join(new_lines)))
    if not hunks or any(old == new for old, new in hunks):
        raise RuntimeError(f"invalid NearbyAnimals compatibility patch: {PATCH_PATH}")
    return hunks


def plan_lua_patch(text, patch_text):
    """Apply only exact known hunks; reject ambiguous or unknown Lua content."""
    updated = text
    cursor = 0
    applied = 0
    for index, (old, new) in enumerate(parse_patch_hunks(patch_text), 1):
        old_at = updated.find(old, cursor)
        new_at = updated.find(new, cursor)
        if old_at >= 0 and (new_at < 0 or old_at < new_at):
            updated = updated[:old_at] + new + updated[old_at + len(old):]
            cursor = old_at + len(new)
            applied += 1
        elif new_at >= 0:
            cursor = new_at + len(new)
        else:
            raise CompatibilityMismatch(
                f"DBD_NearbyAnimals.lua hunk {index} does not match known safe structure"
            )

    if not applied:
        return text, "FIXED"
    return updated, "APPLIED"


def transformed_mod_info(source):
    text = source.read_text(encoding="utf-8", errors="strict")
    if mod_info_id(source) != MOD_ID:
        raise CompatibilityMismatch("active source mod.info has an unexpected mod ID")
    for key in ("versionMin", "versionMax"):
        pattern = re.compile(rf"(?m)^(?P<prefix>{key}\s*=)[^\r\n]*$")
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise CompatibilityMismatch(f"active source mod.info has {len(matches)} {key} fields")
        text = pattern.sub(rf"\g<prefix>{TARGET_VERSION_NAME}", text, count=1)
    return text


def validate_translation(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CompatibilityMismatch(f"invalid translation {path.name}: {exc}") from exc
    if not isinstance(data, dict) or not REQUIRED_TRANSLATION_KEYS.issubset(data):
        raise CompatibilityMismatch(
            f"translation {path.name} is missing required NearbyAnimals keys"
        )


def plan_active_tree(mod_root, source_tree):
    """Plan only the B42.20 metadata files, sourced from the installed mod."""
    target_tree = mod_root / TARGET_VERSION_NAME
    if source_tree == target_tree:
        return target_tree, None, []
    if target_tree.exists():
        raise CompatibilityMismatch(
            "42.20 target exists but is not a recognized NearbyAnimals tree"
        )

    translations = sorted(source_tree.glob(TRANSLATION_GLOB))
    if not translations:
        raise CompatibilityMismatch("active source tree has no translation files")
    for translation in translations:
        validate_translation(translation)
    return target_tree, transformed_mod_info(source_tree / "mod.info"), translations


def install_active_tree(target_tree, mod_info_text, translations, source_tree):
    target_tree.mkdir(parents=True, exist_ok=False)
    rewrite_atomically(target_tree / "mod.info", mod_info_text)
    for source in translations:
        relative = source.relative_to(source_tree)
        destination = target_tree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def patch_mod(mod_root, log):
    lua_path = mod_root / LUA_RELATIVE
    if not lua_path.is_file():
        log(f"NearbyAnimals: SKIPPED / TARGET MISSING ({LUA_RELATIVE}).")
        return False

    source_tree = select_active_source_tree(mod_root)
    if source_tree is None:
        log("NearbyAnimals: SKIPPED / UNKNOWN REVISION (no compatible B42 mod.info tree).")
        return False

    try:
        lua_text = lua_path.read_text(encoding="utf-8", errors="strict")
        patch_text = PATCH_PATH.read_text(encoding="utf-8", errors="strict")
        updated_lua, _lua_status = plan_lua_patch(lua_text, patch_text)
        target_tree, mod_info_text, translations = plan_active_tree(mod_root, source_tree)
    except (UnicodeError, CompatibilityMismatch) as exc:
        log(f"NearbyAnimals: SKIPPED / UPSTREAM CHANGED ({exc}).")
        return False

    lua_changed = updated_lua != lua_text
    tree_changed = mod_info_text is not None
    if not lua_changed and not tree_changed:
        backup = lua_path.with_suffix(lua_path.suffix + ".pz-local-fix.bak")
        status = "ALREADY PATCHED" if backup.is_file() else "UPSTREAM FIXED / SKIP"
        log(f"NearbyAnimals: {status}.")
        return False

    log("NearbyAnimals: applying B42.20 compatibility patch.")
    if lua_changed:
        backup = lua_path.with_suffix(lua_path.suffix + ".pz-local-fix.bak")
        if not backup.exists():
            shutil.copy2(lua_path, backup)
        rewrite_atomically(lua_path, updated_lua)
        log(f"NearbyAnimals: patched {lua_path.name}.")
    if tree_changed:
        install_active_tree(target_tree, mod_info_text, translations, source_tree)
        log("NearbyAnimals: created active 42.20 metadata tree from installed Workshop content.")
    return True


def run(ctx):
    log = ctx["log"]
    roots = matching_mod_roots(ctx)
    if not roots:
        log("NearbyAnimals: SKIPPED / TARGET NOT INSTALLED.")
        return False
    if len(roots) != 1:
        log(f"NearbyAnimals: SKIPPED / UPSTREAM CHANGED (found {len(roots)} installed mod roots).")
        return False

    root = roots[0]
    relative = root.relative_to(ctx["WORKSHOP"])
    log(f"NearbyAnimals: found installed mod at {relative}.")
    return patch_mod(root, log)


FIX = {
    "name": "Nearby Animals B42.20 compatibility update",
    "run": run,
}
