from conftest import FIX_SCRIPTS, fix_context, load_path_module


FIX_NAME = "47-bicycle-plastic-bag-model.py"


def content(value="Plasticbag"):
    return (
        "item BicycleBagOne\n{\n    Material2 = PlasticBag,\n"
        f"    WorldStaticModel = {value},\n}}\n"
        "item BicycleBagTwo\n{\n    Material2 = PlasticBag,\n"
        f"    WorldStaticModel = {value},\n}}\n"
        "// Plasticbag must remain an unrelated comment\n"
    )


def write_fixture(workshop, module, text, directory=None):
    directory = directory or module.MOD_DIRECTORY
    path = workshop / module.WORKSHOP_ID / "mods" / directory / module.SCRIPT_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_bicycle_fix_changes_only_b42_20_fields_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    target = write_fixture(workshop, module, content())
    old_version = target.parents[3] / "42.19/media/scripts/Bicycle_item.txt"
    old_version.parent.mkdir(parents=True)
    old_version.write_text(content(), encoding="utf-8")

    assert module.FIX["run"](fix_context(workshop))
    after = target.read_text(encoding="utf-8")
    assert after.count("WorldStaticModel = PlasticBag_Ground,") == 2
    assert "Material2 = PlasticBag," in after
    assert "// Plasticbag must remain an unrelated comment" in after
    assert old_version.read_text(encoding="utf-8") == content()
    assert not module.FIX["run"](fix_context(workshop))
    assert target.read_text(encoding="utf-8") == after


def test_bicycle_fix_handles_case_alias_once_and_skips_unknown_layout(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    target = write_fixture(workshop, module, content())
    alias = target.parents[3].with_name("bicycle")
    alias.symlink_to(target.parents[3].name, target_is_directory=True)
    assert module.FIX["run"](fix_context(workshop))
    assert target.read_text(encoding="utf-8").count("PlasticBag_Ground") == 2

    target.write_text(content().replace("Plasticbag", "OtherModel", 1), encoding="utf-8")
    messages = []
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert "OtherModel" in target.read_text(encoding="utf-8")
    assert "SKIPPED / UPSTREAM CHANGED" in messages[-1]


def test_bicycle_fix_skips_missing_target(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    messages = []
    assert not module.FIX["run"](fix_context(tmp_path / "workshop", messages.append))
    assert messages[-1] == "Bicycle plastic-bag model: SKIPPED / TARGET NOT INSTALLED."
