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
    state = ctx['state']

    changed = False

    root = (
        WORKSHOP
        / "3740052292"
        / "mods"
        / "CompanionDogs"
        / "42"
        / "media"
        / "lua"
    )

    if not root.is_dir():
        log(
            "CompanionDogs: mod non presente; skip."
        )
        return False

    client_dir = (
        root
        / "client"
        / "TimedActions"
    )

    shared_dir = (
        root
        / "shared"
        / "TimedActions"
    )

    files = (
        "ISCDBaseDogAction.lua",
        "ISCDFeedDog.lua",
        "ISCDPetDog.lua",
        "ISCDWaterDog.lua",
    )

    managed = state[
        "managed_files"
    ]

    for filename in files:
        src = (
            client_dir
            / filename
        )

        dst = (
            shared_dir
            / filename
        )

        key = str(dst)

        if not src.is_file():
            log(
                "CompanionDogs: "
                f"{filename} non esiste più "
                "nel client. Non applico la patch."
            )

            managed.pop(
                key,
                None,
            )

            continue

        src_hash = sha256(src)

        previous = managed.get(
            key
        )

        # Nessuna destinazione:
        # probabilmente Workshop ha rimosso il nostro file
        # durante l'update. Lo ricreiamo.
        if not dst.exists():
            shared_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                src,
                dst,
            )

            new_hash = sha256(dst)

            managed[key] = {
                "sha256": new_hash,
                "source_sha256":
                    src_hash,
            }

            log(
                "CompanionDogs: creata copia shared "
                f"{filename}."
            )

            changed = True
            continue

        dst_hash = sha256(dst)

        # Non abbiamo mai registrato questo file come nostro.
        #
        # Non lo tocchiamo: potrebbe essere una futura
        # implementazione ufficiale dell'autore.
        if previous is None:
            if dst_hash == src_hash:
                # È molto probabilmente la copia che avevamo
                # creato prima di introdurre questo patcher.
                managed[key] = {
                    "sha256": dst_hash,
                    "source_sha256":
                        src_hash,
                }

                log(
                    "CompanionDogs: "
                    f"{filename} già presente "
                    "e identico al client; "
                    "adottato come file gestito."
                )

            else:
                log(
                    "CompanionDogs: "
                    f"{filename} esiste già in shared "
                    "ma non è gestito dal patcher. "
                    "Presumo fix upstream; NON sovrascrivo."
                )

            continue

        previous_hash = previous.get(
            "sha256"
        )

        # Il file shared è cambiato rispetto a quello
        # che avevamo scritto noi.
        #
        # Potrebbe essere un aggiornamento ufficiale:
        # smettiamo immediatamente di gestirlo.
        if (
            previous_hash
            and dst_hash != previous_hash
        ):
            log(
                "CompanionDogs: "
                f"{filename} shared è stato modificato "
                "da qualcosa di esterno. "
                "Presumo implementazione upstream; "
                "smetto di gestirlo."
            )

            managed.pop(
                key,
                None,
            )

            continue

        # La sorgente client non è cambiata:
        # niente da fare.
        if dst_hash == src_hash:
            managed[key] = {
                "sha256": dst_hash,
                "source_sha256":
                    src_hash,
            }

            continue

        # Il file è ancora chiaramente il nostro,
        # ma il client è stato aggiornato.
        # Aggiorniamo anche la copia shared.
        shutil.copy2(
            src,
            dst,
        )

        new_hash = sha256(dst)

        managed[key] = {
            "sha256": new_hash,
            "source_sha256":
                src_hash,
        }

        log(
            "CompanionDogs: "
            f"{filename} client aggiornato; "
            "copia shared sincronizzata."
        )

        changed = True

    return changed

FIX = {
    "name": 'Companion Dogs B42 shared TimedActions',
    "run": run,
}
