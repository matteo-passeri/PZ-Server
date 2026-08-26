#!/usr/bin/env python3
"""Narrow B42 regression correction with strict source-shape guards."""
import re
from _vehicle_compat import TEMPLATE_RE, backup_and_write, named_blocks, tree


def run(ctx):
    active = tree(ctx["WORKSHOP"], "3161951724", "76chevyKseries", "42.13")
    log = ctx["log"]
    path = active / "media/scripts/vehicles/template_CH76_spareTires.txt"
    if not path.is_file():
        log("76chevyKseries: 42.13 spare-tire template not present; skipped.")
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        block = named_blocks(text, TEMPLATE_RE).get("CH76SpareTireRoofDually")
    except ValueError:
        log("76chevyKseries: blocked; unbalanced vehicle script.")
        return False
    if block is None:
        log("76chevyKseries: blocked; CH76SpareTireRoofDually block missing.")
        return False
    bad = "template! = DAMNSpareTireRoof,"
    good = "template! = CH76SpareTireRoof,"
    if good in block and bad not in block:
        log("76chevyKseries: CH76SpareTireRoofDually already fixed; skip.")
        return False
    if block.count(bad) != 1 or good in block:
        log("76chevyKseries: blocked; unexpected parent template structure.")
        return False
    replacement = block.replace(bad, good)
    backup_and_write(path, text.replace(block, replacement, 1))
    log("76chevyKseries: patched CH76SpareTireRoofDually parent template.")
    return True


FIX = {"name": "B42 vehicle regression fixes", "run": run}
