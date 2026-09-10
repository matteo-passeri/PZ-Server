#!/usr/bin/env python3
"""Repair the known B42.20 Bicycle plastic-bag world model reference."""
import os
from pathlib import Path
import re
import tempfile


WORKSHOP_ID = "3461415167"
MOD_ID = "BicycleMod"
MOD_DIRECTORY = "Bicycle"
SCRIPT_RELATIVE = Path("42.20/media/scripts/Bicycle_item.txt")
BAD_VALUE = "Plasticbag"
GOOD_VALUE = "PlasticBag_Ground"
EXPECTED_FIELDS = 2


class UpstreamChangedError(RuntimeError):
    """The supported Bicycle source layout no longer matches."""


def rewrite_atomically(path, data):
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = None
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def resolve_mod_root(workshop):
    mods_root = workshop / WORKSHOP_ID / "mods"
    if not mods_root.is_dir():
        return None
    physical = []
    for child in mods_root.iterdir():
        if not child.is_dir() or child.name.casefold() != MOD_DIRECTORY.casefold():
            continue
        try:
            resolved = child.resolve(strict=True)
        except OSError:
            continue
        if resolved not in physical:
            physical.append(resolved)
    return physical[0] if len(physical) == 1 else None


def item_blocks(text):
    """Yield syntactic item blocks so comments and unrelated text are excluded."""
    header = re.compile(r"(?m)^[ \t]*item[ \t]+[^\s{]+[ \t]*(?:\r?\n|$)")
    for match in header.finditer(text):
        opener = text.find("{", match.end())
        if opener == -1:
            raise UpstreamChangedError("item block has no opening brace")
        depth = 0
        for index in range(opener, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield match.start(), index + 1
                    break
        else:
            raise UpstreamChangedError("item block has no closing brace")


def plan_fix(text):
    fields = []
    for start, end in item_blocks(text):
        block = text[start:end]
        fields.extend((start + field.start("value"), start + field.end("value"), field.group("value"))
                      for field in re.finditer(
                          r"(?m)^[ \t]*WorldStaticModel[ \t]*=[ \t]*"
                          r"(?P<value>Plasticbag|PlasticBag_Ground)[ \t]*,",
                          block,
                      ))
    if len(fields) != EXPECTED_FIELDS:
        raise UpstreamChangedError(f"expected {EXPECTED_FIELDS} Bicycle WorldStaticModel fields; found {len(fields)}")
    values = [value for _, _, value in fields]
    if all(value == GOOD_VALUE for value in values):
        return text, "ALREADY PATCHED"
    if not all(value == BAD_VALUE for value in values):
        raise UpstreamChangedError(f"expected all fields to be {BAD_VALUE!r} or {GOOD_VALUE!r}; found {values}")
    for start, end, _ in reversed(fields):
        text = text[:start] + GOOD_VALUE + text[end:]
    return text, "PATCHED 2 FIELDS"


def run(ctx):
    log = ctx["log"]
    active_workshop_ids = ctx.get("active_workshop_ids", ())
    active_mod_ids = ctx.get("active_mod_ids", ())
    if active_workshop_ids and WORKSHOP_ID not in active_workshop_ids:
        log("Bicycle plastic-bag model: Workshop 3461415167 is not active; skip.")
        return False
    if active_mod_ids and MOD_ID not in active_mod_ids:
        log("Bicycle plastic-bag model: Mod BicycleMod is not active; skip.")
        return False
    mod_root = resolve_mod_root(ctx["WORKSHOP"])
    if mod_root is None:
        log("Bicycle plastic-bag model: SKIPPED / TARGET NOT INSTALLED.")
        return False
    script_path = mod_root / SCRIPT_RELATIVE
    if not script_path.is_file():
        log("Bicycle plastic-bag model: SKIPPED / TARGET NOT INSTALLED.")
        return False
    try:
        data = script_path.read_bytes()
        text = data.decode("utf-8", errors="strict")
        updated, status = plan_fix(text)
    except (UnicodeError, UpstreamChangedError) as exc:
        log(f"Bicycle plastic-bag model: SKIPPED / UPSTREAM CHANGED ({exc}).")
        return False
    if updated == text:
        log(f"Bicycle plastic-bag model: {status}.")
        return False
    rewrite_atomically(script_path, updated.encode("utf-8"))
    log("Bicycle plastic-bag model: patched two WorldStaticModel fields.")
    return True



FIX = {"name": "Bicycle B42.20 plastic-bag world model", "run": run}
