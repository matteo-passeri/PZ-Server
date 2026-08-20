#!/usr/bin/env python3
from pathlib import Path
import hashlib
import shutil
import subprocess
from datetime import datetime

def run(ctx):
    WORKSHOP = ctx['WORKSHOP']
    CONTAINER = ctx['CONTAINER']
    VRO_BACKUP_KEEP = ctx['VRO_BACKUP_KEEP']
    VRO_CONTAINER_TARGET = ctx['VRO_CONTAINER_TARGET']
    VRO_NC_MARKER = ctx['VRO_NC_MARKER']
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
        / "client"
        / "zzz_VRO_Fixing.lua"
    )

    if not target.is_file():
        log(
            "VRO-NC: Vehicle Repair Overhaul B42 "
            "non presente; skip."
        )
        return False

    try:
        original_text = target.read_text(
            encoding="utf-8",
        )
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"VRO-NC: impossibile leggere {target}: {exc}"
        )

    # Idempotenza: se il marker c'è già, non tocchiamo nulla.
    if VRO_NC_MARKER in original_text:
        log(
            "VRO-NC: integrazione VRO già presente; skip."
        )
        return False

    text = original_text

    def replace_exact(old, new, expected, description):
        nonlocal text

        count = text.count(old)

        if count != expected:
            raise RuntimeError(
                "VRO-NC: struttura VRO incompatibile per "
                f"{description}. "
                f"Attese={expected} trovate={count}. "
                "Patch NON applicata."
            )

        text = text.replace(old, new)

    # --------------------------------------------------------
    # 1. Helper Nearby Containers
    # --------------------------------------------------------

    old = """----------------------------------------------------------------
-- D) Tooltip (dynamic color + icon)
----------------------------------------------------------------"""

    new = """----------------------------------------------------------------
-- Nearby-container integration (optional companion mod)
----------------------------------------------------------------
local function VRO_effectiveInventory(playerObj)
  local nc = rawget(_G, "VRONearbyContainers")
  if nc and nc.getEffectiveInventory then
    local ok, inv = pcall(nc.getEffectiveInventory, playerObj)
    if ok and inv then return inv end
  end
  return playerObj:getInventory()
end

local function VRO_stageBundle(playerObj, bundle)
  local nc = rawget(_G, "VRONearbyContainers")
  if nc and nc.queueBundleToPlayer then
    return nc.queueBundleToPlayer(playerObj, bundle)
  end
  return true
end

----------------------------------------------------------------
-- D) Tooltip (dynamic color + icon)
----------------------------------------------------------------"""

    replace_exact(
        old,
        new,
        1,
        "helper Nearby Containers",
    )

    # --------------------------------------------------------
    # 2. Tooltip usa inventario effettivo
    # --------------------------------------------------------

    replace_exact(
        "  local inv = player:getInventory()",
        "  local inv = VRO_effectiveInventory(player)",
        1,
        "inventario tooltip",
    )

    # --------------------------------------------------------
    # 3. Equip: ricerca nei container vicini +
    #    staging verso inventario player
    # --------------------------------------------------------

    old = """  local inv        = playerObj:getInventory()
  local equipKeep  = {}

  -- make sure an item is actually in the player inventory (not in a bag)
  local function _ensureInPlayerInv(it)
    if not it then return end
    if it:getContainer() ~= inv then
      toPlayerInventory(playerObj, it)
    end
  end"""

    new = """  local playerInv  = playerObj:getInventory()
  local inv        = VRO_effectiveInventory(playerObj)
  local equipKeep  = {}

  -- make sure an item is actually in the player inventory (not in a bag)
  local function _ensureInPlayerInv(it)
    if not it then return end
    if it:getContainer() ~= playerInv then
      local nc = rawget(_G, "VRONearbyContainers")
      if nc and nc.queueItemToPlayer then
        nc.queueItemToPlayer(playerObj, it)
      else
        toPlayerInventory(playerObj, it)
      end
    end
  end"""

    replace_exact(
        old,
        new,
        1,
        "queueEquipActions",
    )

    # --------------------------------------------------------
    # 4. Entrambi i menu usano inventario effettivo
    # --------------------------------------------------------

    replace_exact(
        "        local inv = playerObj:getInventory()",
        "        local inv = VRO_effectiveInventory(playerObj)",
        2,
        "inventario menu repair",
    )

    # --------------------------------------------------------
    # 5. Repair veicolo: staging bundle
    # --------------------------------------------------------

    old = """          option = sub:addOption(label, playerObj, function(p, prt, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            queuePathToPartArea(p, prt)"""

    new = """          option = sub:addOption(label, playerObj, function(p, prt, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            VRO_stageBundle(p, fxB)
            VRO_stageBundle(p, glB)
            VRO_stageBundle(p, glK)
            queuePathToPartArea(p, prt)"""

    replace_exact(
        old,
        new,
        1,
        "staging repair veicolo",
    )

    # --------------------------------------------------------
    # 6. Repair inventario: staging bundle
    # --------------------------------------------------------

    old = """          option = sub:addOption(label, playerObj, function(p, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            local chosenP, chosenS, equipKeep, err ="""

    new = """          option = sub:addOption(label, playerObj, function(p, fixg, fixr, idx_, brk, fxB, glB, glK, torchHint)
            VRO_stageBundle(p, fxB)
            VRO_stageBundle(p, glB)
            VRO_stageBundle(p, glK)
            local chosenP, chosenS, equipKeep, err ="""

    replace_exact(
        old,
        new,
        1,
        "staging repair inventario",
    )

    if VRO_NC_MARKER not in text:
        raise RuntimeError(
            "VRO-NC: costruzione patch completata "
            "senza marker. Nessun file modificato."
        )

    patched_bytes = text.encode("utf-8")
    expected_hash = hashlib.sha256(
        patched_bytes
    ).hexdigest()

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime("%Y%m%d-%H%M%S")
    )

    backup_container = (
        VRO_CONTAINER_TARGET
        + ".pz-local-fix."
        + timestamp
        + ".bak"
    )

    log(
        "VRO-NC: struttura upstream compatibile. "
        "Creo backup tramite container..."
    )

    backup_proc = subprocess.run(
        [
            "podman",
            "exec",
            CONTAINER,
            "sh",
            "-c",
            'cp -a "$1" "$2"',
            "sh",
            VRO_CONTAINER_TARGET,
            backup_container,
        ],
        capture_output=True,
        text=True,
    )

    if backup_proc.returncode != 0:
        raise RuntimeError(
            "VRO-NC: backup tramite container fallito: "
            f"{(backup_proc.stderr or backup_proc.stdout).strip()}"
        )

    install_proc = subprocess.run(
        [
            "podman",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-c",
            'cat > "$1"',
            "sh",
            VRO_CONTAINER_TARGET,
        ],
        input=patched_bytes,
        capture_output=True,
    )

    if install_proc.returncode != 0:
        detail = (
            install_proc.stderr
            or install_proc.stdout
            or b""
        ).decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise RuntimeError(
            "VRO-NC: scrittura tramite container "
            f"fallita: {detail}"
        )

    installed_hash = sha256(
        target
    )

    if installed_hash != expected_hash:
        log(
            "VRO-NC: verifica fallita; "
            "ripristino backup..."
        )

        rollback = subprocess.run(
            [
                "podman",
                "exec",
                CONTAINER,
                "sh",
                "-c",
                'cp -a "$1" "$2"',
                "sh",
                backup_container,
                VRO_CONTAINER_TARGET,
            ],
            capture_output=True,
            text=True,
        )

        if rollback.returncode != 0:
            raise RuntimeError(
                "VRO-NC: verifica fallita E rollback fallito: "
                f"{(rollback.stderr or rollback.stdout).strip()}"
            )

        raise RuntimeError(
            "VRO-NC: verifica SHA256 post-install fallita; "
            "backup ripristinato. "
            f"Atteso={expected_hash} "
            f"Trovato={installed_hash}"
        )

    # --------------------------------------------------------
    # Mantieni solo gli ultimi N backup
    # --------------------------------------------------------

    cleanup = subprocess.run(
        [
            "podman",
            "exec",
            CONTAINER,
            "sh",
            "-c",
            (
                'ls -1t "$1".pz-local-fix.*.bak 2>/dev/null '
                '| tail -n +"$2" '
                '| xargs -r rm -f --'
            ),
            "sh",
            VRO_CONTAINER_TARGET,
            str(VRO_BACKUP_KEEP + 1),
        ],
        capture_output=True,
        text=True,
    )

    if cleanup.returncode != 0:
        log(
            "ATTENZIONE VRO-NC: "
            "cleanup backup non riuscito: "
            f"{(cleanup.stderr or cleanup.stdout).strip()}"
        )

    log(
        "VRO-NC: integrazione incrementale applicata. "
        f"SHA256={installed_hash}. "
        f"Backup={backup_container}"
    )

    return True

FIX = {
    "name": 'VRO Nearby Containers',
    "run": run,
}
