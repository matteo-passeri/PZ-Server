import shutil
from pathlib import Path

from conftest import FIX_SCRIPTS, fix_context, load_path_module


SOURCE = Path(__file__).resolve().parents[2] / "NearbyAnimals"


def install_fixture(workshop, module):
    mod = workshop / "123" / "mods" / "NearbyAnimals"
    shutil.copytree(SOURCE / "common", mod / "common")
    shutil.copytree(SOURCE / "42.15", mod / "42.15")
    lua = mod / module.LUA_RELATIVE
    lua.write_bytes(bytes.fromhex("00"))
    # Restore the exact unpatched file from the parent commit without relying
    # on a deployed Workshop download in this unit test.
    import subprocess
    lua.write_bytes(subprocess.check_output([
        "git", "-C", str(SOURCE), "show",
        "53574dd:common/media/lua/client/DBD_NearbyAnimals.lua",
    ]))
    return mod


def test_nearby_animals_fix_installs_committed_b42_20_tree_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module)
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx["nearby_animals_source"] = SOURCE

    assert module.FIX["run"](ctx)
    assert module.digest(mod / module.LUA_RELATIVE) == module.FIXED_LUA_SHA256
    assert (mod / module.LUA_RELATIVE).with_suffix(".lua.pz-local-fix.bak").is_file()
    assert module.target_tree_is_safe(mod / "42.20", SOURCE)
    assert not module.FIX["run"](ctx)
    assert messages[-1] == "NearbyAnimals: B42.20 compatibility update already present."


def test_nearby_animals_fix_leaves_unknown_upstream_revision_untouched(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "41-nearby-animals-b42-20.py")
    workshop = tmp_path / "workshop"
    mod = install_fixture(workshop, module)
    lua = mod / module.LUA_RELATIVE
    lua.write_text("unknown revision", encoding="utf-8")
    ctx = fix_context(workshop)
    ctx["nearby_animals_source"] = SOURCE

    assert not module.FIX["run"](ctx)
    assert lua.read_text(encoding="utf-8") == "unknown revision"
    assert not (mod / "42.20").exists()
