#!/usr/bin/env python3
"""Create safe Linux case-only aliases for active Workshop mod paths."""
import os
import re
from pathlib import Path


MISSING_MARKERS = (
    "missing",
    "not found",
    "does not exist",
    "no such file",
    "cannot open",
    "can't open",
    "failed to open",
)
QUOTED_PATH = re.compile(r"[\"'](?P<path>(?:[A-Za-z]:)?/[^\"'\r\n]+)[\"']")
UNQUOTED_PATH = re.compile(r"(?P<path>(?:[A-Za-z]:)?/[^\s\"'<>]+)")
PREVENTIVE_DIRECTORY_ALIASES = (
    ("AnimSets", "animsets"),
    ("ActionGroups", "actiongroups"),
)


def missing_paths(log_path):
    """Extract absolute paths from log lines which report a missing resource.

    Active Workshop/mod-tree validation is intentionally deferred to
    ``relative_to_workshop`` and ``resolve_case_only_path``.  That allows
    log-driven repair of any case-only mismatch without treating log text as
    authority to modify paths outside an active Workshop mod.
    """
    paths = []

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        lowered = line.casefold()
        if not any(marker in lowered for marker in MISSING_MARKERS):
            continue

        for pattern in (QUOTED_PATH, UNQUOTED_PATH):
            for match in pattern.finditer(line):
                path_text = match.group("path").rstrip(".,;:)]}")
                if Path(path_text).is_absolute() and path_text not in paths:
                    paths.append(path_text)

    return paths


def relative_to_workshop(path_text, workshop, active_workshop_ids):
    """Validate an absolute log path and return its active Workshop suffix."""
    raw = Path(path_text)
    if not raw.is_absolute():
        return None

    raw_parts = raw.parts
    root_parts = workshop.parts
    if len(raw_parts) <= len(root_parts):
        return None
    if tuple(part.casefold() for part in raw_parts[:len(root_parts)]) != tuple(
        part.casefold() for part in root_parts
    ):
        return None

    suffix = raw_parts[len(root_parts):]
    if len(suffix) < 3 or suffix[0] not in active_workshop_ids:
        return None
    if suffix[1].casefold() != "mods":
        return None

    return suffix


def case_only_matches(directory, requested_name):
    """Return direct children whose names differ from requested_name only by case."""
    if not directory.is_dir():
        return []

    folded = requested_name.casefold()
    return [
        child
        for child in directory.iterdir()
        if child.name != requested_name and child.name.casefold() == folded
    ]


def ensure_case_alias(source, destination):
    """Safely create one relative alias, never taking over existing content."""
    if destination.is_symlink():
        try:
            if destination.samefile(source):
                return "present"
        except OSError:
            pass
        return "unexpected"

    if destination.exists():
        return "blocked"

    if not source.exists() or not destination.parent.is_dir():
        return "unfixable"

    link_target = os.path.relpath(
        source.resolve(),
        start=destination.parent.resolve(),
    )
    destination.symlink_to(link_target, target_is_directory=source.is_dir())
    return "created"


def active_media_roots(workshop, active_workshop_ids):
    """Yield media directories belonging to active Workshop items only."""
    for workshop_id in active_workshop_ids:
        mods_root = workshop / workshop_id / "mods"
        if not mods_root.is_dir():
            continue

        for media_root in mods_root.rglob("media"):
            if media_root.is_dir():
                yield media_root


def create_animsets_descendant_aliases(animsets, log):
    """Alias mixed-case AnimSets children without traversing symlink aliases."""
    changed = False
    directories = [animsets]

    while directories:
        directory = directories.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            log(f"Linux case aliases: unable to inspect {directory}: {exc}")
            continue

        for source in children:
            # Traversal is limited to original directory entries. This prevents
            # an alias from becoming another traversal root on later runs.
            if source.is_symlink():
                continue

            if source.is_dir():
                directories.append(source)
            elif not source.is_file():
                continue

            lowercase_name = source.name.lower()
            if lowercase_name == source.name:
                continue

            destination = source.with_name(lowercase_name)
            result = ensure_case_alias(source, destination)
            if result == "created":
                log(
                    "Linux case aliases: created AnimSets descendant alias "
                    f"{destination} -> {source.name}."
                )
                changed = True
            elif result in ("blocked", "unexpected", "unfixable"):
                log(
                    "Linux case aliases: "
                    f"{result}; leaving untouched: {destination}"
                )

    return changed


def create_preventive_directory_aliases(ctx):
    """Add only unambiguous B42 directory aliases before a server can log one."""
    log = ctx["log"]
    changed = False

    for media_root in active_media_roots(
        ctx["WORKSHOP"],
        ctx["active_workshop_ids"],
    ):
        for source_name, destination_name in PREVENTIVE_DIRECTORY_ALIASES:
            source = media_root / source_name
            destination = media_root / destination_name
            if not source.is_dir():
                continue

            result = ensure_case_alias(source, destination)
            if result == "created":
                log(
                    "Linux case aliases: created preventive directory alias "
                    f"{destination} -> {source_name}."
                )
                changed = True
            elif result in ("blocked", "unexpected"):
                log(
                    "Linux case aliases: "
                    f"{result}; leaving untouched: {destination}"
                )

            if source_name == "AnimSets":
                if create_animsets_descendant_aliases(source, log):
                    changed = True

    return changed


def resolve_case_only_path(path_text, workshop, active_workshop_ids):
    """Find a single case-only path through an active Workshop mod tree."""
    suffix = relative_to_workshop(path_text, workshop, active_workshop_ids)
    if suffix is None:
        return "outside_active_tree", []

    current = workshop
    aliases = []
    for index, requested_name in enumerate(suffix):
        exact = current / requested_name
        if exact.exists() or exact.is_symlink():
            current = exact
            continue

        matches = case_only_matches(current, requested_name)
        if len(matches) != 1:
            return ("ambiguous" if matches else "unfixable"), []

        source = matches[0]
        is_leaf = index == len(suffix) - 1
        if not is_leaf and not source.is_dir():
            return "unfixable", []
        if is_leaf and Path(requested_name).suffix and not source.is_file():
            return "unfixable", []

        aliases.append((source, exact))
        current = source

    return "resolved", aliases


def run(ctx):
    log = ctx["log"]
    changed = create_preventive_directory_aliases(ctx)
    log_path = ctx["latest_pz_server_log"]()
    if log_path is None:
        log("Linux case aliases: no persisted PZ server startup log found; file repair skipped.")
        return changed

    candidates = missing_paths(log_path)
    if not candidates:
        log(f"Linux case aliases: no relevant missing paths in {log_path}; skip.")
        return changed

    for path_text in candidates:
        status, aliases = resolve_case_only_path(
            path_text,
            ctx["WORKSHOP"],
            ctx["active_workshop_ids"],
        )
        if status != "resolved":
            log(f"Linux case aliases: {status}; leaving untouched: {path_text}")
            continue

        for source, destination in aliases:
            result = ensure_case_alias(source, destination)
            if result == "created":
                log(f"Linux case aliases: created {destination} -> {source.name}.")
                changed = True
            elif result in ("blocked", "unexpected", "unfixable"):
                log(
                    "Linux case aliases: "
                    f"{result}; leaving untouched: {destination}"
                )

    return changed


FIX = {
    "name": "B42 Linux preventive and log-driven case aliases",
    "run": run,
}
