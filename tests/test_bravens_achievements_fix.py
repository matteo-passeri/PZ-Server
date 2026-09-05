from conftest import FIX_SCRIPTS, fix_context, load_path_module


def upstream_files(module):
    main = '''BB_Achievements = {}

function ResetAchievements()
    BB_Achievements.startGame = { achieved = false }
    BB_Achievements.killZeds1 = { achieved = false }
end

local function onInitGlobalModData()
    if getWorld():getGameMode() == "Multiplayer" and not isClient() then return end
    BB_Achievements = ModData.getOrCreate("BB_Achievements")

    if BB_Achievements.startGame == nil then
        ResetAchievements()
    end
    BB_Achievements.guardinGnome = { achieved = false }
    BB_Achievements.waitASec = { achieved = false }
    BB_Achievements.pacifist = { achieved = false }
    BB_Achievements.iAmLegend = { achieved = false }
    BB_Achievements.openSesame = { achieved = false }
    BB_Achievements.gta = { achieved = false }
end

Events.OnInitGlobalModData.Add(onInitGlobalModData)
'''
    tracker = '''BB_Achievements_Tracker = {}

function ResetAchievementTrackers()
    BB_Achievements_Tracker.characterName = ""
    BB_Achievements_Tracker.itemsOnInv = 0
    BB_Achievements_Tracker.barricades = 0
    BB_Achievements_Tracker.timeAwake = 0
end

local function onInitGlobalModData()
    if getWorld():getGameMode() == "Multiplayer" and not isClient() then return end
    BB_Achievements_Tracker = ModData.getOrCreate("BB_Achievements_Tracker")

    if BB_Achievements_Tracker.characterName == nil then
        ResetAchievementTrackers()
    end
end

Events.OnInitGlobalModData.Add(onInitGlobalModData)
'''
    client = '''local function onLoadCharacter()
    climateManager = getClimateManager()

    local fullCharName = getPlayer():getFullName()

    if BB_Achievements_Tracker.characterName ~= fullCharName then
        if BB_Achievements.startGame.achieved and SandboxVars.Achievements.ResetOnSwitch then
            ResetAchievements()
            ResetAchievementTrackers()
            BB_Achievements.startGame.achieved = true
        end

        BB_Achievements_Tracker.characterName = fullCharName
    end

    if not BB_Achievements.startGame.achieved then
        AchievementHandler.popIn(BB_Achievements.startGame)
    end
end

Events.OnCreatePlayer.Add(onLoadCharacter)
'''
    return dict(zip(module.LUA_RELATIVES, (main, tracker, client)))


def install_fixture(workshop, module, item_id="3051277957", mod_id=None):
    root = workshop / item_id / "mods" / "UnexpectedDirectory"
    tree = root / module.B42_TREE
    tree.mkdir(parents=True)
    (root / "mod.info").write_text(
        "name=Braven's Achievements\n"
        f"id={mod_id or module.MOD_ID}\nmodversion={module.MOD_VERSION}\n", encoding="utf-8"
    )
    for relative, text in upstream_files(module).items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    barricade = tree / "media/lua/client/overrides/timed actions/BB_Achievements_Barricade.lua"
    barricade.parent.mkdir(parents=True, exist_ok=True)
    barricade.write_text("BB_Achievements_Tracker.barricades = BB_Achievements_Tracker.barricades + 1\n",
                         encoding="utf-8")
    return root


def test_discovery_patch_backup_and_idempotence(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "43-bravens-achievements-b42-persistence.py")
    workshop = tmp_path / "workshop"
    root = install_fixture(workshop, module, item_id="9999999999")
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx["active_workshop_ids"] = ("9999999999",)

    assert module.FIX["run"](ctx)
    for relative in module.LUA_RELATIVES:
        path = root / module.B42_TREE / relative
        patched = path.read_text(encoding="utf-8")
        assert module.MARKER in patched
        assert path.with_suffix(path.suffix + ".pz-local-fix.bak").is_file()
    main = (root / module.B42_TREE / module.LUA_RELATIVES[0]).read_text(encoding="utf-8")
    tracker = (root / module.B42_TREE / module.LUA_RELATIVES[1]).read_text(encoding="utf-8")
    client = (root / module.B42_TREE / module.LUA_RELATIVES[2]).read_text(encoding="utf-8")
    assert "ModData.getOrCreate" not in main + tracker + client
    assert "Events.OnInitGlobalModData" not in main + tracker + client
    assert "playerObj:getModData()" in main + tracker
    assert "BB_Achievements = achievements" in main
    assert "BB_Achievements_Tracker = tracker" in tracker
    assert "if achievements[name] == nil" in main
    assert "if tracker[field] == nil" in tracker
    assert "if created then" in main + tracker
    for achievement in ("guardinGnome", "waitASec", "pacifist", "iAmLegend", "openSesame", "gta"):
        assert f"BB_Achievements.{achievement} = {{ achieved = false }}" in main
    assert "SandboxVars.Achievements.ResetOnSwitch" not in client
    assert "ResetAchievements()" not in client
    assert "local player = playerObj or getPlayer()" in client
    assert "BB_Achievements_InitializeTracker(player)" in client
    barricade = root / module.B42_TREE / "media/lua/client/overrides/timed actions/BB_Achievements_Barricade.lua"
    assert barricade.read_text(encoding="utf-8") == (
        "BB_Achievements_Tracker.barricades = BB_Achievements_Tracker.barricades + 1\n"
    )

    before = {relative: (root / module.B42_TREE / relative).read_bytes() for relative in module.LUA_RELATIVES}
    assert not module.FIX["run"](ctx)
    assert before == {relative: (root / module.B42_TREE / relative).read_bytes() for relative in module.LUA_RELATIVES}
    assert messages[-1] == "Braven's Achievements: ALREADY PATCHED."


def test_inactive_item_and_wrong_mod_id_are_skipped(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "43-bravens-achievements-b42-persistence.py")
    workshop = tmp_path / "workshop"
    root = install_fixture(workshop, module, item_id="9999999999")
    original = (root / module.B42_TREE / module.LUA_RELATIVES[0]).read_bytes()
    ctx = fix_context(workshop)
    ctx["active_workshop_ids"] = ("1111111111",)
    assert not module.FIX["run"](ctx)
    assert (root / module.B42_TREE / module.LUA_RELATIVES[0]).read_bytes() == original

    wrong = install_fixture(workshop, module, item_id="2222222222", mod_id="Not_BB_Achievements")
    ctx["active_workshop_ids"] = ("2222222222",)
    assert not module.FIX["run"](ctx)
    assert (wrong / module.B42_TREE / module.LUA_RELATIVES[0]).read_bytes() == original


def test_unknown_or_mixed_upstream_is_blocked_without_mutation(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "43-bravens-achievements-b42-persistence.py")
    workshop = tmp_path / "workshop"
    root = install_fixture(workshop, module)
    client = root / module.B42_TREE / module.LUA_RELATIVES[2]
    client.write_text("unknown revision\n", encoding="utf-8")
    before = {relative: (root / module.B42_TREE / relative).read_bytes() for relative in module.LUA_RELATIVES}
    messages = []
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert before == {relative: (root / module.B42_TREE / relative).read_bytes() for relative in module.LUA_RELATIVES}
    assert any("BLOCKED / UPSTREAM CHANGED" in message for message in messages)

    client.write_text(upstream_files(module)[module.LUA_RELATIVES[2]], encoding="utf-8")
    main = root / module.B42_TREE / module.LUA_RELATIVES[0]
    main.write_text(module.plan_file(module.LUA_RELATIVES[0], main.read_text(encoding="utf-8"))[0], encoding="utf-8")
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert any("mixed patched and upstream Lua state" in message for message in messages)


def test_unsupported_modversion_is_blocked_without_mutation(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "43-bravens-achievements-b42-persistence.py")
    workshop = tmp_path / "workshop"
    root = install_fixture(workshop, module)
    info = root / "mod.info"
    info.write_text(info.read_text(encoding="utf-8").replace("modversion=1.3.0", "modversion=1.3.1"),
                    encoding="utf-8")
    before = (root / module.B42_TREE / module.LUA_RELATIVES[0]).read_bytes()
    messages = []
    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert (root / module.B42_TREE / module.LUA_RELATIVES[0]).read_bytes() == before
    assert any("supported BB_Achievements 1.3.0" in message for message in messages)


def test_production_fix_uses_only_common_workshop_discovery():
    source = (FIX_SCRIPTS / "43-bravens-achievements-b42-persistence.py").read_text(encoding="utf-8")
    assert "ctx[\"WORKSHOP\"]" in source
    assert "/home/" not in source
    assert "/mnt/" not in source
    assert "BRAVEN" not in source
