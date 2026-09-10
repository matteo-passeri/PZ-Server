#!/usr/bin/env python3
"""Repair Lugli - Achievements weapon-category tracking for Build 42.20."""
import os
from pathlib import Path
import tempfile


WORKSHOP_ID = "3793988085"
MOD_ID = "Lugli_Achievements"
MOD_ROOT = Path("mods") / MOD_ID
LUA_RELATIVE = Path("42.20/media/lua/client/LugliAchievements/Track/Combat.lua")

KNOWN_BAD = '''local function creditCategories(player, weapon)
    if weapon == nil then
        -- Empty hands still count: unarmed is a real weapon category with exactly one entry.
        M.incStat(player, "kills_unarmed", 1)
        M.addUnique(player, "weapon_classes_used", "base:unarmed")
        return
    end
    if weapon.isRanged ~= nil and weapon:isRanged() then
        M.incStat(player, "kills_firearm", 1)
        return
    end
    local script = weapon:getScriptItem()
    if script == nil or script.containsWeaponCategory == nil then return end
    for cat, stat in pairs(CATEGORY_STAT) do
        -- pcall with arguments, not a closure: a closure here is eight allocations per kill.
        local ok, has = pcall(script.containsWeaponCategory, script, cat)
        if ok and has then
            M.incStat(player, stat, 1)
            M.addUnique(player, "weapon_classes_used", cat)
        end
    end
end'''

KNOWN_GOOD = '''local function creditCategories(player, weapon)
    if weapon == nil then
        -- Empty hands still count: unarmed is a real weapon category with exactly one entry.
        M.incStat(player, "kills_unarmed", 1)
        M.addUnique(player, "weapon_classes_used", "base:unarmed")
        return
    end

    if weapon.isRanged ~= nil and weapon:isRanged() then
        M.incStat(player, "kills_firearm", 1)
        return
    end

    local script = weapon:getScriptItem()
    if script == nil or script.getWeaponCategories == nil then return end

    local categories = script:getWeaponCategories()
    if categories == nil then return end

    local iter = categories:iterator()
    while iter:hasNext() do
        local category = iter:next()
        local id = tostring(category)
        local stat = CATEGORY_STAT[id]

        if stat ~= nil then
            M.incStat(player, stat, 1)
            M.addUnique(player, "weapon_classes_used", id)
        end
    end
end'''


class UpstreamChangedError(RuntimeError):
    """The exact supported Combat.lua implementation is no longer present."""


def rewrite_atomically(path, data):
    """Replace a validated file without creating a Workshop backup file."""
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = None
            temporary.write(data)
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


def plan_lua_fix(data):
    """Return an exact replacement plan, rejecting unrecognized upstream code."""
    text = data.decode("utf-8", errors="strict")
    newline = "\r\n" if "\r\n" in text else "\n"
    known_bad = KNOWN_BAD.replace("\n", newline)
    known_good = KNOWN_GOOD.replace("\n", newline)
    bad_count = text.count(known_bad)
    good_count = text.count(known_good)

    if bad_count == 1 and good_count == 0:
        return text.replace(known_bad, known_good, 1).encode("utf-8"), "APPLIED"
    if bad_count == 0 and good_count == 1:
        return data, "ALREADY PATCHED"

    raise UpstreamChangedError(
        "creditCategories: expected one exact known-bad or known-good implementation; "
        f"found bad={bad_count}, good={good_count}"
    )


def run(ctx):
    log = ctx["log"]
    active_workshop_ids = ctx.get("active_workshop_ids", ())
    active_mod_ids = ctx.get("active_mod_ids", ())
    if active_workshop_ids and WORKSHOP_ID not in active_workshop_ids:
        log("Lugli - Achievements: Workshop 3793988085 is not active; skip.")
        return False
    if active_mod_ids and MOD_ID not in active_mod_ids:
        log("Lugli - Achievements: Mod Lugli_Achievements is not active; skip.")
        return False

    lua_path = ctx["WORKSHOP"] / WORKSHOP_ID / MOD_ROOT / LUA_RELATIVE
    if not lua_path.is_file():
        log("Lugli - Achievements: SKIPPED / TARGET NOT INSTALLED.")
        return False

    try:
        data = lua_path.read_bytes()
        updated, status = plan_lua_fix(data)
    except (UnicodeError, UpstreamChangedError) as exc:
        log(f"Lugli - Achievements: SKIPPED / UPSTREAM CHANGED ({exc}).")
        return False

    if updated == data:
        log(f"Lugli - Achievements: {status}.")
        return False

    rewrite_atomically(lua_path, updated)
    log("Lugli - Achievements: patched Combat.lua.")
    return True


FIX = {
    "name": "Lugli - Achievements B42.20 weapon categories",
    "run": run,
}
