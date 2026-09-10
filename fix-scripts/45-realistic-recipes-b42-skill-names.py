#!/usr/bin/env python3
"""Repair two Build 42 skill-name regressions in Realistic Recipes."""
import os
from pathlib import Path
import re
import tempfile


WORKSHOP_ID = "3795521454"
MOD_ID = "RealisticRecipes"
MODS_RELATIVE = Path("mods")
SCRIPT_RELATIVE = Path("42/media/scripts/RealisticRecipes/realistic_recipes.txt")

RECIPE_FIXES = (
    ("MakeKitchenTongs", "xpAward", "Metalworking:5", "MetalWelding:5"),
    ("MakeToolbox", "SkillRequired", "Carpentry:1", "Woodwork:1"),
)


class UpstreamChangedError(RuntimeError):
    """The expected recipe block no longer has a recognized skill line."""


def rewrite_atomically(path, data):
    """Replace a validated file without creating a Workshop backup file."""
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
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
    """Resolve the installed mod root across the Linux casing alias variants."""
    mods_root = workshop / WORKSHOP_ID / MODS_RELATIVE
    if not mods_root.is_dir():
        return None

    exact = mods_root / MOD_ID
    if exact.is_dir():
        return exact

    try:
        matches = [
            child for child in mods_root.iterdir()
            if child.is_dir() and child.name.casefold() == MOD_ID.casefold()
        ]
    except OSError:
        return None

    return matches[0] if len(matches) == 1 else None


def recipe_block(text, recipe_name):
    """Return the unique craftRecipe block identified by its recipe name."""
    header = re.compile(
        rf"(?m)^[ \t]*craftRecipe[ \t]+{re.escape(recipe_name)}[ \t]*(?:\r?\n|$)"
    )
    headers = list(header.finditer(text))
    if len(headers) != 1:
        raise UpstreamChangedError(
            f"{recipe_name}: expected exactly one craftRecipe block; found {len(headers)}"
        )

    start = headers[0].start()
    next_header = re.search(r"(?m)^[ \t]*craftRecipe[ \t]+", text[headers[0].end():])
    search_end = headers[0].end() + next_header.start() if next_header else len(text)
    opener = text.find("{", headers[0].end(), search_end)
    if opener == -1:
        raise UpstreamChangedError(f"{recipe_name}: craftRecipe block has no opening brace")

    depth = 0
    for index in range(opener, search_end):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise UpstreamChangedError(f"{recipe_name}: craftRecipe block has no closing brace")


def plan_recipe_fix(text, recipe_name, field, bad_value, good_value):
    """Plan one isolated skill-field repair within one named recipe block."""
    start, end = recipe_block(text, recipe_name)
    block = text[start:end]
    line = re.compile(
        rf"(?m)^[ \t]*{re.escape(field)}[ \t]*=[ \t]*"
        rf"(?P<value>{re.escape(bad_value)}|{re.escape(good_value)})[ \t]*,[ \t]*(?:\r?$)"
    )
    matches = list(line.finditer(block))
    if len(matches) != 1:
        raise UpstreamChangedError(
            f"{recipe_name}: expected exactly one {field} line with {bad_value!r} "
            f"or {good_value!r}; found {len(matches)}"
        )

    match = matches[0]
    if match.group("value") == good_value:
        return text, "ALREADY PATCHED"

    updated_block = block[:match.start("value")] + good_value + block[match.end("value"):]
    return text[:start] + updated_block + text[end:], "CHANGED"


def run(ctx):
    log = ctx["log"]
    active_workshop_ids = ctx.get("active_workshop_ids", ())
    active_mod_ids = ctx.get("active_mod_ids", ())
    if active_workshop_ids and WORKSHOP_ID not in active_workshop_ids:
        log("Realistic Recipes: Workshop 3795521454 is not active; skip.")
        return False
    if active_mod_ids and MOD_ID not in active_mod_ids:
        log("Realistic Recipes: Mod RealisticRecipes is not active; skip.")
        return False

    mod_root = resolve_mod_root(ctx["WORKSHOP"])
    if mod_root is None:
        log("Realistic Recipes: SKIPPED / TARGET NOT INSTALLED.")
        return False
    script_path = mod_root / SCRIPT_RELATIVE
    if not script_path.is_file():
        log("Realistic Recipes: SKIPPED / TARGET NOT INSTALLED.")
        return False

    try:
        data = script_path.read_bytes()
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        log(f"Realistic Recipes: SKIPPED / UPSTREAM CHANGED ({exc}).")
        return False

    changed = False
    for recipe_name, field, bad_value, good_value in RECIPE_FIXES:
        try:
            updated, status = plan_recipe_fix(
                text, recipe_name, field, bad_value, good_value
            )
        except UpstreamChangedError as exc:
            log(f"Realistic Recipes {recipe_name}: SKIPPED / UPSTREAM CHANGED ({exc}).")
            continue

        if status == "CHANGED":
            text = updated
            changed = True
        log(f"Realistic Recipes {recipe_name}: {status}.")

    if changed:
        rewrite_atomically(script_path, text.encode("utf-8"))
    return changed


FIX = {
    "name": "Realistic Recipes B42 skill names",
    "run": run,
}
