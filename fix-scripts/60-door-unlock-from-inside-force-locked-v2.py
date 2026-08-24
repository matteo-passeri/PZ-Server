#!/usr/bin/env python3
from pathlib import Path
import shutil

WORKSHOP_ID = "3712058921"
MARKER = "PZ-LOCAL-FIX: preserve forceLocked doors v2"

SERVER_REL = Path("mods/DoorUnlockFromInside/42/media/lua/server/DoorUnlock_Server.lua")
CLIENT_REL = Path("mods/DoorUnlockFromInside/42/media/lua/client/DoorUnlockFromInside.lua")


def backup_and_write(path, new):
    backup = path.with_suffix(path.suffix + ".pz-local-fix.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(new, encoding="utf-8")


def replace_once(text, old, new):
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def run(ctx):
    root = ctx["WORKSHOP"] / WORKSHOP_ID
    log = ctx["log"]

    server = root / SERVER_REL
    client = root / CLIENT_REL

    if not server.is_file() or not client.is_file():
        log("DoorUnlockFromInside: file v5/v5.2 attesi non trovati; skip.")
        return False

    s = server.read_text(encoding="utf-8", errors="replace")
    c = client.read_text(encoding="utf-8", errors="replace")

    if MARKER in s and MARKER in c:
        log("DoorUnlockFromInside: patch forceLocked v2 già presente; skip.")
        return False

    # =========================================================
    # SERVER: ultima barriera di sicurezza.
    # Non sbloccare porte forceLocked anche se il client
    # invia esplicitamente DoorUnlock/unlockAt.
    # =========================================================

    server_old = '''            if isDoor or isDoorThump then
                pcall(function() if o.setLocked then o:setLocked(false) end end)
                pcall(function() if o.setLockedByKey then o:setLockedByKey(false) end end)
                pcall(function() if o.setIsLocked then o:setIsLocked(false) end end)
                unlocked = true
            end'''

    server_new = '''            if isDoor or isDoorThump then
                -- PZ-LOCAL-FIX: preserve forceLocked doors v2
                local forceLocked = false
                pcall(function()
                    local props = o:getProperties()
                    forceLocked = props and props:has("forceLocked") or false
                end)

                if not forceLocked then
                    pcall(function() if o.setLocked then o:setLocked(false) end end)
                    pcall(function() if o.setLockedByKey then o:setLockedByKey(false) end end)
                    pcall(function() if o.setIsLocked then o:setIsLocked(false) end end)
                    unlocked = true
                end
            end'''

    ns, ok_s = replace_once(s, server_old, server_new)

    # =========================================================
    # CLIENT 1: requestUnlock()
    # Una square che contiene soltanto una porta forceLocked
    # non deve generare una richiesta di unlock al server.
    # =========================================================

    req_old = '''            if isDoor or isDoorT then hasDoor = true; break end'''

    req_new = '''            if isDoor or isDoorT then
                -- PZ-LOCAL-FIX: preserve forceLocked doors v2
                local forceLocked = false
                pcall(function()
                    local props = o:getProperties()
                    forceLocked = props and props:has("forceLocked") or false
                end)

                if not forceLocked then
                    hasDoor = true
                    break
                end
            end'''

    nc, ok1 = replace_once(c, req_old, req_new)

    # =========================================================
    # CLIENT 2: fallback single-player
    # =========================================================

    sp_old = '''        for i = 0, objs:size() - 1 do
            local o = objs:get(i)
            pcall(function() if o and o.setLocked then o:setLocked(false) end end)
            pcall(function() if o and o.setLockedByKey then o:setLockedByKey(false) end end)
            pcall(function() if o and o.setIsLocked then o:setIsLocked(false) end end)
        end'''

    sp_new = '''        for i = 0, objs:size() - 1 do
            local o = objs:get(i)

            if o then
                local _, isDoor = pcall(function()
                    return instanceof(o, "IsoDoor")
                end)

                local _, isThump = pcall(function()
                    return instanceof(o, "IsoThumpable")
                end)

                local _, isDoorT = pcall(function()
                    return isThump and o:isDoor()
                end)

                if isDoor or isDoorT then
                    -- PZ-LOCAL-FIX: preserve forceLocked doors v2
                    local forceLocked = false

                    pcall(function()
                        local props = o:getProperties()
                        forceLocked = props and props:has("forceLocked") or false
                    end)

                    if not forceLocked then
                        pcall(function()
                            if o.setLocked then
                                o:setLocked(false)
                            end
                        end)

                        pcall(function()
                            if o.setLockedByKey then
                                o:setLockedByKey(false)
                            end
                        end)

                        pcall(function()
                            if o.setIsLocked then
                                o:setIsLocked(false)
                            end
                        end)
                    end
                end
            end
        end'''

    nc, ok2 = replace_once(nc, sp_old, sp_new)

    # =========================================================
    # CLIENT 3: conferma ricevuta dal server
    # =========================================================

    sync_old = '''                    if isDoor or isDoorT then
                        pcall(function() if o.setLocked then o:setLocked(false) end end)
                        pcall(function() if o.setLockedByKey then o:setLockedByKey(false) end end)
                        pcall(function() if o.setIsLocked then o:setIsLocked(false) end end)
                    end'''

    sync_new = '''                    if isDoor or isDoorT then
                        -- PZ-LOCAL-FIX: preserve forceLocked doors v2
                        local forceLocked = false

                        pcall(function()
                            local props = o:getProperties()
                            forceLocked = props and props:has("forceLocked") or false
                        end)

                        if not forceLocked then
                            pcall(function()
                                if o.setLocked then
                                    o:setLocked(false)
                                end
                            end)

                            pcall(function()
                                if o.setLockedByKey then
                                    o:setLockedByKey(false)
                                end
                            end)

                            pcall(function()
                                if o.setIsLocked then
                                    o:setIsLocked(false)
                                end
                            end)
                        end
                    end'''

    nc, ok3 = replace_once(nc, sync_old, sync_new)

    # =========================================================
    # CLIENT 4: ISOpenCloseDoor:perform hook
    # Questo è particolarmente importante: impedisce al mod di
    # sbloccare localmente una security door appena prima
    # dell'apertura.
    # =========================================================

    hook_old = '''                    if indoors then
                        pcall(function() if self.door.setLocked then self.door:setLocked(false) end end)
                        pcall(function() if self.door.setLockedByKey then self.door:setLockedByKey(false) end end)
                        pcall(function() if self.door.setIsLocked then self.door:setIsLocked(false) end end)
                        -- 서버에도 요청
                        local sq = self.door:getSquare()
                        if sq and isClient() and sendClientCommand then
                            sendClientCommand(self.character, "DoorUnlock", "unlockAt",
                                { x = sq:getX(), y = sq:getY(), z = sq:getZ() })
                        end
                        log("Hook: unlocked door just before open")
                    end'''

    hook_new = '''                    if indoors then
                        -- PZ-LOCAL-FIX: preserve forceLocked doors v2
                        local forceLocked = false

                        pcall(function()
                            local props = self.door:getProperties()
                            forceLocked = props and props:has("forceLocked") or false
                        end)

                        if not forceLocked then
                            pcall(function()
                                if self.door.setLocked then
                                    self.door:setLocked(false)
                                end
                            end)

                            pcall(function()
                                if self.door.setLockedByKey then
                                    self.door:setLockedByKey(false)
                                end
                            end)

                            pcall(function()
                                if self.door.setIsLocked then
                                    self.door:setIsLocked(false)
                                end
                            end)

                            local sq = self.door:getSquare()

                            if sq and isClient() and sendClientCommand then
                                sendClientCommand(
                                    self.character,
                                    "DoorUnlock",
                                    "unlockAt",
                                    {
                                        x = sq:getX(),
                                        y = sq:getY(),
                                        z = sq:getZ()
                                    }
                                )
                            end

                            log("Hook: unlocked door just before open")
                        end
                    end'''

    nc, ok4 = replace_once(nc, hook_old, hook_new)

    # =========================================================
    # SAFETY:
    # tutti i punti devono corrispondere alla versione attesa.
    # Se ne manca anche uno, non modifichiamo NESSUN file.
    # =========================================================

    if not all((ok_s, ok1, ok2, ok3, ok4)):
        log(
            "DoorUnlockFromInside: ATTENZIONE: sorgente non corrisponde "
            "esattamente alla v5/v5.2 attesa; nessun file modificato."
        )

        log(
            "DoorUnlockFromInside: "
            "match server/request/SP/sync/hook = %s/%s/%s/%s/%s"
            % (ok_s, ok1, ok2, ok3, ok4)
        )

        return False

    # Sanity check ulteriore.
    if ns.count(MARKER) != 1 or nc.count(MARKER) != 4:
        log(
            "DoorUnlockFromInside: ATTENZIONE: sanity check fallito; "
            "nessun file modificato."
        )
        return False

    backup_and_write(server, ns)
    backup_and_write(client, nc)

    log("DoorUnlockFromInside: server v5.2 protetto contro forceLocked.")
    log("DoorUnlockFromInside: client v5 protetto in request/SP/sync/hook.")
    log("DoorUnlockFromInside: patch forceLocked v2 completata.")

    return True


FIX = {
    "name": "Door Unlock From Inside - preserve forceLocked doors v2",
    "run": run,
}
