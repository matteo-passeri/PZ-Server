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
