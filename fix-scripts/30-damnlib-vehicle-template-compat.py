#!/usr/bin/env python3
"""Recover only safe older damnlib placeholder templates for B42.20."""
import re
from _vehicle_compat import TEMPLATE_RE, add_compatibility_templates, named_blocks, template_locations, tree

WORKSHOP_ID = "3171167894"
MOD_NAME = "damnlib"
ACTIVE_VERSION = "42.20"
REFERENCE_RE = re.compile(r"\btemplate\s*=\s*(DAMN[A-Za-z0-9_]+)\b")


def safe_empty_template(block):
    """A compatibility placeholder must have no nested part definitions."""
    return "part " not in block and "part\t" not in block


def run(ctx):
    root = ctx["WORKSHOP"] / WORKSHOP_ID / "mods" / MOD_NAME
    active = tree(ctx["WORKSHOP"], WORKSHOP_ID, MOD_NAME, ACTIVE_VERSION)
    log = ctx["log"]
    if not active.is_dir():
        log("damnlib: 42.20 tree not present; skipped.")
        return False
    upstream = template_locations(active)
    wanted = {}
    references = set()
    for workshop_id in ctx["active_workshop_ids"]:
        for path in (ctx["WORKSHOP"] / workshop_id / "mods").glob("*/42.13/media/scripts/**/*.txt"):
            references.update(REFERENCE_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    if not references:
        log("damnlib: no active DAMN template references found; skipped.")
        return False
    # Older trees are sources only. Never replace their files or import
    # nonempty vehicle definitions as placeholders.
    for version in (".", "legacy", "42.0", "42.13", "42.17", "42"):
        old_tree = root / version
        if not old_tree.is_dir():
            continue
        for path in sorted((old_tree / "media" / "scripts").rglob("*.txt")):
            try:
                blocks = named_blocks(path.read_text(encoding="utf-8", errors="replace"), TEMPLATE_RE)
            except ValueError:
                log(f"damnlib: blocked; unbalanced source structure: {path}")
                continue
            for name, block in blocks.items():
                if (
                    name in references
                    and name not in upstream
                    and name not in wanted
                    and safe_empty_template(block)
                ):
                    wanted[name] = block
    target = active / "media/scripts/commonItems/ZZ_DAMN_42_20_Compatibility.txt"
    if not wanted:
        log("damnlib: no safe older compatibility templates needed; already fixed or upstream changed.")
        return False
    return add_compatibility_templates(target, wanted, upstream, log, "damnlib")


FIX = {"name": "damnlib B42.20 safe vehicle template compatibility", "run": run}
