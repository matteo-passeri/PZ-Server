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
        log("CarRoofFix: AnimSets not present; skip.")
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
        log("CarRoofFix: created lowercase AnimSets alias.")
    elif result == "replaced":
        log("CarRoofFix: restored lowercase AnimSets alias.")
    elif result == "present":
        log("CarRoofFix: lowercase AnimSets alias already present; skip.")
    elif result == "blocked":
        log(
            "CarRoofFix: destination "
            f"{lowercase_animsets} exists and is not a symlink; "
            "NOT overwriting."
        )
    else:
        log("CarRoofFix: lowercase AnimSets source not present; skip.")

    return result in ("created", "replaced")


FIX = {
    "name": "CarRoofFix B42 AnimSets case alias",
    "run": run,
}
