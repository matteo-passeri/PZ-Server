#!/usr/bin/env python3
from pathlib import Path
import hashlib
import shutil
import subprocess
from datetime import datetime

def run(ctx):
    WORKSHOP = ctx['WORKSHOP']
    log = ctx['log']
    sha256 = ctx['sha256']

    target = (
        WORKSHOP
        / "2757712197"
        / "mods"
        / "Vehicle Repair Overhaul"
        / "42"
        / "media"
        / "lua"
        / "server"
        / "VRO_TrunkCapacity.lua"
    )

    supported_sha256 = (
        "49d9680955c2b2f03f07b35728a9c070"
        "019d59bd4c01a1a6c5064f74a0d1713d"
    )

    patch_marker = "PZ local fix: respect conditionAffectsCapacity"

    if not target.is_file():
        log("VRO-TC: VRO_TrunkCapacity.lua non presente; skip.")
        return False

    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"VRO-TC: impossibile leggere {target}: {exc}"
        )

    if patch_marker in text:
        log("VRO-TC: conditionAffectsCapacity già corretto; skip.")
        return False

    current_hash = sha256(target)

    if current_hash != supported_sha256:
        raise RuntimeError(
            "VRO-TC: upstream VRO_TrunkCapacity.lua cambiato. "
            "Patch NON applicata automaticamente. "
            f"SHA256 atteso={supported_sha256} "
            f"trovato={current_hash}"
        )

    old = '''local function sweepVehicle(vehicle)
    local count = vehicle:getPartCount()
    for i = 0, count - 1 do
        local part = vehicle:getPartByIndex(i)
        if part then
            local container = part:getItemContainer()
            local item = part:getInventoryItem()
            if container and item then
                local maxCapacity = item:getMaxCapacity()
                if maxCapacity and maxCapacity > 0 then
                    local want = expectedCapacity(maxCapacity, item:getCondition())
                    if container:getCapacity() < want then
                        log(string.format("veiculo %s, peca %s: capacidade %s -> %s",
                            tostring(vehicle:getId()), tostring(part:getId()),
                            tostring(container:getCapacity()), tostring(want)))
                        part:setContainerCapacity(want)
                        vehicle:transmitPartItem(part)
                    end
                end
            end
        end
    end
end'''

    new = '''local function sweepVehicle(vehicle)
    local count = vehicle:getPartCount()
    for i = 0, count - 1 do
        local part = vehicle:getPartByIndex(i)
        if part then
            local scriptPart = part:getScriptPart()
            local scriptContainer = scriptPart and scriptPart.container

            -- PZ local fix: respect conditionAffectsCapacity
            -- Ricalcola solo i container per cui la condition
            -- deve realmente influenzare la capacity.
            if scriptContainer and scriptContainer.conditionAffectsCapacity then
                local container = part:getItemContainer()
                local item = part:getInventoryItem()

                if container and item then
                    local maxCapacity = item:getMaxCapacity()
                    if maxCapacity and maxCapacity > 0 then
                        local want = expectedCapacity(maxCapacity, item:getCondition())
                        if container:getCapacity() < want then
                            log(string.format("veiculo %s, peca %s: capacidade %s -> %s",
                                tostring(vehicle:getId()), tostring(part:getId()),
                                tostring(container:getCapacity()), tostring(want)))
                            part:setContainerCapacity(want)
                            vehicle:transmitPartItem(part)
                        end
                    end
                end
            end
        end
    end
end'''

    count = text.count(old)

    if count != 1:
        raise RuntimeError(
            "VRO-TC: struttura sweepVehicle incompatibile. "
            f"Attesa=1 trovata={count}. Patch NON applicata."
        )

    patched = text.replace(old, new, 1)

    backup = target.with_suffix(
        target.suffix + ".pz-local-fix.bak"
    )

    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(
        patched,
        encoding="utf-8",
    )

    verify = target.read_text(
        encoding="utf-8",
        errors="replace",
    )

    if patch_marker not in verify:
        raise RuntimeError(
            "VRO-TC: verifica post-patch fallita."
        )

    log(
        "VRO-TC: legacy sweep corretta per "
        "conditionAffectsCapacity."
    )

    return True

FIX = {
    "name": 'VRO Trunk Capacity',
    "run": run,
}
