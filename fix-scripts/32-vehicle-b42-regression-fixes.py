#!/usr/bin/env python3
"""Narrow B42 regression corrections with strict source-shape guards."""
from _vehicle_compat import TEMPLATE_RE, backup_and_write, named_blocks, tree


J10_OLD_SPARE_TIRE = "template = JP82SpareTires/part/JP82SpareTireRear,"
J10_NEW_SPARE_TIRE = "template = JP82SpareTires/part/DAMNSpareTire,"


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
    changed = patch_j10_spare_tire(ctx)
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
