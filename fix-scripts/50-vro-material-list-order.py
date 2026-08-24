#!/usr/bin/env python3
import shutil


VRO_WORKSHOP_ID = "2757712197"
VRO_MOD_PATH = (
    "mods/Vehicle Repair Overhaul/42/media/lua/client/"
    "zzz_VRO_Fixing.lua"
)
PATCH_MARKER = "local function sortVRORepairMaterials(sub)"


def run(ctx):
    workshop = ctx["WORKSHOP"]
    log = ctx["log"]

    target = workshop / VRO_WORKSHOP_ID / VRO_MOD_PATH

    if not target.is_file():
        log("VRO-MLO: zzz_VRO_Fixing.lua non presente; skip.")
        return False

    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"VRO-MLO: impossibile leggere {target}: {exc}"
        )

    if PATCH_MARKER in text:
        log("VRO-MLO: ordine materiali gia corretto; skip.")
        return False

    def replace_exact(old, new, description):
        nonlocal text

        count = text.count(old)

        if count != 1:
            raise RuntimeError(
                "VRO-MLO: struttura VRO incompatibile per "
                f"{description}. Attesa=1 trovata={count}. "
                "Patch NON applicata."
            )

        text = text.replace(old, new, 1)

    replace_exact(
        """----------------------------------------------------------------
-- F) Mechanics window (vanilla-style submenu; attach to existing)
----------------------------------------------------------------""",
        """-- Keep any existing vanilla entries in place, while ordering VRO's material
-- choices by the same potential-repair value shown in their tooltips.
local function sortVRORepairMaterials(sub)
  local opts = sub and sub.options
  if type(opts) ~= "table" then return end

  local positions, materials = {}, {}
  for i = 1, #opts do
    local option = opts[i]
    if option and option._VRO_potentialRepair ~= nil then
      positions[#positions + 1] = i
      materials[#materials + 1] = { option = option, index = i }
    end
  end

  table.sort(materials, function(a, b)
    local aPotential = a.option._VRO_potentialRepair
    local bPotential = b.option._VRO_potentialRepair
    if aPotential == bPotential then return a.index < b.index end
    return aPotential > bPotential
  end)

  for i = 1, #materials do
    opts[positions[i]] = materials[i].option
  end
end

----------------------------------------------------------------
-- F) Mechanics window (vanilla-style submenu; attach to existing)
----------------------------------------------------------------""",
        "repair-material sort helper",
    )

    replace_exact(
        """        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, part, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and createdRepairParent and not rendered and isSubmenuEmpty(parent) then""",
        """        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, part, fixing, fixer, idx, broken)
        option.toolTip = tip
        option._VRO_potentialRepair = math.ceil(condRepairedPercent(
          broken, playerObj, fixing, fixer, getHBR(part, broken), idx))
      end
    end
  end

  sortVRORepairMaterials(sub)

  if parent and createdRepairParent and not rendered and isSubmenuEmpty(parent) then""",
        "menu repair veicolo",
    )

    replace_exact(
        """        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, nil, fixing, fixer, idx, broken)
        option.toolTip = tip
      end
    end
  end

  if parent and not rendered and isSubmenuEmpty(parent) then""",
        """        local tip = ISToolTip:new()
        addFixerTooltip(tip, playerObj, nil, fixing, fixer, idx, broken)
        option.toolTip = tip
        option._VRO_potentialRepair = math.ceil(condRepairedPercent(
          broken, playerObj, fixing, fixer, getHBR(nil, broken), idx))
      end
    end
  end

  sortVRORepairMaterials(sub)

  if parent and not rendered and isSubmenuEmpty(parent) then""",
        "menu repair inventario",
    )

    if PATCH_MARKER not in text:
        raise RuntimeError(
            "VRO-MLO: costruzione patch completata senza marker. "
            "Nessun file modificato."
        )

    backup = target.with_suffix(
        target.suffix + ".pz-local-fix.material-list-order.bak"
    )

    try:
        if not backup.exists():
            shutil.copy2(target, backup)

        target.write_text(text, encoding="utf-8")
        verify = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"VRO-MLO: scrittura/verifica fallita per {target}: {exc}"
        )

    if PATCH_MARKER not in verify:
        raise RuntimeError("VRO-MLO: verifica post-patch fallita.")

    log("VRO-MLO: materiali ordinati per potenziale riparazione.")
    return True


FIX = {
    "name": "VRO Material List Order",
    "run": run,
}
