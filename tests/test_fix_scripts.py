import pytest

from conftest import FIX_SCRIPTS as FIX_DIR, fix_context, load_path_module


FIX_PATHS = tuple(sorted(path for path in FIX_DIR.glob("*.py") if not path.name.startswith("_")))


@pytest.mark.parametrize("path", FIX_PATHS, ids=lambda path: path.stem)
def test_each_fix_is_a_safe_noop_when_its_workshop_content_is_absent(path, tmp_path):
    module = load_path_module(path)
    messages = []
    assert module.FIX["run"](fix_context(tmp_path / "workshop", messages.append)) is False
    assert not (tmp_path / "workshop").exists()
    assert messages


def test_limestone_fix_updates_only_script_files_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_DIR / "10-weldingrodmod-craft-plaster.py")
    workshop = tmp_path / "workshop"
    script = workshop / "3496263414/mods/Foo/42/media/scripts/items.txt"
    script.parent.mkdir(parents=True)
    script.write_text("Base.CrushedLimestone", encoding="utf-8")
    assert module.FIX["run"](fix_context(workshop))
    assert script.read_text(encoding="utf-8") == "Base.LimestoneCrushed"
    assert not module.FIX["run"](fix_context(workshop))


def test_hot_brass_aliases_are_idempotent_and_do_not_overwrite(tmp_path):
    module = load_path_module(FIX_DIR / "23-hot-brass-linux-case.py")
    workshop = tmp_path / "workshop"
    animsets = workshop / module.WORKSHOP_ID / "mods" / module.MOD_DIRECTORY / "42/media/AnimSets"
    animsets.mkdir(parents=True)
    source = animsets / "Player.XML"
    source.write_text("xml", encoding="utf-8")
    assert module.FIX["run"](fix_context(workshop))
    assert (animsets / "player.xml").is_symlink()
    assert not module.FIX["run"](fix_context(workshop))


def test_log_driven_case_fix_rebases_container_workshop_paths_safely(tmp_path):
    module = load_path_module(FIX_DIR / "00-linux-animset-xml-case.py")
    workshop = tmp_path / "host/steamapps/workshop/content/108600"
    mod_root = workshop / "123/mods/Vehicle Repair Overhaul/42/media/scripts"
    mod_root.mkdir(parents=True)
    (mod_root / "test.lua").write_text("lua", encoding="utf-8")
    container_path = (
        "/home/steam/zomboid/steamapps/workshop/content/108600/123/mods/"
        "Vehicle Repair Overhaul/42/media/scripts/Test.lua"
    )
    host_path = str(mod_root / "Test.lua")
    expected_suffix = ("123", "mods", "Vehicle Repair Overhaul", "42", "media", "scripts", "Test.lua")
    assert module.relative_to_workshop(container_path, workshop, ("123",)) == expected_suffix
    assert module.relative_to_workshop(host_path, workshop, ("123",)) == expected_suffix
    assert module.resolve_case_only_path(host_path, workshop, ("123",))[0] == "resolved"
    assert module.relative_to_workshop(container_path.replace("/123/mods/", "/999/mods/"), workshop, ("123",)) is None
    assert module.relative_to_workshop(container_path.replace("/123/mods/", "/123/notmods/"), workshop, ("123",)) is None
    assert module.relative_to_workshop("/home/steam/zomboid/unrelated/108600/123/mods/Foo/a.lua", workshop, ("123",)) is None
    assert module.relative_to_workshop(container_path.replace("/scripts/", "/../scripts/"), workshop, ("123",)) is None
    outside = tmp_path / "outside"
    outside.mkdir()
    (workshop / "123/mods/Escaped").symlink_to(outside, target_is_directory=True)
    escaped = "/home/steam/zomboid/steamapps/workshop/content/108600/123/mods/Escaped/Foo.lua"
    assert module.resolve_case_only_path(escaped, workshop, ("123",))[0] == "outside_active_tree"

    log = tmp_path / "server.log"
    log.write_text(f"java.nio.file.NoSuchFileException: {container_path}\n", encoding="utf-8")
    ctx = fix_context(workshop)
    ctx.update({"active_workshop_ids": ("123",), "latest_pz_server_log": lambda: log})
    assert module.FIX["run"](ctx)
    assert (mod_root / "Test.lua").is_symlink()
    assert not module.FIX["run"](ctx)

    zero = mod_root / "Missing.lua"
    assert module.resolve_case_only_path(str(zero), workshop, ("123",))[0] == "unfixable"
    (mod_root / "other.lua").write_text("one", encoding="utf-8")
    (mod_root / "OTHER.LUA").write_text("two", encoding="utf-8")
    assert module.resolve_case_only_path(str(mod_root / "Other.lua"), workshop, ("123",))[0] == "ambiguous"
