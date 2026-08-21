#!/usr/bin/env python3


WORKSHOP_ID = "3781616141"
MOD_NAME = "CarRoofFix"


def run(ctx):
    workshop = ctx["WORKSHOP"]
    log = ctx["log"]
    ensure_symlink = ctx["ensure_symlink"]

    mod_root = workshop / WORKSHOP_ID / "mods" / MOD_NAME / "42"
    animsets = mod_root / "media" / "AnimSets"

    if not animsets.is_dir():
        log("CarRoofFix: AnimSets non presente; skip.")
        return False

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
        "../../../CarRoofFix/42/media/AnimSets",
    )

    if result == "created":
        log("CarRoofFix: creato alias lowercase AnimSets.")
    elif result == "replaced":
        log("CarRoofFix: alias lowercase AnimSets ripristinato.")
    elif result == "present":
        log("CarRoofFix: alias lowercase AnimSets già presente; skip.")
    elif result == "blocked":
        log(
            "CarRoofFix: destinazione "
            f"{lowercase_animsets} esiste e non è un symlink; "
            "NON sovrascrivo."
        )
    else:
        log("CarRoofFix: sorgente lowercase AnimSets non presente; skip.")

    return result in ("created", "replaced")


FIX = {
    "name": "CarRoofFix B42 AnimSets case alias",
    "run": run,
}
