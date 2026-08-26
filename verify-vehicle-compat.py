#!/usr/bin/env python3
"""Read-only structural verification for generated vehicle compatibility files."""
import argparse
import importlib.util
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_PATH = SCRIPT_DIR / "fix-scripts" / "_vehicle_compat.py"
spec = importlib.util.spec_from_file_location("vehicle_compat", HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(helper)

EXPECTED = (
    ("3171167894", "damnlib", "42.20", "media/scripts/commonItems/ZZ_DAMN_42_20_Compatibility.txt", ()),
    ("3722240318", "cobbM540", "42.13", "media/scripts/vehicles/ZZ_M540_Compatibility.txt", ("M540Headlights",)),
    ("3670064951", "KI5campers", "42.13", "media/scripts/vehicles/ZZ_KI5campers_Compatibility.txt", ("KI5CRStabilizerB16",)),
    ("3110911330", "87fordB700", "42.20", "media/scripts/vehicles/ZZ_B700_Compatibility.txt", ("B700Mudflaps", "B700SideStorage")),
    ("3152529790", "93chevySuburban", "42.13", "media/scripts/vehicles/ZZ_SUB93_Compatibility.txt", ("SUB93BumpersCCSPD", "SUB93TrunkDoorWrecker")),
    ("3073430075", "93fordF350", "42.13", "media/scripts/vehicles/ZZ_Ford_MissingTemplates_Compatibility.txt", ("F3502Roofrack", "F1502Roofrack", "F1502SpareTires")),
    ("3292659291", "89volvo200", "42.13", "media/scripts/vehicles/ZZ_VL200_Compatibility.txt", ("VL200Louver",)),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workshop-root", type=Path, required=True)
    args = parser.parse_args()
    failed = False
    for workshop_id, mod, version, relative, expected in EXPECTED:
        path = args.workshop_root / workshop_id / "mods" / mod / version / relative
        if not path.exists():
            print(f"SKIP missing compatibility file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        names = [match.group(1) for match in helper.TEMPLATE_RE.finditer(text)]
        errors = []
        if not helper.balanced(text):
            errors.append("unbalanced braces")
        if len(names) != len(set(names)):
            errors.append("duplicate template names")
        errors.extend(f"missing {name}" for name in expected if name not in names)
        if errors:
            failed = True
            print(f"FAIL {path}: {', '.join(errors)}")
        else:
            print(f"OK {path}: {len(names)} unique template(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
