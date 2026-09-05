import json

from conftest import FIX_SCRIPTS, fix_context, load_path_module


def upstream_lua(module):
    patch = module.PATCH_PATH.read_text(encoding="utf-8")
    return "\n-- fixture boundary --\n".join(old for old, _new in module.parse_patch_hunks(patch))


def fixed_lua(module):
    original = upstream_lua(module)
    return module.plan_lua_patch(original, module.PATCH_PATH.read_text(encoding="utf-8"))[0]


def install_fixture(workshop, module, item_id="1234567890", version="42.15", lua=None):
    mod = workshop / item_id / "mods" / "ArbitraryDirectoryName"
    tree = mod / version
    tree.mkdir(parents=True)
    (tree / "mod.info").write_text(
        "name=Nearby Animals\n"
        f"id={module.MOD_ID}\n"
        "modversion=1.0.7\n"
        f"versionMin={version}\n"
        "versionMax=42.99\n",
        encoding="utf-8",
    )
    translation = tree / "media/lua/shared/Translate/EN/IG_UI.json"
    translation.parent.mkdir(parents=True)
    translation.write_text(json.dumps({key: key for key in module.REQUIRED_TRANSLATION_KEYS}),
                           encoding="utf-8")
    lua_path = mod / module.LUA_RELATIVE
    lua_path.parent.mkdir(parents=True)
    lua_path.write_text(lua if lua is not None else upstream_lua(module), encoding="utf-8")
    return mod


def test_discovers_mod_id_without_fixed_item_or_directory_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module, item_id="9876543210")
    unrelated = mod / "unrelated.txt"
    unrelated.write_text("keep me", encoding="utf-8")
    old_tree_file = mod / "42.15/mod.info"
    old_tree = old_tree_file.read_bytes()
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx["active_workshop_ids"] = ("9876543210",)

    assert module.FIX["run"](ctx)
    assert (mod / module.LUA_RELATIVE).read_text(encoding="utf-8") == fixed_lua(module)
    assert (mod / "42.20/mod.info").is_file()
    assert "versionMin=42.20" in (mod / "42.20/mod.info").read_text(encoding="utf-8")
    assert (mod / "42.20/media/lua/shared/Translate/EN/IG_UI.json").is_file()
    assert old_tree_file.read_bytes() == old_tree
    assert unrelated.read_text(encoding="utf-8") == "keep me"
    assert any("found installed mod at 9876543210/mods/ArbitraryDirectoryName" in message
               for message in messages)

    before = (mod / module.LUA_RELATIVE).read_bytes()
    assert not module.FIX["run"](ctx)
    assert (mod / module.LUA_RELATIVE).read_bytes() == before
    assert messages[-1] == "NearbyAnimals: ALREADY PATCHED."


def test_target_not_installed_is_successful_skip(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    messages = []

    assert not module.FIX["run"](fix_context(tmp_path / "workshop", messages.append))
    assert messages == ["NearbyAnimals: SKIPPED / TARGET NOT INSTALLED."]


def test_unknown_upstream_is_explicit_successful_skip(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module, lua="unknown revision\n")
    messages = []

    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert (mod / module.LUA_RELATIVE).read_text(encoding="utf-8") == "unknown revision\n"
    assert not (mod / "42.20").exists()
    assert any("SKIPPED / UPSTREAM CHANGED" in message for message in messages)


def test_upstream_fixed_without_local_backup_is_successful_skip(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module, version="42.20", lua=fixed_lua(module))
    messages = []

    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert messages[-1] == "NearbyAnimals: UPSTREAM FIXED / SKIP."
    assert not (mod / module.LUA_RELATIVE).with_suffix(".lua.pz-local-fix.bak").exists()


def test_only_selected_active_tree_is_used_and_old_trees_are_unchanged(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module)
    legacy = mod / "41/mod.info"
    legacy.parent.mkdir()
    legacy.write_text(f"id={module.MOD_ID}\nversionMin=41\nversionMax=41\n", encoding="utf-8")
    old_before = (mod / "42.15/mod.info").read_bytes()
    legacy_before = legacy.read_bytes()

    assert module.FIX["run"](fix_context(workshop))
    assert (mod / "42.15/mod.info").read_bytes() == old_before
    assert legacy.read_bytes() == legacy_before


def test_production_fix_has_no_external_checkout_configuration():
    source = (FIX_SCRIPTS / "41-nearby-animals-b42-20.py").read_text(encoding="utf-8")
    assert "DEFAULT_SOURCE" not in source
    assert "nearby_animals_source" not in source
    assert "copytree" not in source
    assert "/home/matteo" not in source
    assert "/mnt/work" not in source
