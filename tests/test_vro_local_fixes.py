"""Fixture tests for the current upstream VRO fixer structure.

These fixtures deliberately contain only the guarded VRO regions used by the
patchers. They model the current 90fa975 source shape without making the test
suite depend on an installed Steam Workshop tree.
"""
from pathlib import Path

import pytest

from conftest import FIX_SCRIPTS as FIX_DIR, fix_context, load_path_module


VRO_RELATIVE = Path(
    "2757712197/mods/Vehicle Repair Overhaul/42/media/lua/client/zzz_VRO_Fixing.lua"
)


CURRENT_VRO = '''----------------------------------------------------------------
-- D) Tooltip (dynamic color + icon)
----------------------------------------------------------------
local function addFixerTooltip(tip, player, part, fixing, fixer, fixerIndex, brokenItem)
  local inv = player:getInventory()
end

local function queueEquipActions(playerObj, eq, torchHint)
  if not eq then return nil, nil, nil end

  local inv        = playerObj:getInventory()
  local equipKeep  = {}

  -- make sure an item is actually in the player inventory (not in a bag)
  local function _ensureInPlayerInv(it)
    if not it then return end
    if it:getContainer() ~= inv then
      toPlayerInventory(playerObj, it)
    end
  end
  local forcedTorch = nil
    -- make sure it’s in main inventory so we can equip it
    _ensureInPlayerInv(forcedTorch)
  local chosenPrimary = nil
  local curP = nil
    if chosenPrimary and chosenPrimary ~= curP then
      _ensureInPlayerInv(chosenPrimary)
      ISTimedActionQueue.add()
    end
  local chosenSecondary = nil
  local curS = nil
    if chosenSecondary and chosenSecondary ~= curS then
      _ensureInPlayerInv(chosenSecondary)
      ISTimedActionQueue.add()
    end
end

----------------------------------------------------------------
-- F) Mechanics window (vanilla-style submenu; attach to existing)
----------------------------------------------------------------
local function vehicleMenu(playerObj, sub, part, fixing, fixer, idx, broken)
        local inv = playerObj:getInventory()
          option = sub:addOption(label, playerObj, function(p, prt, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            queuePathToPartArea(p, prt)
            local chosenP, chosenS, equipKeep, err =
              queueEquipActions(p, mergeEquip(fixr.equip, fixg.equip), torchHint)
            if err == "need_torch_uses" then
              return
            end

            local torchUses = _weldingUses(fixr, fixg)
          end)
        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, part, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and createdRepairParent and not rendered and isSubmenuEmpty(parent) then
  end
end

local function inventoryMenu(playerObj, sub, fixing, fixer, idx, broken)
        local inv = playerObj:getInventory()
          option = sub:addOption(label, playerObj, function(p, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            local chosenP, chosenS, equipKeep, err =
              queueEquipActions(p, mergeEquip(fixr.equip, fixg.equip), torchHint)
            if err == "need_torch_uses" then
              return
            end
          end)
        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, nil, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and not rendered and isSubmenuEmpty(parent) then
  end
end
'''


def target(workshop):
    path = workshop / VRO_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(CURRENT_VRO, encoding="utf-8")
    return path


def fixer(name):
    return load_path_module(FIX_DIR / name)


def test_nearby_containers_patch_uses_current_companion_api_and_is_idempotent(tmp_path):
    path = target(tmp_path / "workshop")
    module = fixer("30-vro-nearby-containers.py")
    assert module.FIX["run"](fix_context(tmp_path / "workshop"))
    patched = path.read_text(encoding="utf-8")

    # Companion absent: VRO follows its normal player-inventory path.
    assert 'return playerObj:getInventory()' in patched
    # Companion present: all current provider entry points are used.
    for api in (
        "getEffectiveInventory",
        "queueItemToPlayer",
        "queueBundleToPlayer",
        "queueKeepToPlayer",
    ):
        assert api in patched
    assert patched.count("VRO_effectiveInventory(playerObj)") == 4
    assert "local inv = VRO_effectiveInventory(player)" in patched
    # Selected material/global/keep bundles stage before equipment and repair.
    vehicle_stage = patched.index("VRO_stageRepairItems(p, fxB, glB, glK)")
    vehicle_equip = patched.index("queueEquipActions(p, mergeEquip(fixr.equip, fixg.equip), torchHint)")
    vehicle_path = patched.index("queuePathToPartArea(p, prt)", vehicle_stage)
    assert vehicle_stage < vehicle_equip < vehicle_path
    assert patched.count("VRO_stageRepairItems(p, fxB, glB, glK)") == 2
    assert "M.pending" not in patched  # de-duplication remains companion-owned.
    assert not module.FIX["run"](fix_context(tmp_path / "workshop"))


def test_nearby_containers_patch_covers_tags_torch_and_exact_bundle_staging(tmp_path):
    path = target(tmp_path / "workshop")
    module = fixer("30-vro-nearby-containers.py")
    assert module.FIX["run"](fix_context(tmp_path / "workshop"))
    patched = path.read_text(encoding="utf-8")
    # The current VRO tag, multi-tag, blowtorch and bundle selection functions
    # all receive the effective inventory through the two menus/queue helper.
    assert patched.count("local inv = VRO_effectiveInventory(playerObj)") == 2
    assert "nc.queueBundleToPlayer(playerObj, fixerBundle)" in patched
    assert "nc.queueBundleToPlayer(playerObj, globalBundle)" in patched
    assert "nc.queueKeepToPlayer(playerObj, globalKeep)" in patched
    assert "nc.queueItemToPlayer(playerObj, it)" in patched


@pytest.mark.parametrize("mutation", (
    lambda text: text.replace("-- D) Tooltip (dynamic color + icon)", "-- changed", 1),
    lambda text: text.replace("local inv = player:getInventory()", "local inv = player:getInventory()\n  local inv = player:getInventory()", 1),
))
def test_nearby_containers_fails_closed_without_writing(tmp_path, mutation):
    path = target(tmp_path / "workshop")
    original = mutation(path.read_text(encoding="utf-8"))
    path.write_text(original, encoding="utf-8")
    with pytest.raises(RuntimeError, match="blocked"):
        fixer("30-vro-nearby-containers.py").FIX["run"](fix_context(tmp_path / "workshop"))
    assert path.read_text(encoding="utf-8") == original


def test_material_order_patch_reuses_current_calculation_and_is_idempotent(tmp_path):
    path = target(tmp_path / "workshop")
    module = fixer("50-vro-material-list-order.py")
    assert module.FIX["run"](fix_context(tmp_path / "workshop"))
    patched = path.read_text(encoding="utf-8")
    assert patched.count("option._VRO_potentialRepair = math.ceil(condRepairedPercent(") == 2
    assert "return ap == bp and a.index < b.index or ap > bp" in patched
    assert "opts[slots[i]] = choices[i].option" in patched
    assert patched.count("sortVRORepairMaterials(sub)") == 3
    assert not module.FIX["run"](fix_context(tmp_path / "workshop"))


def test_material_order_fails_closed_without_writing(tmp_path):
    path = target(tmp_path / "workshop")
    original = path.read_text(encoding="utf-8").replace(
        "-- F) Mechanics window (vanilla-style submenu; attach to existing)",
        "-- changed", 1,
    )
    path.write_text(original, encoding="utf-8")
    with pytest.raises(RuntimeError, match="blocked"):
        fixer("50-vro-material-list-order.py").FIX["run"](fix_context(tmp_path / "workshop"))
    assert path.read_text(encoding="utf-8") == original
