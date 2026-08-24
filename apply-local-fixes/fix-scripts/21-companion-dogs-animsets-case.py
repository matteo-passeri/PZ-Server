#!/usr/bin/env python3


WORKSHOP_ID = "3740052292"
MOD_NAME = "CompanionDogs"


def ensure_targeted_alias(log, source, destination, link_target, label):
    """Create one known lowercase alias without taking over upstream paths."""
    if not source.exists():
        return "source_missing"

    if destination.is_symlink():
        try:
            if (
                destination.readlink() == link_target
                and destination.samefile(source)
            ):
                return "present"
        except OSError:
            pass

        log(
            f"CompanionDogs: lowercase {label} alias points to an "
            "unexpected target; NOT replacing it."
        )
        return "unexpected"

    if destination.exists():
        log(
            f"CompanionDogs: lowercase {label} path exists as a real "
            "file or directory; not touching it."
        )
        return "blocked"

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(link_target, target_is_directory=source.is_dir())
    log(f"CompanionDogs: created lowercase {label} alias.")
    return "created"


def run(ctx):
    workshop = ctx["WORKSHOP"]
    log = ctx["log"]

    mod_root = workshop / WORKSHOP_ID / "mods" / MOD_NAME / "42"
    media_root = mod_root / "media"

    if not media_root.is_dir():
        log("CompanionDogs: mod not present; skip.")
        return False

    lowercase_media_root = (
        workshop / WORKSHOP_ID / "mods" / MOD_NAME.lower() / "42" / "media"
    )
    aliases = (
        ("lua", media_root / "lua", "lua"),
        ("animsets", media_root / "AnimSets", "AnimSets"),
        ("scripts", media_root / "scripts", "scripts"),
        ("models_X", media_root / "models_X", "models_X"),
    )

    changed = False
    for label, source, source_name in aliases:
        result = ensure_targeted_alias(
            log,
            source,
            lowercase_media_root / label,
            f"../../../{MOD_NAME}/42/media/{source_name}",
            label,
        )
        changed = changed or result == "created"

    default_pathfind = (
        media_root / "AnimSets" / "raccoon" / "pathfind" / "defaultPathfind.xml"
    )
    result = ensure_targeted_alias(
        log,
        default_pathfind,
        default_pathfind.parent / "defaultpathfind.xml",
        "defaultPathfind.xml",
        "defaultpathfind.xml",
    )

    return changed or result == "created"


FIX = {
    "name": "Companion Dogs B42 targeted lowercase compatibility aliases",
    "run": run,
}
