from conftest import FIX_SCRIPTS, fix_context, load_path_module


FIX_NAME = "44-lugli-achievements-b42-20-weapon-categories.py"


def target_path(workshop, module):
    path = workshop / module.WORKSHOP_ID / module.MOD_ROOT / module.LUA_RELATIVE
    path.parent.mkdir(parents=True)
    return path


def test_known_bad_combat_is_patched_once_and_is_idempotent(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    combat = target_path(workshop, module)
    combat.write_text("before\n" + module.KNOWN_BAD + "\nafter\n", encoding="utf-8")
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx.update({
        "active_workshop_ids": (module.WORKSHOP_ID,),
        "active_mod_ids": (module.MOD_ID,),
    })

    assert module.FIX["run"](ctx)
    patched = combat.read_text(encoding="utf-8")
    assert "script:getWeaponCategories()" in patched
    assert "categories:iterator()" in patched
    assert "pcall(script.containsWeaponCategory, script, cat)" not in patched
    assert messages[-1] == "Lugli - Achievements: patched Combat.lua."

    before = combat.read_bytes()
    assert not module.FIX["run"](ctx)
    assert combat.read_bytes() == before
    assert messages[-1] == "Lugli - Achievements: ALREADY PATCHED."


def test_known_good_combat_is_left_untouched(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    combat = target_path(workshop, module)
    combat.write_text(module.KNOWN_GOOD, encoding="utf-8")
    messages = []

    before = combat.read_bytes()
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert combat.read_bytes() == before
    assert messages[-1] == "Lugli - Achievements: ALREADY PATCHED."


def test_unknown_upstream_combat_is_skipped_byte_for_byte(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    combat = target_path(workshop, module)
    combat.write_bytes(b"local function creditCategories()\n    changed upstream\nend\n")
    messages = []

    before = combat.read_bytes()
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert combat.read_bytes() == before
    assert any("SKIPPED / UPSTREAM CHANGED" in message for message in messages)


def test_missing_target_is_a_successful_skip(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    messages = []

    assert not module.FIX["run"](fix_context(tmp_path / "workshop", messages.append))
    assert messages == ["Lugli - Achievements: SKIPPED / TARGET NOT INSTALLED."]


def test_only_the_target_workshop_mod_and_42_20_file_can_change(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    target = target_path(workshop, module)
    target.write_text(module.KNOWN_BAD, encoding="utf-8")
    old_version = workshop / module.WORKSHOP_ID / module.MOD_ROOT / "42.19" / module.LUA_RELATIVE.relative_to("42.20")
    wrong_mod = workshop / module.WORKSHOP_ID / "mods" / "OtherMod" / module.LUA_RELATIVE
    wrong_workshop = workshop / "9999999999" / module.MOD_ROOT / module.LUA_RELATIVE
    for path in (old_version, wrong_mod, wrong_workshop):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(module.KNOWN_BAD, encoding="utf-8")
    before = {path: path.read_bytes() for path in (old_version, wrong_mod, wrong_workshop)}

    assert module.FIX["run"](fix_context(workshop))
    assert "script:getWeaponCategories()" in target.read_text(encoding="utf-8")
    assert {path: path.read_bytes() for path in before} == before


def test_inactive_target_is_not_patched(tmp_path):
    module = load_path_module(FIX_SCRIPTS / FIX_NAME)
    workshop = tmp_path / "workshop"
    combat = target_path(workshop, module)
    combat.write_text(module.KNOWN_BAD, encoding="utf-8")
    before = combat.read_bytes()
    ctx = fix_context(workshop)
    ctx.update({
        "active_workshop_ids": ("9999999999",),
        "active_mod_ids": ("OtherMod",),
    })

    assert not module.FIX["run"](ctx)
    assert combat.read_bytes() == before
