#!/usr/bin/env python3
"""Narrow B42 regression corrections with strict source-shape guards."""
import re

from _vehicle_compat import (
    TEMPLATE_RE,
    backup_and_write,
    backup_and_write_bytes,
    named_blocks,
    tree,
)


J10_OLD_SPARE_TIRE = "template = JP82SpareTires/part/JP82SpareTireRear,"
J10_NEW_SPARE_TIRE = "template = JP82SpareTires/part/DAMNSpareTire,"
MOTORCLUB_WORKSHOP_ID = "3404737883"
MOTORCLUB_MOD_NAME = "AutotsarMotorClub"
MOTORCLUB_WAVERUNNER_RELATIVE = "media/scripts/vehicles/MotoWaverunner650TL.txt"
MOTORCLUB_VERSIONS = ("common", "42.13", "42.15")
API_BOAT_AIRBAG_LINE_RE = re.compile(
    rb"(?m)^[ \t]*template[ \t]*=[ \t]*ApiBoatAirbag,[ \t]*(?:\r\n|\n|\r|$)"
)
MOD_INFO_FIELD_RE = re.compile(r"(?mi)^\s*(?:id|name)\s*=\s*(.+?)\s*$")


def looks_like_aquatsar(value):
    return "aquatsar" in value.lower() or "yacht" in value.lower()


def aquatsar_is_available(ctx):
    """Detect installed or active Aquatsar from configured IDs and Workshop metadata."""
    if any(looks_like_aquatsar(mod_id) for mod_id in ctx.get("active_mod_ids", ())):
        return True

    workshop = ctx["WORKSHOP"]
    workshop_ids = set(ctx.get("active_workshop_ids", ()))
    if workshop.is_dir():
        try:
            workshop_ids.update(
                path.name for path in workshop.iterdir() if path.is_dir() and path.name.isdigit()
            )
        except OSError:
            pass
    for workshop_id in sorted(workshop_ids):
        mods_root = workshop / workshop_id / "mods"
        if not mods_root.is_dir():
            continue
        try:
            mod_roots = sorted(path for path in mods_root.iterdir() if path.is_dir())
        except OSError:
            continue
        for mod_root in mod_roots:
            if looks_like_aquatsar(mod_root.name):
                return True
            try:
                infos = mod_root.rglob("mod.info")
                for info in infos:
                    if not info.is_file():
                        continue
                    fields = MOD_INFO_FIELD_RE.findall(
                        info.read_text(encoding="utf-8", errors="replace")
                    )
                    if any(looks_like_aquatsar(field) for field in fields):
                        return True
            except OSError:
                continue
    return False


def patch_motorclub_api_boat_airbag(ctx):
    log = ctx["log"]
    if aquatsar_is_available(ctx):
        log("Autotsar Motorclub: Aquatsar detected; ApiBoatAirbag references left unchanged.")
        return False

    changed = False
    mod_root = ctx["WORKSHOP"] / MOTORCLUB_WORKSHOP_ID / "mods" / MOTORCLUB_MOD_NAME
    for version in MOTORCLUB_VERSIONS:
        path = mod_root / version / MOTORCLUB_WAVERUNNER_RELATIVE
        if not path.is_file():
            continue
        try:
            original = path.read_bytes()
        except OSError as exc:
            log(f"Autotsar Motorclub: unable to read {path}: {exc}")
            raise RuntimeError(f"Autotsar Motorclub: unable to read {path}") from exc
        updated, removed = API_BOAT_AIRBAG_LINE_RE.subn(b"", original)
        if not removed:
            continue
        try:
            backup_and_write_bytes(path, updated)
        except OSError as exc:
            log(f"Autotsar Motorclub: unable to patch {path}: {exc}")
            raise RuntimeError(f"Autotsar Motorclub: unable to patch {path}") from exc
        log(f"Autotsar Motorclub: removed ApiBoatAirbag reference from {version}.")
        changed = True
    return changed


def patch_j10_spare_tire(ctx):
    active = tree(ctx["WORKSHOP"], "2886832257", "82jeepJ10", "42.13")
    log = ctx["log"]
    path = active / "media/scripts/vehicles/82jeepJ10t.txt"
    if not path.is_file():
        log("82jeepJ10: 42.13 vehicle script not present; skipped.")
        return False

    text = path.read_text(encoding="utf-8", errors="replace")
    old_count = text.count(J10_OLD_SPARE_TIRE)
    new_count = text.count(J10_NEW_SPARE_TIRE)
    if old_count == 0 and new_count == 1:
        log("82jeepJ10: DAMNSpareTire reference already fixed; skip.")
        return False
    if old_count != 1 or new_count != 0:
        log(
            "82jeepJ10: blocked; unexpected spare-tire template references "
            f"(old={old_count}, new={new_count})."
        )
        return False

    backup_and_write(path, text.replace(J10_OLD_SPARE_TIRE, J10_NEW_SPARE_TIRE, 1))
    log("82jeepJ10: patched spare-tire reference to DAMNSpareTire.")
    return True


def run(ctx):
    changed = patch_motorclub_api_boat_airbag(ctx)
    changed |= patch_j10_spare_tire(ctx)
    active = tree(ctx["WORKSHOP"], "3161951724", "76chevyKseries", "42.13")
    log = ctx["log"]
    path = active / "media/scripts/vehicles/template_CH76_spareTires.txt"
    if not path.is_file():
        log("76chevyKseries: 42.13 spare-tire template not present; skipped.")
        return changed
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        block = named_blocks(text, TEMPLATE_RE).get("CH76SpareTireRoofDually")
    except ValueError:
        log("76chevyKseries: blocked; unbalanced vehicle script.")
        return changed
    if block is None:
        log("76chevyKseries: blocked; CH76SpareTireRoofDually block missing.")
        return changed
    bad = "template! = DAMNSpareTireRoof,"
    good = "template! = CH76SpareTireRoof,"
    if good in block and bad not in block:
        log("76chevyKseries: CH76SpareTireRoofDually already fixed; skip.")
        return changed
    if block.count(bad) != 1 or good in block:
        log("76chevyKseries: blocked; unexpected parent template structure.")
        return changed
    replacement = block.replace(bad, good)
    backup_and_write(path, text.replace(block, replacement, 1))
    log("76chevyKseries: patched CH76SpareTireRoofDually parent template.")
    return True


FIX = {"name": "B42 vehicle regression fixes", "run": run}
