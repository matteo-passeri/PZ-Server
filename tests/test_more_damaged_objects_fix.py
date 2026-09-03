from pathlib import Path

import pytest

from conftest import FIX_SCRIPTS as FIX_DIR, fix_context, load_path_module


def original_lua(transmit="newObj:transmitCompleteItemToClients()"):
    return f"""function MDO_Utils.addObjectToSquare(square, spriteName)
    local newObj = IsoObject.new(square, spriteName, nil, false)
    square:AddTileObject(newObj)
    {transmit}
end

function MDO_Utils.after()
end
"""


def tile(sprite_name, attached):
    return f"""// {sprite_name}
tile {{
    {attached} =
    forceFade =
}}
"""


def original_tiles():
    return "".join((
        tile("carpentry_02_84", "attachedW"),
        tile("carpentry_02_85", "attachedN"),
        tile("carpentry_02_86", "attachedW"),
        tile("carpentry_02_87", "attachedN"),
    ))


def target_paths(workshop, module):
    root = workshop / module.WORKSHOP_ID / module.MOD_ROOT
    lua = root / module.LUA_RELATIVE
    tiles = root / module.TILE_RELATIVE
    lua.parent.mkdir(parents=True)
    tiles.parent.mkdir(parents=True)
    return lua, tiles


def test_mdo_fixes_apply_correct_mapping_and_are_idempotent(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(), encoding="utf-8")
    tiles.write_text(original_tiles(), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    assert module.CLIENT_TRANSMIT not in lua.read_text(encoding="utf-8")
    assert module.SERVER_TRANSMIT in lua.read_text(encoding="utf-8")
    patched_tiles = tiles.read_text(encoding="utf-8")
    for sprite_name, ladder in module.LADDER_PROPERTIES.items():
        start, end = module.tile_block(patched_tiles, sprite_name)
        assert f"{ladder} =" in patched_tiles[start:end]
        assert patched_tiles[start:end].index("forceFade =") < patched_tiles[start:end].index(f"{ladder} =")
    assert "world-object sync: APPLIED" in messages[0]
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert "world-object sync: ALREADY PATCHED" in messages[-5]
    assert all("ALREADY PATCHED" in message for message in messages[-5:])


def test_mdo_fixes_leave_already_patched_files_byte_identical(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(module.SERVER_TRANSMIT), encoding="utf-8")
    patched_tiles, _ = module.plan_tile_fix(original_tiles())
    tiles.write_text(patched_tiles, encoding="utf-8")
    before_lua = lua.read_bytes()
    before_tiles = tiles.read_bytes()

    assert not module.FIX["run"](fix_context(workshop))
    assert lua.read_bytes() == before_lua
    assert tiles.read_bytes() == before_tiles


def test_mdo_fix_skips_a_missing_target_but_applies_the_other_fix(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    tiles.write_text(original_tiles(), encoding="utf-8")
    messages = []

    assert module.FIX["run"](fix_context(workshop, messages.append))
    assert "world-object sync: SKIPPED / TARGET MISSING" in messages[0]
    assert all(f"{ladder} =" in tiles.read_text(encoding="utf-8")
               for ladder in module.LADDER_PROPERTIES.values())


@pytest.mark.parametrize("broken_lua", (
    "newObj:transmitCompleteItemToClients()\nnewObj:transmitCompleteItemToClients()",
    "newObj:transmitCompleteItemToServer()\nnewObj:transmitCompleteItemToClients()",
))
def test_mdo_fix_rejects_ambiguous_lua_without_partial_write(tmp_path, broken_lua):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(broken_lua), encoding="utf-8")
    tiles.write_text(original_tiles(), encoding="utf-8")
    before_tiles = tiles.read_bytes()

    with pytest.raises(module.UpstreamChangedError):
        module.FIX["run"](fix_context(workshop))
    assert tiles.read_bytes() == before_tiles


def test_mdo_fix_rejects_wrong_ladder_property_without_partial_write(tmp_path):
    module = load_path_module(FIX_DIR / "42-more-damaged-objects-b42-20.py")
    workshop = tmp_path / "workshop"
    lua, tiles = target_paths(workshop, module)
    lua.write_text(original_lua(), encoding="utf-8")
    tiles.write_text(original_tiles().replace("forceFade =", "forceFade =\n    ladderN =", 1), encoding="utf-8")
    before_lua = lua.read_bytes()
    before_tiles = tiles.read_bytes()

    with pytest.raises(module.UpstreamChangedError):
        module.FIX["run"](fix_context(workshop))
    assert lua.read_bytes() == before_lua
    assert tiles.read_bytes() == before_tiles
