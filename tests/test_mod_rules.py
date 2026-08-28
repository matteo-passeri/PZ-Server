import pytest

from conftest import ROOT, load_path_module


def rules(generator, always=(), prefer=(), conflict=()):
    return generator.ModRules(tuple(always), tuple(prefer), tuple(conflict))


def test_prefer_uses_evolving_active_set_and_admin_blacklist():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    preference = generator.PreferRule("WorkingGutters", ("WorkingGuttersRemoved",), "variants")
    config = rules(generator, prefer=(preference,))
    assert generator.resolve_mod_rules(["WorkingGutters", "WorkingGuttersRemoved"], config)[0] == ["WorkingGutters"]
    assert generator.resolve_mod_rules(
        ["WorkingGutters", "WorkingGuttersRemoved"], config, {"WorkingGutters"}
    )[0] == ["WorkingGuttersRemoved"]
    assert generator.resolve_mod_rules(["WorkingGuttersRemoved"], config)[0] == ["WorkingGuttersRemoved"]
    assert generator.resolve_mod_rules(["WorkingGutters"], config)[0] == ["WorkingGutters"]


def test_rules_exclusions_conflicts_disabled_and_deterministic_order():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    config = rules(
        generator,
        always=("Obsolete",),
        prefer=(
            generator.PreferRule("A", ("B", "C", "D"), "A wins"),
            generator.PreferRule("B", ("C",)),
            generator.PreferRule("Disabled", ("Kept",), enabled=False),
        ),
        conflict=(generator.ConflictRule(("A", "Conflict"), "manual choice required"),),
    )
    active, decisions, conflicts = generator.resolve_mod_rules(
        ["A", "B", "C", "D", "Obsolete", "Conflict", "Disabled", "Kept", "A"], config
    )
    assert active == ["A", "Conflict", "Disabled", "Kept"]
    assert {item["mod_id"] for item in decisions if item["reason"] == "superseded"} == {"B", "C", "D"}
    assert any(item["reason"] == "project always_exclude" for item in decisions)
    assert conflicts == [{"mods": ["A", "Conflict"], "reason": "manual choice required"}]


def test_chained_prefer_does_not_consult_original_collection_set():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    config = rules(generator, prefer=(
        generator.PreferRule("A", ("B",)),
        generator.PreferRule("B", ("C",)),
    ))
    assert generator.resolve_mod_rules(["A", "B", "C"], config)[0] == ["A", "C"]


def test_rules_validation_and_prefer_cycle(tmp_path):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    cyclic = tmp_path / "rules.toml"
    cyclic.write_text("""[mods]\n[[mods.prefer]]\nwinner = 'A'\nlosers = ['B']\n[[mods.prefer]]\nwinner = 'B'\nlosers = ['A']\n""", encoding="utf-8")
    with pytest.raises(generator.ModRulesError, match="prefer cycle: A -> B -> A"):
        generator.load_mod_rules(cyclic)
    malformed = tmp_path / "bad.toml"
    malformed.write_text("[mods]\nalways_exclude = ['A', 'A']\n", encoding="utf-8")
    with pytest.raises(generator.ModRulesError, match="duplicate always_exclude"):
        generator.load_mod_rules(malformed)


def test_rules_file_and_offline_cli(capsys, monkeypatch):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    loaded = generator.load_mod_rules(ROOT / "mod-rules.toml")
    assert "EQUIPMENT_UI" in loaded.always_exclude
    monkeypatch.setattr("sys.argv", ["generate-mod-list.py", "--validate-rules"])
    assert generator.main() == 0
    assert "Rules OK" in capsys.readouterr().out


def test_multi_mod_workshop_keeps_other_active_mod_and_forced_ids_are_explicit():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    # Workshop selection reports both IDs; filtering happens later at Mod-ID
    # level, so its Workshop item can stay for A/shared assets.
    assert generator.select_workshop_mod_ids(["A", "B"], [], ["A", "B"])[0] == ["A", "B"]
    config = rules(generator, always=("B",))
    active, decisions, _ = generator.resolve_mod_rules(["A", "B"], config, forced=["Forced"])
    assert active == ["A", "Forced"]
    assert decisions[-1] == {"mod_id": "Forced", "status": "included", "reason": "manual forced"}


def test_contradictory_administrator_overrides_are_reported(tmp_path, capsys):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    env = tmp_path / ".env"
    env.write_text("""PZ_APP_ID=108600
PZ_DEFAULT_COLLECTION_ID=1
PZ_COLLECTION_API=https://example.invalid/collection
PZ_DETAILS_API=https://example.invalid/details
PZ_USER_AGENT=test
PZ_BACKUPS_TO_KEEP=1
PZ_DEDICATED_SERVER_DIR=/tmp/zomboid
PZ_MANAGED_ENV_KEYS=PZ_MOD_IDS,PZ_MOD_NAMES,PZ_MAP_NAMES
PZ_MOD_ID_OVERRIDES={}
PZ_MOD_BLACKLIST_MODS=SomeMod
PZ_MOD_FORCED_MODS=SomeMod
PZ_MOD_BLACKLIST_WORKSHOP=123
PZ_MOD_FORCED_WORKSHOP=123
""", encoding="utf-8")
    generator.load_configuration(env)
    stderr = capsys.readouterr().err
    assert "both blacklists and forces Mod IDs: SomeMod" in stderr
    assert "both blacklists and forces Workshop IDs: 123" in stderr


def test_removed_fallback_requires_previous_successful_winner():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    preference = generator.PreferRule(
        "FunctionalGutters", ("FunctionalGuttersRemoved",),
        "save compatibility", removed_fallback="FunctionalGuttersRemoved",
    )
    config = rules(generator, prefer=(preference,))
    active, decisions, _ = generator.resolve_mod_rules(
        ["FunctionalGutters", "FunctionalGuttersRemoved"], config,
        {"FunctionalGutters"}, previous_active={"FunctionalGutters"},
    )
    assert active == ["FunctionalGuttersRemoved"]
    assert decisions[-1]["status"] == "auto_removed_fallback"
    # Existing prefer semantics leave an independently discovered loser alone
    # when the winner is blacklisted, but no automatic fallback is claimed.
    active, decisions, _ = generator.resolve_mod_rules(
        ["FunctionalGutters", "FunctionalGuttersRemoved"], config,
        {"FunctionalGutters"}, previous_active=set(),
    )
    assert active == ["FunctionalGuttersRemoved"]
    assert not any(item["status"] == "auto_removed_fallback" for item in decisions)


def test_removed_fallback_blocked_and_unavailable_are_diagnostic():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    preference = generator.PreferRule("A", ("ARemoved",), removed_fallback="ARemoved")
    config = rules(generator, prefer=(preference,))
    active, decisions, _ = generator.resolve_mod_rules(
        ["A", "ARemoved"], config, {"A", "ARemoved"}, previous_active={"A"},
    )
    assert active == []
    assert decisions[-1]["status"] == "fallback_blocked_by_admin"
    active, decisions, _ = generator.resolve_mod_rules(
        ["A"], config, {"A"}, previous_active={"A"},
    )
    assert active == []
    assert decisions[-1]["status"] == "fallback_unavailable"


def test_disabled_prefer_has_no_fallback_effect_and_forced_behavior_is_unchanged():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    preference = generator.PreferRule("A", ("ARemoved",), enabled=False, removed_fallback="ARemoved")
    active, decisions, _ = generator.resolve_mod_rules(
        ["A", "ARemoved"], rules(generator, prefer=(preference,)), {"A"},
        forced=["Forced"], previous_active={"A"},
    )
    assert active == ["ARemoved", "Forced"]
    assert decisions[-1]["reason"] == "manual forced"


@pytest.mark.parametrize("rule_text, message", [
    ("removed_fallback = ''", "removed_fallback"),
    ("removed_fallback = 'A'", "is the winner"),
    ("removed_fallback = 'C'", "must appear in losers"),
])
def test_removed_fallback_validation(tmp_path, rule_text, message):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    path = tmp_path / "rules.toml"
    path.write_text(f"[mods]\n[[mods.prefer]]\nwinner = 'A'\nlosers = ['B']\n{rule_text}\n", encoding="utf-8")
    with pytest.raises(generator.ModRulesError, match=message):
        generator.load_mod_rules(path)
