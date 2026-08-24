#!/usr/bin/env python3
import re


WORKSHOP_ID = "3610677934"
MOD_DIRECTORY = "Hot_Brass_Visible_Casing_Ejection_Framework"


def version_rank(path):
    """Match the generator's B42 preference for a mod version directory."""
    if path.name == "42.20":
        return (0, path.name)
    if path.name == "42":
        return (1, path.name)
    if re.fullmatch(r"42(?:\.\d+)+", path.name):
        return (3, path.name)
    return (4, path.name)


def select_active_b42_tree(mod_root):
    """Return one B42 tree with AnimSets, never patching obsolete versions."""
    candidates = []
    if (mod_root / "media" / "AnimSets").is_dir():
        candidates.append(((4, ""), mod_root))

    for path in mod_root.iterdir():
        if path.is_dir() and (path / "media" / "AnimSets").is_dir():
            rank = version_rank(path)
            if rank[0] < 4:
                candidates.append((rank, path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def ensure_alias(source, destination, link_target):
    """Create a verified symlink without replacing upstream objects."""
    if not source.exists():
        return "source_missing"

    if destination.is_symlink():
        try:
            if destination.samefile(source):
                return "present"
        except OSError:
            pass
        return "unexpected"

    if destination.exists():
        return "blocked"

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(link_target, target_is_directory=source.is_dir())
    return "created"


def log_unmanaged_alias(log, label, path, result):
    if result == "blocked":
        log(f"HotBrass: upstream lowercase {label} exists; leaving untouched: {path}")
    elif result == "unexpected":
        log(f"HotBrass: unexpected symlink target; not replacing: {path}")


def run(ctx):
    workshop = ctx["WORKSHOP"]
    log = ctx["log"]
    mods_root = workshop / WORKSHOP_ID / "mods"
    mod_root = mods_root / MOD_DIRECTORY

    if not mod_root.is_dir():
        log("HotBrass: mod not present; skip.")
        return False

    active_tree = select_active_b42_tree(mod_root)
    if active_tree is None:
        log("HotBrass: no compatible B42 AnimSets tree found; skip.")
        return False

    changed = False
    lowercase_mod_root = mods_root / MOD_DIRECTORY.lower()
    result = ensure_alias(mod_root, lowercase_mod_root, MOD_DIRECTORY)
    if result == "created":
        log("HotBrass: created lowercase mod-root alias.")
        changed = True
    else:
        log_unmanaged_alias(log, "mod-root path", lowercase_mod_root, result)

    animsets = active_tree / "media" / "AnimSets"
    lowercase_animsets = active_tree / "media" / "animsets"
    result = ensure_alias(animsets, lowercase_animsets, "AnimSets")
    if result == "created":
        log("HotBrass: created lowercase AnimSets alias.")
        changed = True
    else:
        log_unmanaged_alias(log, "AnimSets path", lowercase_animsets, result)

    # AnimNode.Parse lowercases extends lookups such as
    # .../media/animsets/player/actions/rackshotgunsemi_hb.xml on Linux.
    created_xml_aliases = 0
    for xml_file in animsets.rglob("*"):
        if not xml_file.is_file() or xml_file.suffix.lower() != ".xml":
            continue

        lowercase_name = xml_file.name.lower()
        if lowercase_name == xml_file.name:
            continue

        result = ensure_alias(xml_file, xml_file.with_name(lowercase_name), xml_file.name)
        if result == "created":
            created_xml_aliases += 1
            changed = True
        elif result in ("blocked", "unexpected"):
            log_unmanaged_alias(log, "XML file", xml_file.with_name(lowercase_name), result)

    if created_xml_aliases:
        log(f"HotBrass: created {created_xml_aliases} lowercase XML aliases.")

    return changed


FIX = {
    "name": "Hot Brass B42 Linux filesystem case aliases",
    "run": run,
}
