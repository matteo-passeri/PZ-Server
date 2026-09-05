import pytest

from conftest import FIX_SCRIPTS as FIX_DIR, fix_context, load_path_module


def original_lua(transmit, comment=""):
    return f"""function MDO_Utils.addObjectToSquare(square, spriteName){comment}
    local newObj = IsoObject.new(square, spriteName, nil, false)
    square:AddTileObject(newObj)
    {transmit}
end

function MDO_Utils.after()
end
"""


def tile(sprite_name, attached, ladder=None):
    ladder_line = f"    {ladder} =\n" if ladder else ""
    return f"""// {sprite_name}
tile {{
    {attached} =
    forceFade =
{ladder_line}}}
"""


def original_tiles(ladders=False):
    entries = (
        ("carpentry_02_84", "attachedW", "ladderW"),
        ("carpentry_02_85", "attachedN", "ladderN"),
        ("carpentry_02_86", "attachedW", "ladderE"),
        ("carpentry_02_87", "attachedN", "ladderS"),
    )
    return "".join(tile(sprite, attached, ladder if ladders else None)
                   for sprite, attached, ladder in entries)


def target_paths(workshop, module):
    root = workshop / module.WORKSHOP_ID / module.MOD_ROOT
    lua = root / module.LUA_RELATIVE
    tiles = root / module.TILE_RELATIVE
    lua.parent.mkdir(parents=True)
    tiles.parent.mkdir(parents=True)
    return lua, tiles


@pytest.mark.parametrize("comment", ("", " -- comment", " -- Add Object to Square   "))
def test_world_sync_matches_guarded_declarations_and_is_idempotent(tmp_path, comment):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.BROKEN_TRANSMIT, comment), encoding="utf-8")
    tiles.write_text(original_tiles(ladders=True), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    patched = lua.read_text(encoding="utf-8")
    assert module.BROKEN_TRANSMIT not in patched
    assert module.FIXED_TRANSMIT in patched
    assert "world-object sync: patched" in messages[0]

    before = lua.read_bytes()
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert lua.read_bytes() == before
    assert any("world-object sync: ALREADY PATCHED" in message for message in messages)


def test_world_sync_allows_normal_declaration_whitespace():
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    lua = (
        "  function   MDO_Utils.addObjectToSquare ( square , spriteName )  -- comment\n"
        f"    {module.BROKEN_TRANSMIT}\n"
        "end\n"
    )

    updated, status = module.plan_lua_fix(lua)
    assert status == "APPLIED"
    assert module.BROKEN_TRANSMIT not in updated
    assert module.FIXED_TRANSMIT in updated


def test_already_fixed_world_sync_succeeds(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.FIXED_TRANSMIT), encoding="utf-8")
    tiles.write_text(original_tiles(), encoding="utf-8")
    messages = []

    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert any("world-object sync: ALREADY PATCHED" in message for message in messages)


def test_missing_function_is_successful_skip_and_ladders_still_patch(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text("function MDO_Utils.other()\nend\n", encoding="utf-8")
    tiles.write_text(original_tiles(ladders=True), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    assert any("world-object sync: SKIPPED / UPSTREAM CHANGED" in message
               for message in messages)
    patched = tiles.read_text(encoding="utf-8")
    assert all(f"{ladder} =" not in patched for ladder in module.LADDER_PROPERTIES.values())


def test_missing_world_sync_file_is_successful_and_ladders_still_patch(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.unlink(missing_ok=True)
    tiles.write_text(original_tiles(ladders=True), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    assert any("world-object sync: SKIPPED / TARGET MISSING" in message
               for message in messages)
    assert all(f"{ladder} =" not in tiles.read_text(encoding="utf-8")
               for ladder in module.LADDER_PROPERTIES.values())


def test_empty_ladder_properties_are_removed_and_second_run_is_idempotent(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.FIXED_TRANSMIT), encoding="utf-8")
    tiles.write_text(original_tiles(ladders=True), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    assert all(f"{ladder} =" not in tiles.read_text(encoding="utf-8")
               for ladder in module.LADDER_PROPERTIES.values())
    before = tiles.read_bytes()
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert tiles.read_bytes() == before
    assert sum("ladder tile properties" in message and "ALREADY PATCHED" in message
               for message in messages) == 4


def test_one_ladder_skip_does_not_prevent_other_ladder_targets(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.FIXED_TRANSMIT), encoding="utf-8")
    broken = original_tiles(ladders=True).replace("// carpentry_02_84", "// unknown_sprite")
    tiles.write_text(broken, encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    patched = tiles.read_text(encoding="utf-8")
    assert "ladderW =" in patched
    assert all(f"{ladder} =" not in patched for ladder in ("ladderN", "ladderE", "ladderS"))
    assert any("carpentry_02_84: SKIPPED / UPSTREAM CHANGED" in message
               for message in messages)


def test_ladder_skip_does_not_prevent_world_sync_patch(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.BROKEN_TRANSMIT), encoding="utf-8")
    tiles.write_text("unknown tile content\n", encoding="utf-8")

    assert module.FIX["run"](fix_context(workshop))
    assert module.FIXED_TRANSMIT in lua.read_text(encoding="utf-8")
    assert tiles.read_text(encoding="utf-8") == "unknown tile content\n"


def test_unexpected_io_failure_remains_fatal(tmp_path, monkeypatch):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.BROKEN_TRANSMIT), encoding="utf-8")
    tiles.write_text(original_tiles(), encoding="utf-8")

    def fail_read(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(module.Path, "read_text", fail_read)

    with pytest.raises(OSError, match="disk"):
        module.FIX["run"](fix_context(workshop))
