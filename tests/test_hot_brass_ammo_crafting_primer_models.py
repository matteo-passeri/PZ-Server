from conftest import FIX_SCRIPTS, fix_context, load_path_module


FIX_NAME = "46-hot-brass-ammo-crafting-primer-models.py"


def write_fixture(workshop, module, items):
    root = workshop / module.WORKSHOP_ID / "mods" / module.MOD_DIRECTORY / "42.19/media/scripts"
    models = root / "models/SpentCasingPhysicsAmmoCraft/Ingredients.txt"
    target = root / "items/SpentCasingPhysicsAmmoCraft/Ingredients.txt"
    models.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    models.write_text(
        "module HBAC {\nmodel Primer_Rifle\nmodel Primer_Pistol\nmodel Primer_Shotshell\n}\n",
        encoding="utf-8",
    )
    target.write_text(items, encoding="utf-8")
    return target


def vulnerable_items():
    primers = "\n".join(
        f"item {primer}\n{{\n    StaticModel = HBVCEF.{primer},\n"
        f"    WorldStaticModel = HBVCEF.{primer},\n}}"
        for primer in ("Primer_Rifle", "Primer_Pistol", "Primer_Shotshell")
    )
    return primers + "\nitem Projectile\n{\n    StaticModel = HBVCEF.Projectile_Rifle,\n    WorldStaticModel = HBVCEF.Projectile_Rifle,\n}\n"


def test_hot_brass_primer_fix_changes_only_six_known_fields_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    target = write_fixture(tmp_path / "workshop", module, vulnerable_items())
    before = target.read_text(encoding="utf-8")

    assert module.FIX["run"](fix_context(tmp_path / "workshop"))
    after = target.read_text(encoding="utf-8")
    assert after.count("HBAC.Primer_") == 6
    assert after.count("HBVCEF.Primer_") == 0
    assert "StaticModel = HBVCEF.Projectile_Rifle," in after
    assert "WorldStaticModel = HBVCEF.Projectile_Rifle," in after
    assert before.replace("HBVCEF.Primer_", "HBAC.Primer_") == after
    assert not module.FIX["run"](fix_context(tmp_path / "workshop"))
    assert target.read_text(encoding="utf-8") == after


def test_hot_brass_primer_fix_leaves_already_fixed_and_unknown_layouts_unchanged(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    fixed = vulnerable_items().replace("HBVCEF.Primer_", "HBAC.Primer_")
    target = write_fixture(workshop, module, fixed)
    assert not module.FIX["run"](fix_context(workshop))
    assert target.read_text(encoding="utf-8") == fixed

    mixed = fixed.replace("HBAC.Primer_Rifle", "HBVCEF.Primer_Rifle", 1)
    target.write_text(mixed, encoding="utf-8")
    messages = []
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert target.read_text(encoding="utf-8") == mixed
    assert "SKIPPED / UPSTREAM CHANGED" in messages[-1]


def test_hot_brass_primer_fix_skips_missing_target(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    messages = []
    assert not module.FIX["run"](fix_context(tmp_path / "workshop", messages.append))
    assert messages[-1] == "Hot Brass Ammo Crafting primers: SKIPPED / TARGET NOT INSTALLED."
