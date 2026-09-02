#!/usr/bin/env python3
"""Install the committed NearbyAnimals B42.20 compatibility update safely."""
import hashlib
from pathlib import Path
import shutil


MOD_ID = "DBD_NearbyAnimals"
UPSTREAM_LUA_SHA256 = "2559abc1f669a33918b43ecf2ecdc7fe83e50f65990cd133df252cf9d98727f6"
FIXED_LUA_SHA256 = "0e816406200c1c3b6aa4f3f0e62926c2e3b4fd97e6d33f6a6a6c7121ac6c09b1"
SOURCE_TREE_SHA256 = {
    Path("mod.info"): "670f3a70c3c71be5939678f6a9080a41b91cf152031e2a62c6fd248ce9166e66",
    Path("media/lua/shared/Translate/DE/IG_UI.json"): "6812282a875ce44faed6e0f1e76e3e049b8703938663177021a41e7ab71a8e39",
    Path("media/lua/shared/Translate/EN/IG_UI.json"): "2b4b0e60cb1493ba97dd2c103bf7dca2164be177c10a1d6d0c95527d22cd3aad",
    Path("media/lua/shared/Translate/ES/IG_UI.json"): "b4f21c0e17b083f3fa25ffd7af160d3dc92075b1b5843a9fc740d6fb0bf98fdf",
    Path("media/lua/shared/Translate/FR/IG_UI.json"): "89117a3c9d21a364d9e8199ed57c9209b5ac871571d807163cf83f33452250ab",
    Path("media/lua/shared/Translate/IT/IG_UI.json"): "1cd2f02b1992c7bc2358c7ef42129b7c5cca05a25b909aa3e6e4d0f0af4ab64f",
}
LUA_RELATIVE = Path("common/media/lua/client/DBD_NearbyAnimals.lua")
TREE_RELATIVE = Path("42.20")
DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "NearbyAnimals"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_mod_id(mod_root):
    for info in mod_root.glob("*/mod.info"):
        try:
            lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if any(line.strip() == f"id={MOD_ID}" for line in lines):
            return True
    return False


def matching_mod_roots(ctx):
    active = set(ctx.get("active_workshop_ids", ()))
    workshop = ctx["WORKSHOP"]
    if not workshop.is_dir():
        return []
    roots = []
    for item in sorted(workshop.iterdir()):
        if not item.is_dir() or (active and item.name not in active):
            continue
        mods = item / "mods"
        if not mods.is_dir():
            continue
        for mod_root in sorted(path for path in mods.iterdir() if path.is_dir()):
            if has_mod_id(mod_root) and (mod_root / LUA_RELATIVE).is_file():
                roots.append(mod_root)
    return roots


def source_is_valid(source):
    lua = source / LUA_RELATIVE
    if not lua.is_file() or digest(lua) != FIXED_LUA_SHA256:
        return False
    tree = source / TREE_RELATIVE
    return all((tree / relative).is_file() and digest(tree / relative) == expected
               for relative, expected in SOURCE_TREE_SHA256.items())


def target_tree_is_safe(target, source):
    if not target.exists():
        return True
    if not target.is_dir():
        return False
    for relative, expected in SOURCE_TREE_SHA256.items():
        destination = target / relative
        if not destination.is_file() or digest(destination) != expected:
            return False
    return True


def copy_tree(source, target):
    for relative in SOURCE_TREE_SHA256:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)


def patch_mod(mod_root, source, log):
    lua = mod_root / LUA_RELATIVE
    target_tree = mod_root / TREE_RELATIVE
    lua_digest = digest(lua)
    if lua_digest not in (UPSTREAM_LUA_SHA256, FIXED_LUA_SHA256):
        log(f"NearbyAnimals: blocked; unknown client Lua revision at {lua}.")
        return False
    if not target_tree_is_safe(target_tree, source):
        log(f"NearbyAnimals: blocked; existing 42.20 tree differs at {target_tree}.")
        return False

    changed = False
    if lua_digest == UPSTREAM_LUA_SHA256:
        backup = lua.with_suffix(lua.suffix + ".pz-local-fix.bak")
        if not backup.exists():
            shutil.copy2(lua, backup)
        shutil.copy2(source / LUA_RELATIVE, lua)
        changed = True

    if not target_tree.exists():
        copy_tree(source / TREE_RELATIVE, target_tree)
        changed = True

    log("NearbyAnimals: B42.20 compatibility update " + ("applied." if changed else "already present."))
    return changed


def run(ctx):
    log = ctx["log"]
    source = Path(ctx.get("nearby_animals_source", DEFAULT_SOURCE))
    if not source_is_valid(source):
        log(f"NearbyAnimals: committed patch source is missing or unexpected: {source}; skip.")
        return False
    roots = matching_mod_roots(ctx)
    if not roots:
        log("NearbyAnimals: active Workshop mod not present; skip.")
        return False
    changed = False
    for root in roots:
        changed = patch_mod(root, source, log) or changed
    return changed


FIX = {
    "name": "Nearby Animals B42.20 compatibility update",
    "run": run,
}
