#!/usr/bin/env python3
"""Move Braven's Achievements B42 state from global to player ModData.

This intentionally has no legacy Global ModData migration.  In multiplayer a
global legacy table cannot be attributed safely to one player, so copying it
would risk awarding one player's progress to every player who joins.
"""
import os
from pathlib import Path
import re
import shutil
import tempfile


WORKSHOP_ID = "3051277957"
MOD_ID = "BB_Achievements"
MOD_VERSION = "1.3.0"
B42_TREE = Path("42.0")
LUA_RELATIVES = (
    Path("media/lua/client/BB_Achievements_Main.lua"),
    Path("media/lua/client/BB_Achievements_Tracker.lua"),
    Path("media/lua/client/BB_Achievements_Client.lua"),
)
MARKER = "-- PZ-LOCAL-FIX: Braven achievements player ModData persistence"
GLOBAL_INIT_EVENT = "Events.OnInitGlobalModData.Add(onInitGlobalModData)"


class CompatibilityMismatch(RuntimeError):
    """Installed Lua does not have the supported 1.3.0 structure."""


def rewrite_atomically(path, text):
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
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


def mod_info_value(path, key):
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^\r\n]+?)\s*$", text)
    return matches[0] if len(matches) == 1 else None


def matching_mod_roots(ctx):
    """Discover the installed target by mod ID, constrained to active items."""
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


def replace_once(text, old, new, description):
    if text.count(old) != 1:
        raise CompatibilityMismatch(
            f"{description}: expected one exact supported upstream anchor; found {text.count(old)}"
        )
    return text.replace(old, new, 1)


MAIN_OLD = '''local function onInitGlobalModData()
    if getWorld():getGameMode() == "Multiplayer" and not isClient() then return end
    BB_Achievements = ModData.getOrCreate("BB_Achievements")

    if BB_Achievements.startGame == nil then
        ResetAchievements()
    end
'''

MAIN_NEW = '''%s
function BB_Achievements_Initialize(playerObj)
    if not playerObj then return false end

    local playerData = playerObj:getModData()
    local achievements = playerData.BB_Achievements
    local created = false
    if achievements == nil then
        achievements = {}
        playerData.BB_Achievements = achievements
        created = true
    end

    -- Build defaults in a temporary table, then merge them additively.  This
    -- retains completed achievements when upstream adds a new definition.
    BB_Achievements = achievements
    if created then
        ResetAchievements()
    else
        BB_Achievements = {}
        ResetAchievements()
        local defaults = BB_Achievements
        BB_Achievements = achievements
        for name, definition in pairs(defaults) do
            if achievements[name] == nil then
                achievements[name] = definition
            elseif type(definition) == "table" and type(achievements[name]) == "table" then
                for field, value in pairs(definition) do
                    if achievements[name][field] == nil then
                        achievements[name][field] = value
                    end
                end
            end
        end
    end

''' % MARKER

TRACKER_OLD = '''local function onInitGlobalModData()
    if getWorld():getGameMode() == "Multiplayer" and not isClient() then return end
    BB_Achievements_Tracker = ModData.getOrCreate("BB_Achievements_Tracker")

    if BB_Achievements_Tracker.characterName == nil then
        ResetAchievementTrackers()
    end
end

Events.OnInitGlobalModData.Add(onInitGlobalModData)'''

TRACKER_NEW = '''%s
function BB_Achievements_InitializeTracker(playerObj)
    if not playerObj then return false end

    local playerData = playerObj:getModData()
    local tracker = playerData.BB_Achievements_Tracker
    local created = false
    if tracker == nil then
        tracker = {}
        playerData.BB_Achievements_Tracker = tracker
        created = true
    end

    BB_Achievements_Tracker = tracker
    if created then
        ResetAchievementTrackers()
    else
        BB_Achievements_Tracker = {}
        ResetAchievementTrackers()
        local defaults = BB_Achievements_Tracker
        BB_Achievements_Tracker = tracker
        for field, value in pairs(defaults) do
            if tracker[field] == nil then
                tracker[field] = value
            end
        end
    end
    return true
end''' % MARKER

CLIENT_OLD = '''local function onLoadCharacter()
    climateManager = getClimateManager()

    local fullCharName = getPlayer():getFullName()

    if BB_Achievements_Tracker.characterName ~= fullCharName then
        if BB_Achievements.startGame.achieved and SandboxVars.Achievements.ResetOnSwitch then
            ResetAchievements()
            ResetAchievementTrackers()
            BB_Achievements.startGame.achieved = true
        end

        BB_Achievements_Tracker.characterName = fullCharName
    end

    if not BB_Achievements.startGame.achieved then
        AchievementHandler.popIn(BB_Achievements.startGame)
    end
end'''

CLIENT_NEW = '''%s
local function onLoadCharacter(playerIndex, playerObj)
    climateManager = getClimateManager()

    local player = playerObj or getPlayer()
    if not player then return end
    if not BB_Achievements_Initialize or not BB_Achievements_InitializeTracker then
        print("BB_Achievements: player persistence helpers are unavailable")
        return
    end

    BB_Achievements_Initialize(player)
    BB_Achievements_InitializeTracker(player)

    -- Player ModData is already per character.  ResetOnSwitch previously
    -- compensated for one global table and would reset reconnecting players.
    if not BB_Achievements.startGame.achieved then
        AchievementHandler.popIn(BB_Achievements.startGame)
    end
end''' % MARKER


def plan_file(relative, text):
    if MARKER in text:
        if text.count(MARKER) != 1:
            raise CompatibilityMismatch(f"{relative}: duplicate local-fix marker")
        return text, "ALREADY PATCHED"
    if relative == LUA_RELATIVES[0]:
        updated = replace_once(text, MAIN_OLD, MAIN_NEW, str(relative))
        return replace_once(updated, GLOBAL_INIT_EVENT, "", str(relative)), "APPLIED"
    if relative == LUA_RELATIVES[1]:
        return replace_once(text, TRACKER_OLD, TRACKER_NEW, str(relative)), "APPLIED"
    if relative == LUA_RELATIVES[2]:
        return replace_once(text, CLIENT_OLD, CLIENT_NEW, str(relative)), "APPLIED"
    raise AssertionError(f"unexpected Lua path: {relative}")


def plan_mod(root):
    info = root / "mod.info"
    if mod_info_id(info) != MOD_ID or mod_info_value(info, "modversion") != MOD_VERSION:
        raise CompatibilityMismatch(f"mod.info is not the supported {MOD_ID} {MOD_VERSION} revision")
    tree = root / B42_TREE
    paths = [tree / relative for relative in LUA_RELATIVES]
    missing = [str(relative) for relative, path in zip(LUA_RELATIVES, paths) if not path.is_file()]
    if missing:
        raise CompatibilityMismatch("target missing: " + ", ".join(missing))

    plan = []
    for relative, path in zip(LUA_RELATIVES, paths):
        text = path.read_text(encoding="utf-8", errors="strict")
        updated, status = plan_file(relative, text)
        plan.append((path, text, updated, status))

    statuses = {status for _path, _text, _updated, status in plan}
    if statuses == {"ALREADY PATCHED"}:
        return plan
    if statuses != {"APPLIED"}:
        raise CompatibilityMismatch("mixed patched and upstream Lua state; refusing partial repair")
    return plan


def patch_mod(root, log):
    try:
        plan = plan_mod(root)
    except (UnicodeError, CompatibilityMismatch) as exc:
        log(f"Braven's Achievements: BLOCKED / UPSTREAM CHANGED ({exc}).")
        return False

    if all(status == "ALREADY PATCHED" for _path, _text, _updated, status in plan):
        log("Braven's Achievements: ALREADY PATCHED.")
        return False

    # All files were validated before any backup or mutation is made.
    for path, _text, _updated, _status in plan:
        backup = path.with_suffix(path.suffix + ".pz-local-fix.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
    for path, _text, updated, _status in plan:
        rewrite_atomically(path, updated)
        log(f"Braven's Achievements: patched {path.name}.")
    return True


def run(ctx):
    log = ctx["log"]
    roots = matching_mod_roots(ctx)
    if not roots:
        log("Braven's Achievements: SKIPPED / TARGET NOT INSTALLED.")
        return False
    if len(roots) != 1:
        log(f"Braven's Achievements: BLOCKED / UPSTREAM CHANGED (found {len(roots)} installed mod roots).")
        return False
    relative = roots[0].relative_to(ctx["WORKSHOP"])
    log(f"Braven's Achievements: found installed mod at {relative}.")
    return patch_mod(roots[0], log)


FIX = {
    "name": "Braven's Achievements B42 player ModData persistence",
    "run": run,
}
