#!/usr/bin/env python3
"""Known case-only AnimSets aliases required by EBF Chainsaw on Linux."""
WORKSHOP_ID = "3714025041"
MOD_NAME = "ebfchainsaw"
ALIASES = (
    ("ext/Ext01.xml", "ext/ext01.xml"),
    ("ext/Ext02.xml", "ext/ext02.xml"),
    ("ext/Ext03.xml", "ext/ext03.xml"),
    ("melee/2handed/ChainsawDefault.xml", "melee/2handed/chainsawdefault.xml"),
)


def run(ctx):
    root = ctx["WORKSHOP"] / WORKSHOP_ID / "mods" / MOD_NAME / "42.20" / "media" / "animsets" / "player"
    log = ctx["log"]
    ensure_symlink = ctx["ensure_symlink"]
    if not root.is_dir():
        log("EBF Chainsaw: 42.20 AnimSets tree not present; skipped.")
        return False
    changed = False
    for source_rel, destination_rel in ALIASES:
        source, destination = root / source_rel, root / destination_rel
        if not source.is_file():
            log(f"EBF Chainsaw: blocked; source missing: {source}")
            continue
        result = ensure_symlink(
            source,
            destination,
            source.name,
        )
        if result == "present":
            log(f"EBF Chainsaw: {destination.name} already fixed.")
        elif result == "created":
            log(f"EBF Chainsaw: created lowercase alias {destination.name}.")
            changed = True
        elif result == "replaced":
            log(f"EBF Chainsaw: repaired lowercase alias {destination.name}.")
            changed = True
        elif result == "blocked":
            log(f"EBF Chainsaw: upstream lowercase destination exists; skipped: {destination}")
        else:
            log(f"EBF Chainsaw: blocked; source missing: {source}")
    return changed


FIX = {"name": "EBF Chainsaw Linux case aliases", "run": run}
