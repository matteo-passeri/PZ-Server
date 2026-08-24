#!/usr/bin/env python3
from pathlib import Path
import hashlib
import shutil
import subprocess
from datetime import datetime

def run(ctx):
    WORKSHOP = ctx['WORKSHOP']
    log = ctx['log']

    changed = False

    workshop_ids = (
        "3496263414",  # WeldingRodMod
        "3409705897",  # Craft Plaster
    )

    old = "Base.CrushedLimestone"
    new = "Base.LimestoneCrushed"

    for workshop_id in workshop_ids:
        root = (
            WORKSHOP
            / workshop_id
        )

        if not root.is_dir():
            log(
                f"Limestone: Workshop {workshop_id} "
                "not present; skip."
            )
            continue

        script_dirs = list(
            root.glob(
                "mods/*/*/media/scripts"
            )
        )

        script_dirs += list(
            root.glob(
                "mods/*/media/scripts"
            )
        )

        seen = set()

        for script_dir in script_dirs:
            try:
                resolved = (
                    script_dir.resolve()
                )
            except OSError:
                continue

            if resolved in seen:
                continue

            seen.add(resolved)

            if not script_dir.is_dir():
                continue

            for path in script_dir.rglob(
                "*.txt"
            ):
                try:
                    text = path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError:
                    continue

                if old not in text:
                    continue

                backup = path.with_suffix(
                    path.suffix
                    + ".pz-local-fix.bak"
                )

                if not backup.exists():
                    shutil.copy2(
                        path,
                        backup,
                    )

                count = text.count(old)

                path.write_text(
                    text.replace(
                        old,
                        new,
                    ),
                    encoding="utf-8",
                )

                log(
                    "Limestone: corrected "
                    f"{path} "
                    f"({count} occurrences)."
                )

                changed = True

    return changed

FIX = {
    "name": 'Limestone aliases',
    "run": run,
}
