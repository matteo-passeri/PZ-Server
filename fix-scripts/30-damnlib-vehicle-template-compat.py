#!/usr/bin/env python3
"""Supply only needed DAMN B42.20 compatibility placeholders."""
import re
from _vehicle_compat import (
    TEMPLATE_RE,
    active_mod_script_files,
    add_compatibility_templates,
    named_blocks,
    template_locations,
    tree,
)

WORKSHOP_ID = "3171167894"
MOD_NAME = "damnlib"
ACTIVE_VERSION = "42.20"
REFERENCE_RE = re.compile(r"\btemplate\s*=\s*(DAMN[A-Za-z0-9_]+)\b")
VERIFIED_PLACEHOLDER_NAMES = frozenset((
    "DAMN76chevyK10mccoy",
    "DAMN76chevyK20brickingIt",
    "DAMN76chevyK20callowayLandscaping",
    "DAMN76chevyK20fossoil",
    "DAMN76chevyK20helton",
    "DAMN76chevyK20kimblesCon",
    "DAMN76chevyK20kyLumber",
    "DAMN76chevyK20marchRidgeCon",
    "DAMN76chevyK20weldingCamille",
    "DAMN76chevyK20yingsWood",
    "DAMN85chevyImpalaPD",
    "DAMN85chevyStepVanBlacksmith",
    "DAMN85chevyStepVanButchers",
    "DAMN85chevyStepVanCitrusWave",
    "DAMN85chevyStepVanDelirosPlonkies",
    "DAMN85chevyStepVanFlorist",
    "DAMN85chevyStepVanGenuine",
    "DAMN85chevyStepVanHerald",
    "DAMN85chevyStepVanJorgensen",
    "DAMN85chevyStepVanLibrary",
    "DAMN85chevyStepVanLvAirportCatering",
    "DAMN85chevyStepVanLvMotorshop",
    "DAMN85chevyStepVanMarineBites",
    "DAMN85chevyStepVanMasonry",
    "DAMN85chevyStepVanMrHuangsLaundry",
    "DAMN85chevyStepVanPostal",
    "DAMN85chevyStepVanPropane",
    "DAMN85chevyStepVanRandys",
    "DAMN85chevyStepVanScarletOak",
    "DAMN85chevyStepVanSeHospitality",
    "DAMN85chevyStepVanSePaintingServices",
    "DAMN85chevyStepVanSmartCut",
    "DAMN85chevyStepVanSunBallz",
    "DAMN85chevyStepVanTheCompleteRepair",
    "DAMN85chevyStepVanTimelessGlass",
    "DAMN85chevyStepVanUsLogistics",
    "DAMN85chevyStepVanZippeeMarket",
))


def safe_empty_template(block):
    """A compatibility placeholder must have no nested part definitions."""
    return "part " not in block and "part\t" not in block


def empty_template(name):
    return f"template vehicle {name}\n{{\n/* */\n}}"


def active_references(workshop, active_workshop_ids, active_mod_ids):
    references = set()
    for path in active_mod_script_files(workshop, active_workshop_ids, active_mod_ids):
        references.update(REFERENCE_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return references


def run(ctx):
    root = ctx["WORKSHOP"] / WORKSHOP_ID / "mods" / MOD_NAME
    active = tree(ctx["WORKSHOP"], WORKSHOP_ID, MOD_NAME, ACTIVE_VERSION)
    log = ctx["log"]
    if not active.is_dir():
        log("damnlib: 42.20 tree not present; skipped.")
        return False
    upstream = template_locations(active)
    wanted = {}
    references = active_references(
        ctx["WORKSHOP"], ctx["active_workshop_ids"], ctx.get("active_mod_ids", ())
    )
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
    for name in references & VERIFIED_PLACEHOLDER_NAMES:
        if name not in upstream and name not in wanted:
            wanted[name] = empty_template(name)
    target = active / "media/scripts/commonItems/ZZ_DAMN_42_20_Compatibility.txt"
    if not wanted:
        log("damnlib: no safe older compatibility templates needed; already fixed or upstream changed.")
        return False
    return add_compatibility_templates(target, wanted, upstream, log, "damnlib")


FIX = {"name": "damnlib B42.20 safe vehicle template compatibility", "run": run}
