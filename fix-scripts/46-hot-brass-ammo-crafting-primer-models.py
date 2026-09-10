#!/usr/bin/env python3
"""Repair the narrowly scoped Hot Brass Ammo Crafting primer model references."""
import os
from pathlib import Path
import re
import tempfile


WORKSHOP_ID = "3610677934"
MOD_ID = "HBAmmoCraft"
MOD_DIRECTORY = "Hot_Brass_Ammo_Crafting"
MODELS_RELATIVE = Path("42.19/media/scripts/models/SpentCasingPhysicsAmmoCraft/Ingredients.txt")
ITEMS_RELATIVE = Path("42.19/media/scripts/items/SpentCasingPhysicsAmmoCraft/Ingredients.txt")
PRIMERS = ("Primer_Rifle", "Primer_Pistol", "Primer_Shotshell")


class UpstreamChangedError(RuntimeError):
    """The supported Hot Brass source layout no longer matches."""


def rewrite_atomically(path, data):
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
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
    """Resolve one physical mod tree, tolerating a case-only Linux alias."""
    mods_root = workshop / WORKSHOP_ID / "mods"
    if not mods_root.is_dir():
        return None
    matches = [
        child for child in mods_root.iterdir()
        if child.is_dir() and child.name.casefold() == MOD_DIRECTORY.casefold()
    ]
    physical = []
    for match in matches:
        try:
            resolved = match.resolve(strict=True)
        except OSError:
            continue
        if resolved not in physical:
            physical.append(resolved)
    return physical[0] if len(physical) == 1 else None


def item_block(text, item_name):
    header = re.compile(
        rf"(?m)^[ \t]*item[ \t]+{re.escape(item_name)}[ \t]*\{{"
    )
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise UpstreamChangedError(f"{item_name}: expected one item block; found {len(matches)}")
    opener = matches[0].end() - 1
    depth = 0
    for index in range(opener, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return matches[0].start(), index + 1
    raise UpstreamChangedError(f"{item_name}: item block has no closing brace")


def declared_primer_models(text):
    module = re.search(r"(?ms)^[ \t]*module[ \t]+HBAC[ \t]*\{(?P<body>.*?)(?=^[ \t]*module[ \t]+|\Z)", text)
    if module is None:
        return False
    return all(re.search(rf"(?m)^[ \t]*model[ \t]+{re.escape(primer)}\b", module.group("body")) for primer in PRIMERS)


def plan_fix(items_text, models_text):
    if not declared_primer_models(models_text):
        raise UpstreamChangedError("module HBAC does not declare all primer models")

    replacements = []
    statuses = []
    for primer in PRIMERS:
        start, end = item_block(items_text, primer)
        block = items_text[start:end]
        values = {}
        for field in ("StaticModel", "WorldStaticModel"):
            matches = list(re.finditer(
                rf"(?m)^[ \t]*{field}[ \t]*=[ \t]*(?P<value>[^,\r\n]+)[ \t]*,", block,
            ))
            if len(matches) != 1:
                raise UpstreamChangedError(f"{primer}: expected one {field} field; found {len(matches)}")
            values[field] = matches[0]
        bad = f"HBVCEF.{primer}"
        good = f"HBAC.{primer}"
        field_values = {field: match.group("value").strip() for field, match in values.items()}
        if set(field_values.values()) == {bad}:
            replacements.extend((start + match.start("value"), start + match.end("value"), good) for match in values.values())
            statuses.append("bad")
        elif set(field_values.values()) == {good}:
            statuses.append("good")
        else:
            raise UpstreamChangedError(
                f"{primer}: expected both model fields to be {bad!r} or {good!r}; found {field_values}"
            )

    if all(status == "good" for status in statuses):
        return items_text, "ALREADY PATCHED"
    if not all(status == "bad" for status in statuses):
        raise UpstreamChangedError("primer blocks are mixed between known bad and known good states")
    for start, end, value in reversed(replacements):
        items_text = items_text[:start] + value + items_text[end:]
    return items_text, "PATCHED 6 FIELDS"


def run(ctx):
    log = ctx["log"]
    active_workshop_ids = ctx.get("active_workshop_ids", ())
    active_mod_ids = ctx.get("active_mod_ids", ())
    if active_workshop_ids and WORKSHOP_ID not in active_workshop_ids:
        log("Hot Brass Ammo Crafting primers: Workshop 3610677934 is not active; skip.")
        return False
    if active_mod_ids and MOD_ID not in active_mod_ids:
        log("Hot Brass Ammo Crafting primers: Mod HBAmmoCraft is not active; skip.")
        return False
    mod_root = resolve_mod_root(ctx["WORKSHOP"])
    if mod_root is None:
        log("Hot Brass Ammo Crafting primers: SKIPPED / TARGET NOT INSTALLED.")
        return False
    models_path = mod_root / MODELS_RELATIVE
    items_path = mod_root / ITEMS_RELATIVE
    if not models_path.is_file() or not items_path.is_file():
        log("Hot Brass Ammo Crafting primers: SKIPPED / TARGET NOT INSTALLED.")
        return False
    try:
        models_text = models_path.read_text(encoding="utf-8", errors="strict")
        items_data = items_path.read_bytes()
        items_text = items_data.decode("utf-8", errors="strict")
        updated, status = plan_fix(items_text, models_text)
    except (UnicodeError, UpstreamChangedError) as exc:
        log(f"Hot Brass Ammo Crafting primers: SKIPPED / UPSTREAM CHANGED ({exc}).")
        return False
    if updated == items_text:
        log(f"Hot Brass Ammo Crafting primers: {status}.")
        return False
    rewrite_atomically(items_path, updated.encode("utf-8"))
    log("Hot Brass Ammo Crafting primers: patched six model fields.")
    return True


FIX = {"name": "Hot Brass Ammo Crafting B42 primer models", "run": run}
