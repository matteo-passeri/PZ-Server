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
            "CompanionDogs: mod not present; skip."
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
                f"{filename} no longer exists "
                "in the client. Patch not applied."
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

        # No destination: Workshop likely removed our file during the update.
        # Recreate it.
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
                "CompanionDogs: created shared copy "
                f"{filename}."
            )

            changed = True
            continue

        dst_hash = sha256(dst)

        # We have never recorded this file as ours.
        #
        # Leave it untouched: it could be a future official implementation
        # from the author.
        if previous is None:
            if dst_hash == src_hash:
                # This is very likely the copy we created before introducing
                # this patcher.
                managed[key] = {
                    "sha256": dst_hash,
                    "source_sha256":
                        src_hash,
                }

                log(
                    "CompanionDogs: "
                    f"{filename} already present "
                    "and identical to the client; "
                    "adopted as a managed file."
                )

            else:
                log(
                    "CompanionDogs: "
                    f"{filename} already exists in shared "
                    "but is not managed by the patcher. "
                    "Assuming an upstream fix; NOT overwriting."
                )

            continue

        previous_hash = previous.get(
            "sha256"
        )

        # The shared file changed from the one we wrote.
        #
        # It could be an official update: stop managing it immediately.
        if (
            previous_hash
            and dst_hash != previous_hash
        ):
            log(
                "CompanionDogs: "
                f"{filename} shared was modified "
                "by something external. "
                "Assuming an upstream implementation; "
                "stopping management."
            )

            managed.pop(
                key,
                None,
            )

            continue

        # The client source has not changed: nothing to do.
        if dst_hash == src_hash:
            managed[key] = {
                "sha256": dst_hash,
                "source_sha256":
                    src_hash,
            }

            continue

        # The file is still clearly ours, but the client was updated.
        # Update the shared copy as well.
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
            f"{filename} client updated; "
            "shared copy synchronized."
        )

        changed = True

    return changed

FIX = {
    "name": 'Companion Dogs B42 shared TimedActions',
    "run": run,
}
