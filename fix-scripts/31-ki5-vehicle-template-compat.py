#!/usr/bin/env python3
"""Guarded, source-derived B42 vehicle template compatibility fixes."""
import re
import shutil
from _vehicle_compat import (
    PART_RE, TEMPLATE_RE, add_compatibility_templates, clone_template, named_blocks,
    template_locations, tree,
)


def literal(name, body):
    return f"template vehicle {name}\n{{\n{body}\n}}"


def source_copy(ctx, workshop_id, mod, source_rel, expected, target_name):
    active = tree(ctx["WORKSHOP"], workshop_id, mod, "42.13")
    log = ctx["log"]
    if not active.is_dir():
        log(f"{mod}: 42.13 tree not present; skipped.")
        return False
    upstream = template_locations(active)
    if expected in upstream:
        log(f"{mod}: upstream fixed {expected}; skip.")
        return False
    source = ctx["WORKSHOP"] / workshop_id / "mods" / mod / source_rel
    if not source.is_file():
        log(f"{mod}: blocked; validated legacy source missing: {source}")
        return False
    blocks = named_blocks(source.read_text(encoding="utf-8", errors="replace"), TEMPLATE_RE)
    if expected not in blocks:
        log(f"{mod}: blocked; source does not define {expected}: {source}")
        return False
    destination = active / "media/scripts/vehicles" / target_name
    if destination.exists():
        existing = named_blocks(destination.read_text(encoding="utf-8", errors="replace"), TEMPLATE_RE)
        if expected in existing:
            log(f"{mod}: {expected} already fixed; skip.")
        else:
            log(f"{mod}: blocked; destination exists with unexpected content: {destination}")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    log(f"{mod}: created {destination.name} from validated legacy source.")
    return True


def compatibility(ctx, workshop_id, mod, version, filename, wanted):
    active = tree(ctx["WORKSHOP"], workshop_id, mod, version)
    if not active.is_dir():
        ctx["log"](f"{mod}: {version} tree not present; skipped.")
        return False
    return add_compatibility_templates(
        active / "media/scripts/vehicles" / filename, wanted, template_locations(active), ctx["log"], mod
    )


def cobb(ctx):
    active = tree(ctx["WORKSHOP"], "3722240318", "cobbM540", "42.13")
    if not active.is_dir():
        ctx["log"]("cobbM540: 42.13 tree not present; skipped.")
        return False
    locations = template_locations(active)
    source = locations.get("N540Headlights")
    if source is None:
        ctx["log"]("cobbM540: blocked; B42.13 N540Headlights source not found.")
        return False
    return add_compatibility_templates(
        active / "media/scripts/vehicles/ZZ_M540_Compatibility.txt",
        {"M540Headlights": clone_template(source[1], "N540Headlights", "M540Headlights")},
        locations, ctx["log"], "cobbM540",
    )


def jeep_collision(ctx):
    active = tree(ctx["WORKSHOP"], "3409287192", "84jeepXJ", "42.13")
    log = ctx["log"]
    if not active.is_dir():
        log("84jeepXJ: 42.13 tree not present; skipped.")
        return False
    source = active / "media/scripts/vehicles/template_JP82_spareTires.txt"
    destination = active / "media/scripts/vehicles/ZZ_template_JP84_spareTires.txt"
    upstream = template_locations(active)
    if "JP84SpareTires" in upstream and upstream["JP84SpareTires"][0] != source:
        log("84jeepXJ: upstream renamed/fixed JP84SpareTires; skip.")
        return False
    if not source.is_file() or "JP84SpareTires" not in named_blocks(source.read_text(encoding="utf-8", errors="replace"), TEMPLATE_RE):
        log("84jeepXJ: blocked; collision source no longer defines JP84SpareTires.")
        return False
    if destination.exists():
        log("84jeepXJ: unique JP84SpareTires file already fixed; skip.")
        return False
    shutil.copy2(source, destination)
    log("84jeepXJ: created unique JP84SpareTires script to avoid filename collision.")
    return True


def ford_roofrack(ctx):
    active = tree(ctx["WORKSHOP"], "3073430075", "93fordF350", "42.13")
    log = ctx["log"]
    if not active.is_dir():
        log("93fordF350: 42.13 tree not present; skipped.")
        return False
    source = active / "media/scripts/vehicles/template_F3502_roofrack.txt"
    if not source.is_file():
        log("93fordF350: blocked; B42.13 roofrack source missing.")
        return False
    parts = named_blocks(source.read_text(encoding="utf-8", errors="replace"), PART_RE)
    wanted = {}
    for name in ("F3502Roofrack", "F1502Roofrack"):
        if name not in parts:
            log(f"93fordF350: blocked; source part {name} missing.")
            return False
        wanted[name] = literal(name, parts[name])
    wanted["F1502SpareTires"] = literal("F1502SpareTires", "    template! = F3502SpareTires,")
    return compatibility(ctx, "3073430075", "93fordF350", "42.13", "ZZ_Ford_MissingTemplates_Compatibility.txt", wanted)


def volvo_louver(ctx):
    active = tree(ctx["WORKSHOP"], "3292659291", "89volvo200", "42.13")
    log = ctx["log"]
    if not active.is_dir():
        log("89volvo200: 42.13 tree not present; skipped.")
        return False
    source = template_locations(active).get("VL200WindshieldRearArmorSedan")
    if source is None:
        log("89volvo200: blocked; B42.13 rear-armor source template missing.")
        return False
    part = named_blocks(source[1], PART_RE).get("DAMNWindshieldRearArmor")
    if part is None:
        log("89volvo200: blocked; B42.13 rear-armor part missing.")
        return False
    # Keep B42 install, uninstall, and Lua callbacks, while removing the two
    # armor models and multi-item behavior that a dedicated louver must not add.
    part = re.sub(r"\n\s*model VL200windra[WM]\s*\{.*?\n\s*\}", "", part, flags=re.S)
    part = re.sub(r"itemType\s*=\s*[^,]+,", "itemType = Base.89volvo240Louver1,", part)
    if "VL200louver0P" not in part or "WindshieldRearArmorS" not in part:
        log("89volvo200: blocked; B42.13 louver source structure changed.")
        return False
    return compatibility(ctx, "3292659291", "89volvo200", "42.13", "ZZ_VL200_Compatibility.txt", {"VL200Louver": literal("VL200Louver", part)})


def run(ctx):
    changed = cobb(ctx)
    changed |= source_copy(ctx, "2566953935", "86oshkoshP19A", "media/scripts/vehicles/template_P19A_trunk_cluster2.txt", "P19ABigTrunkCompartment2", "template_P19A_trunk_cluster2.txt")
    changed |= source_copy(ctx, "3001592312", "93mustangSSP", "media/scripts/vehicles/template_SSP93_gunrack.txt", "SSP93Gunrack", "template_SSP93_gunrack.txt")
    changed |= source_copy(ctx, "3196180339", "87chevySuburban", "media/scripts/vehicles/template_SUB87_gunrack.txt", "SUB87Gunrack", "template_SUB87_gunrack.txt")
    changed |= jeep_collision(ctx)
    changed |= compatibility(ctx, "3670064951", "KI5campers", "42.13", "ZZ_KI5campers_Compatibility.txt", {"KI5CRStabilizerB16": literal("KI5CRStabilizerB16", "    template! = KI5CRStabilizer,")})
    changed |= compatibility(ctx, "3110911330", "87fordB700", "42.20", "ZZ_B700_Compatibility.txt", {"B700Mudflaps": literal("B700Mudflaps", "    template! = F700Mudflaps,"), "B700SideStorage": literal("B700SideStorage", "")})
    changed |= compatibility(ctx, "3152529790", "93chevySuburban", "42.13", "ZZ_SUB93_Compatibility.txt", {"SUB93BumpersCCSPD": literal("SUB93BumpersCCSPD", "    template! = SUB93BumpersCCPD,"), "SUB93TrunkDoorWrecker": literal("SUB93TrunkDoorWrecker", "    template! = SUB93TrunkDoorFlatbed,")})
    changed |= ford_roofrack(ctx)
    changed |= volvo_louver(ctx)
    changed |= compatibility(ctx, "2886833398", "89fordBronco", "42.13", "ZZ_BR89_Compatibility.txt", {"BR89SpareTiresPD": literal("BR89SpareTiresPD", "    template! = BR89SpareTires,")})
    changed |= compatibility(ctx, "2897390033", "97bushmaster", "42.13", "ZZ_BUSH_Compatibility.txt", {"BUSHTires": literal("BUSHTires", "")})
    changed |= compatibility(ctx, "2942793445", "90pierceArrow", "42.13", "ZZ_Pierce_Compatibility.txt", {"1500WaterTruckTank": literal("1500WaterTruckTank", "")})
    return changed


FIX = {"name": "KI5 and DAMN-based vehicle template compatibility", "run": run}
