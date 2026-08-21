#!/usr/bin/env python3


WORKSHOP_ID = "3740052292"
MOD_NAME = "CompanionDogs"


def log_alias_result(log, alias, destination, result):
    if result == "created":
        log(f"CompanionDogs: creato alias {alias}.")
    elif result == "replaced":
        log(f"CompanionDogs: alias {alias} ripristinato.")
    elif result == "present":
        log(f"CompanionDogs: alias {alias} già presente; skip.")
    elif result == "blocked":
        log(
            "CompanionDogs: destinazione "
            f"{destination} esiste e non è un symlink; "
            "NON sovrascrivo."
        )
    else:
        log(f"CompanionDogs: sorgente alias {alias} non presente; skip.")


def run(ctx):
    workshop = ctx["WORKSHOP"]
    log = ctx["log"]
    ensure_symlink = ctx["ensure_symlink"]

    mod_root = workshop / WORKSHOP_ID / "mods" / MOD_NAME / "42"
    animsets = mod_root / "media" / "AnimSets"

    if not animsets.is_dir():
        log("CompanionDogs: AnimSets non presente; skip.")
        return False

    changed = False

    lowercase_animsets = (
        workshop
        / WORKSHOP_ID
        / "mods"
        / MOD_NAME.lower()
        / "42"
        / "media"
        / "animsets"
    )

    result = ensure_symlink(
        animsets,
        lowercase_animsets,
        "../../../CompanionDogs/42/media/AnimSets",
    )
    log_alias_result(
        log,
        "lowercase AnimSets",
        lowercase_animsets,
        result,
    )
    changed = result in ("created", "replaced")

    default_pathfind = (
        animsets
        / "raccoon"
        / "pathfind"
        / "defaultPathfind.xml"
    )
    lowercase_default_pathfind = (
        default_pathfind.parent
        / "defaultpathfind.xml"
    )

    result = ensure_symlink(
        default_pathfind,
        lowercase_default_pathfind,
        default_pathfind.name,
    )
    log_alias_result(
        log,
        "defaultpathfind.xml",
        lowercase_default_pathfind,
        result,
    )

    return changed or result in ("created", "replaced")


FIX = {
    "name": "Companion Dogs B42 AnimSets case aliases",
    "run": run,
}
