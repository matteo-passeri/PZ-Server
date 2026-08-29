#!/usr/bin/env python3
"""Stably order current VRO repair alternatives by VRO's displayed outcome."""
from pathlib import Path
import shutil


VRO_WORKSHOP_ID = "2757712197"
VRO_RELATIVE = Path(
    "mods/Vehicle Repair Overhaul/42/media/lua/client/zzz_VRO_Fixing.lua"
)
MARKER = "PZ-LOCAL-FIX: stable VRO repair material order v1"


def _replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"VRO-MLO: blocked; current VRO {label} anchor is not unique "
            f"(expected=1, found={count})."
        )
    return text.replace(old, new, 1)


def _backup_and_write(path, text):
    backup = path.with_suffix(path.suffix + ".pz-local-fix.material-list-order.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".pz-local-fix.material-list-order.tmp")
    if temporary.exists():
        raise RuntimeError(f"VRO-MLO: blocked; stale temporary file exists: {temporary}")
    temporary.write_text(text, encoding="utf-8")
    if temporary.read_text(encoding="utf-8", errors="replace") != text:
        raise RuntimeError("VRO-MLO: temporary-file verification failed.")
    temporary.replace(path)


def run(ctx):
    target = ctx["WORKSHOP"] / VRO_WORKSHOP_ID / VRO_RELATIVE
    log = ctx["log"]
    if not target.is_file():
        log("VRO-MLO: current VRO fixer source is absent; skip.")
        return False

    original = target.read_text(encoding="utf-8", errors="replace")
    if MARKER in original:
        log("VRO-MLO: material ordering already applied; skip.")
        return False

    text = _replace_once(
        original,
        """----------------------------------------------------------------
-- F) Mechanics window (vanilla-style submenu; attach to existing)
----------------------------------------------------------------""",
        """-- PZ-LOCAL-FIX: stable VRO repair material order v1
-- Only VRO-tagged options move. Their original slots keep unrelated menu
-- entries fixed, while index makes Lua's otherwise unstable sort stable.
local function sortVRORepairMaterials(sub)
  local opts = sub and sub.options
  if type(opts) ~= "table" then return end
  local slots, choices = {}, {}
  for i = 1, #opts do
    local option = opts[i]
    if option and option._VRO_potentialRepair ~= nil then
      slots[#slots + 1] = i
      choices[#choices + 1] = { option = option, index = i }
    end
  end
  table.sort(choices, function(a, b)
    local ap, bp = a.option._VRO_potentialRepair, b.option._VRO_potentialRepair
    return ap == bp and a.index < b.index or ap > bp
  end)
  for i = 1, #choices do opts[slots[i]] = choices[i].option end
end

----------------------------------------------------------------
-- F) Mechanics window (vanilla-style submenu; attach to existing)
----------------------------------------------------------------""",
        "menu helper boundary",
    )
    text = _replace_once(
        text,
        """        addFixerTooltip(tip, playerObj, part, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and createdRepairParent and not rendered and isSubmenuEmpty(parent) then""",
        """        addFixerTooltip(tip, playerObj, part, fixing, fixer, idx, broken)
        option.toolTip = tip
        option._VRO_potentialRepair = math.ceil(condRepairedPercent(
          broken, playerObj, fixing, fixer, getHBR(part, broken), idx))
      end
    end
  end

  sortVRORepairMaterials(sub)

  if parent and createdRepairParent and not rendered and isSubmenuEmpty(parent) then""",
        "vehicle menu potential-repair assignment",
    )
    text = _replace_once(
        text,
        """        addFixerTooltip(tip, playerObj, nil, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and not rendered and isSubmenuEmpty(parent) then""",
        """        addFixerTooltip(tip, playerObj, nil, fixing, fixer, idx, broken)
        option.toolTip = tip
        option._VRO_potentialRepair = math.ceil(condRepairedPercent(
          broken, playerObj, fixing, fixer, getHBR(nil, broken), idx))
      end
    end
  end

  sortVRORepairMaterials(sub)

  if parent and not rendered and isSubmenuEmpty(parent) then""",
        "inventory menu potential-repair assignment",
    )
    if MARKER not in text:
        raise RuntimeError("VRO-MLO: patch construction lost its marker.")

    _backup_and_write(target, text)
    verify = target.read_text(encoding="utf-8", errors="replace")
    if MARKER not in verify or verify.count("option._VRO_potentialRepair") != 5:
        raise RuntimeError("VRO-MLO: post-write verification failed.")
    log("VRO-MLO: restored stable material ordering for both VRO menus.")
    return True


FIX = {"name": "VRO material list order", "run": run}
