#!/usr/bin/env python3
"""Restore the optional VRO Nearby Containers integration for current VRO."""
from pathlib import Path
import shutil


VRO_WORKSHOP_ID = "2757712197"
VRO_RELATIVE = Path(
    "mods/Vehicle Repair Overhaul/42/media/lua/client/zzz_VRO_Fixing.lua"
)
MARKER = "PZ-LOCAL-FIX: VRO Nearby Containers v1"


def _replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"VRO-NC: blocked; current VRO {label} anchor is not unique "
            f"(expected=1, found={count})."
        )
    return text.replace(old, new, 1)


def _backup_and_write(path, text):
    backup = path.with_suffix(path.suffix + ".pz-local-fix.nearby-containers.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".pz-local-fix.nearby-containers.tmp")
    if temporary.exists():
        raise RuntimeError(f"VRO-NC: blocked; stale temporary file exists: {temporary}")
    temporary.write_text(text, encoding="utf-8")
    if temporary.read_text(encoding="utf-8", errors="replace") != text:
        raise RuntimeError("VRO-NC: temporary-file verification failed.")
    temporary.replace(path)


def run(ctx):
    target = ctx["WORKSHOP"] / VRO_WORKSHOP_ID / VRO_RELATIVE
    log = ctx["log"]
    if not target.is_file():
        log("VRO-NC: current VRO fixer source is absent; skip.")
        return False

    original = target.read_text(encoding="utf-8", errors="replace")
    if MARKER in original:
        log("VRO-NC: Nearby Containers compatibility already applied; skip.")
        return False

    text = original
    text = _replace_once(
        text,
        """----------------------------------------------------------------
-- D) Tooltip (dynamic color + icon)
----------------------------------------------------------------""",
        """----------------------------------------------------------------
-- PZ-LOCAL-FIX: VRO Nearby Containers v1
-- Workshop 3783281822 / Mod ID VRONearbyContainers is optional. Its v1 API
-- aggregates discovery and queues MP-safe transfer actions for exact objects.
----------------------------------------------------------------
local function VRO_effectiveInventory(playerObj)
  local nc = rawget(_G, "VRONearbyContainers")
  if nc and type(nc.getEffectiveInventory) == "function"
      and type(nc.queueItemToPlayer) == "function"
      and type(nc.queueBundleToPlayer) == "function"
      and type(nc.queueKeepToPlayer) == "function" then
    local ok, inv = pcall(nc.getEffectiveInventory, playerObj)
    if ok and inv then return inv end
  end
  return playerObj:getInventory()
end

local function VRO_stageRepairItems(playerObj, fixerBundle, globalBundle, globalKeep)
  local nc = rawget(_G, "VRONearbyContainers")
  if not (nc and type(nc.queueItemToPlayer) == "function"
      and type(nc.queueBundleToPlayer) == "function"
      and type(nc.queueKeepToPlayer) == "function") then
    return true
  end
  return nc.queueBundleToPlayer(playerObj, fixerBundle)
      and nc.queueBundleToPlayer(playerObj, globalBundle)
      and nc.queueKeepToPlayer(playerObj, globalKeep)
end

----------------------------------------------------------------
-- D) Tooltip (dynamic color + icon)
----------------------------------------------------------------""",
        "tooltip helper boundary",
    )
    text = _replace_once(
        text,
        "  local inv = player:getInventory()",
        "  local inv = VRO_effectiveInventory(player)",
        "tooltip resource inventory",
    )
    text = _replace_once(
        text,
        """  local inv        = playerObj:getInventory()
  local equipKeep  = {}

  -- make sure an item is actually in the player inventory (not in a bag)
  local function _ensureInPlayerInv(it)
    if not it then return end
    if it:getContainer() ~= inv then
      toPlayerInventory(playerObj, it)
    end
  end""",
        """  local playerInv  = playerObj:getInventory()
  local inv        = VRO_effectiveInventory(playerObj)
  local equipKeep  = {}

  -- VRO-NC queues an MP-safe transfer for nearby/world objects. The companion
  -- de-duplicates pending objects, so an item selected by more than one role
  -- cannot acquire duplicate transfer actions.
  local function _ensureInPlayerInv(it)
    if not it or it:getContainer() == playerInv then return true end
    local nc = rawget(_G, "VRONearbyContainers")
    if nc and type(nc.queueItemToPlayer) == "function" then
      return nc.queueItemToPlayer(playerObj, it)
    end
    toPlayerInventory(playerObj, it)
    return true
  end""",
        "queueEquipActions resource inventory",
    )
    text = _replace_once(
        text,
        """    -- make sure it’s in main inventory so we can equip it
    _ensureInPlayerInv(forcedTorch)""",
        """    -- make sure it’s in main inventory so we can equip it
    if not _ensureInPlayerInv(forcedTorch) then
      return nil, nil, nil, "stage_failed"
    end""",
        "forced blowtorch staging",
    )
    text = _replace_once(
        text,
        """    if chosenPrimary and chosenPrimary ~= curP then
      _ensureInPlayerInv(chosenPrimary)
      ISTimedActionQueue.add""",
        """    if chosenPrimary and chosenPrimary ~= curP then
      if not _ensureInPlayerInv(chosenPrimary) then
        return nil, nil, nil, "stage_failed"
      end
      ISTimedActionQueue.add""",
        "primary equipment staging",
    )
    text = _replace_once(
        text,
        """    if chosenSecondary and chosenSecondary ~= curS then
      _ensureInPlayerInv(chosenSecondary)
      ISTimedActionQueue.add""",
        """    if chosenSecondary and chosenSecondary ~= curS then
      if not _ensureInPlayerInv(chosenSecondary) then
        return nil, nil, nil, "stage_failed"
      end
      ISTimedActionQueue.add""",
        "secondary equipment staging",
    )
    old = "        local inv = playerObj:getInventory()"
    if text.count(old) != 2:
        raise RuntimeError(
            "VRO-NC: blocked; current VRO menu inventory anchors are not "
            f"unique (expected=2, found={text.count(old)})."
        )
    text = text.replace(old, "        local inv = VRO_effectiveInventory(playerObj)")
    text = _replace_once(
        text,
        """          option = sub:addOption(label, playerObj, function(p, prt, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            queuePathToPartArea(p, prt)
            local chosenP, chosenS, equipKeep, err =""",
        """          option = sub:addOption(label, playerObj, function(p, prt, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            if not VRO_stageRepairItems(p, fxB, glB, glK) then return end
            -- VRO-NC vehicle queue boundary
            local chosenP, chosenS, equipKeep, err =""",
        "vehicle repair staging sequence",
    )
    text = _replace_once(
        text,
        """            -- VRO-NC vehicle queue boundary
            local chosenP, chosenS, equipKeep, err =
              queueEquipActions(p, mergeEquip(fixr.equip, fixg.equip), torchHint)
            if err == "need_torch_uses" then
              return
            end

            local torchUses = _weldingUses(fixr, fixg)""",
        """            -- VRO-NC vehicle queue boundary
            local chosenP, chosenS, equipKeep, err =
              queueEquipActions(p, mergeEquip(fixr.equip, fixg.equip), torchHint)
            if err == "need_torch_uses" then
              return
            end
            queuePathToPartArea(p, prt)

            local torchUses = _weldingUses(fixr, fixg)""",
        "vehicle repair path ordering",
    )
    text = _replace_once(
        text,
        """          option = sub:addOption(label, playerObj, function(p, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            local chosenP, chosenS, equipKeep, err =""",
        """          option = sub:addOption(label, playerObj, function(p, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            if not VRO_stageRepairItems(p, fxB, glB, glK) then return end
            local chosenP, chosenS, equipKeep, err =""",
        "inventory repair staging sequence",
    )
    error_check = '''            if err == "need_torch_uses" then
              return
            end'''
    if text.count(error_check) != 2:
        raise RuntimeError(
            "VRO-NC: blocked; current VRO equipment error checks are not "
            f"unique (expected=2, found={text.count(error_check)})."
        )
    text = text.replace(error_check, '''            if err then
              return
            end''')
    if MARKER not in text:
        raise RuntimeError("VRO-NC: patch construction lost its marker.")

    _backup_and_write(target, text)
    verify = target.read_text(encoding="utf-8", errors="replace")
    if MARKER not in verify or "VRO_effectiveInventory(playerObj)" not in verify:
        raise RuntimeError("VRO-NC: post-write verification failed.")
    log("VRO-NC: restored optional Nearby Containers discovery and staging.")
    return True


FIX = {"name": "VRO Nearby Containers compatibility", "run": run}
