#!/usr/bin/env python3
from pathlib import Path
import hashlib
import shutil
import subprocess
from datetime import datetime

def run(ctx):
    WORKSHOP = ctx['WORKSHOP']
    log = ctx['log']

    target = (
        WORKSHOP
        / "3739173520"
        / "mods"
        / "Plysken Irrigation Pipes"
        / "42.1"
        / "media"
        / "lua"
        / "server"
        / "PIP"
        / "PIPBarrelRegistry.lua"
    )

    if not target.is_file():
        log(
            "PIP: PIPBarrelRegistry.lua non presente; skip."
        )
        return False

    text = target.read_text(
        encoding="utf-8",
        errors="replace",
    )

    self_heal_marker = "groupId self-heal"

    if self_heal_marker in text:
        log(
            "PIP: groupId self-heal già presente; skip."
        )
        return False

    old = '''    end
    return nil
end

-- (Re)peupler PIP.Marked depuis le ModData au chargement, en re-fetchant les IsoObject presents.
function PIP.Barrels.seedFromModData()'''

    new = '''    end

    -- Self-heal : le barrel existe fisicamente ma ha perso il
    -- marquage server-side. Ricostruiamo il network da una pipe
    -- registrata adiacente usando la logica PIP esistente.
    if PIP.Network
       and PIP.Network.getPipeAt
       and PIP.Network.assignIdAndUnify then

        for _, d in ipairs(PIP.DIRS_CARD) do
            local px, py = x + d[1], y + d[2]
            local rec = PIP.Network.getPipeAt(px, py, z)

            if rec then
                local psq = getSquare(px, py, z)
                local pobj = psq and PIP.findPipeObject(psq) or nil

                if pobj then
                    PIP.Network.assignIdAndUnify(pobj)

                    local repaired = PIP.Marked[k]
                    if repaired and repaired.id and repaired.id > 0 then
                        PIP.dbg(
                            "groupId self-heal",
                            "barrel="..x..","..y..","..z,
                            "gid="..tostring(repaired.id)
                        )
                        return repaired.id
                    end
                end
            end
        end
    end

    return nil
end

-- (Re)peupler PIP.Marked depuis le ModData au chargement, en re-fetchant les IsoObject presents.
function PIP.Barrels.seedFromModData()'''

    count = text.count(old)

    if count != 1:
        raise RuntimeError(
            "PIP: struttura PIPBarrelRegistry.lua incompatibile. "
            f"Attesa=1 trovata={count}. Patch NON applicata."
        )

    backup = target.with_suffix(
        target.suffix + ".pz-local-fix.bak"
    )

    if not backup.exists():
        shutil.copy2(
            target,
            backup,
        )

    patched = text.replace(
        old,
        new,
        1,
    )

    target.write_text(
        patched,
        encoding="utf-8",
    )

    verify = target.read_text(
        encoding="utf-8",
        errors="replace",
    )

    if self_heal_marker not in verify:
        raise RuntimeError(
            "PIP: verifica post-patch fallita."
        )

    log(
        "PIP: groupId self-heal applicato."
    )

    return True

FIX = {
    "name": 'Plysken Irrigation Pipes groupId self-heal',
    "run": run,
}
