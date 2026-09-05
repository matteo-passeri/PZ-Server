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


def test_always_exclude_resolves_neat_building_multi_mod_item():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    discovered = [
        "Neat_Building",
        "Neat_Building_Buildables_SESCompat",
        "Neat_Building_Railings",
        "Neat_Building_UIOnly",
    ]
    rules_file = generator.load_mod_rules(ROOT / "mod-rules.toml")

    selected, unresolved = generator.select_workshop_mod_ids(
        discovered, [], None, set(rules_file.always_exclude),
    )

    assert selected == ["Neat_Building"]
    assert unresolved == []
    active, _decisions, _conflicts = generator.resolve_mod_rules(selected, rules_file)
    assert active == ["Neat_Building"]


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


def test_removed_fallback_uses_physical_availability_after_selection():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    preference = generator.PreferRule(
        "Foo", ("FooRemoved",), removed_fallback="FooRemoved",
    )
    active, decisions, _ = generator.resolve_mod_rules(
        ["Foo"], rules(generator, prefer=(preference,)), {"Foo"},
        previous_active={"Foo"}, available_mod_ids={"Foo", "FooRemoved"},
    )
    assert active == ["FooRemoved"]
    assert decisions[-1]["status"] == "auto_removed_fallback"
    active, decisions, _ = generator.resolve_mod_rules(
        ["Foo"], rules(generator, always=("FooRemoved",), prefer=(preference,)), {"Foo"},
        previous_active={"Foo"}, available_mod_ids={"Foo", "FooRemoved"},
    )
    assert active == []
    assert decisions[-1]["reason"] == "excluded by project always_exclude"


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


def test_auto_detects_exact_removed_pairs_within_one_workshop_item():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo", "FooRemoved", "FooPatch", "OtherMod"]},
    ])
    assert [(rule.winner, rule.losers, rule.workshop_id) for rule in inferred] == [
        ("Foo", ("FooRemoved",), "1"),
    ]
    effective, diagnostics = generator.reconcile_prefer_rules((), inferred)
    assert generator.resolve_mod_rules(["Foo", "FooRemoved", "FooPatch", "OtherMod"], rules(generator, prefer=effective))[0] == ["Foo", "FooPatch", "OtherMod"]
    assert diagnostics[0]["status"] == "active_auto_rule"


def test_auto_detection_uses_discovered_ids_without_activating_unresolved_mods():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": [], "discovered_mod_ids": ["Foo", "FooRemoved", "FooPatch"]},
    ])
    assert [(rule.winner, rule.losers) for rule in inferred] == [("Foo", ("FooRemoved",))]
    effective, _ = generator.reconcile_prefer_rules((), inferred)
    # Discovery remains metadata until the existing Workshop selection process
    # provides IDs to the active candidate list.
    assert generator.resolve_mod_rules([], rules(generator, prefer=effective))[0] == []


def test_auto_removed_pairs_require_same_workshop_and_exact_case_sensitive_suffix():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    assert generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo"]},
        {"workshop_id": "2", "mod_ids": ["FooRemoved"]},
        {"workshop_id": "3", "mod_ids": ["Bar", "Bar_Removed", "Bar-Removed", "RemovedBar"]},
        {"workshop_id": "4", "mod_ids": ["Case", "caseremoved"]},
    ]) == ()
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "5", "mod_ids": ["Foo", "FooRemoved", "Bar", "BarRemoved"]},
    ])
    assert [(rule.winner, rule.losers) for rule in inferred] == [
        ("Foo", ("FooRemoved",)), ("Bar", ("BarRemoved",)),
    ]


def test_explicit_rules_override_or_disable_auto_pairs_without_duplicates():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo", "FooRemoved"]},
    ])
    explicit = generator.PreferRule("Foo", ("FooRemoved",), "known", removed_fallback="FooRemoved")
    effective, diagnostics = generator.reconcile_prefer_rules((explicit,), inferred)
    assert effective == (explicit,)
    assert diagnostics[0]["status"] == "superseded_by_explicit"
    active, decisions, _ = generator.resolve_mod_rules(
        ["Foo", "FooRemoved"], rules(generator, prefer=effective), {"Foo"},
        previous_active={"Foo"},
    )
    assert active == ["FooRemoved"]
    assert sum(item["status"] == "auto_removed_fallback" for item in decisions) == 1
    disabled = generator.PreferRule("Foo", ("FooRemoved",), enabled=False)
    effective, diagnostics = generator.reconcile_prefer_rules((disabled,), inferred)
    assert effective == (disabled,)
    assert diagnostics[0]["status"] == "suppressed_by_disabled_explicit"
    assert generator.resolve_mod_rules(["Foo", "FooRemoved"], rules(generator, prefer=effective))[0] == ["Foo", "FooRemoved"]


def test_unrelated_explicit_same_winner_coexists_with_auto_pair():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo", "FooRemoved"]},
    ])
    explicit = generator.PreferRule("Foo", ("Bar",), "independent preference")
    effective, diagnostics = generator.reconcile_prefer_rules((explicit,), inferred)
    assert effective == (explicit, inferred[0])
    assert diagnostics[0]["status"] == "active_auto_rule"
    assert generator.resolve_mod_rules(
        ["Foo", "FooRemoved", "Bar"], rules(generator, prefer=effective),
    )[0] == ["Foo"]


def test_explicit_multiple_losers_covers_inferred_pair():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo", "FooRemoved"]},
    ])
    explicit = generator.PreferRule("Foo", ("Bar", "FooRemoved"))
    effective, diagnostics = generator.reconcile_prefer_rules((explicit,), inferred)
    assert effective == (explicit,)
    assert diagnostics[0]["status"] == "superseded_by_explicit"


def test_contradictory_explicit_rule_suppresses_auto_pair_deterministically():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Foo", "FooRemoved"]},
    ])
    explicit = generator.PreferRule("FooRemoved", ("Foo",), "intentional reverse preference")
    effective, diagnostics = generator.reconcile_prefer_rules((explicit,), inferred)
    assert effective == (explicit,)
    assert diagnostics[0]["status"] == "superseded_by_explicit"
    assert generator.resolve_mod_rules(["Foo", "FooRemoved"], rules(generator, prefer=effective))[0] == ["FooRemoved"]


def test_auto_pair_does_not_create_historical_fallback():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = generator.detect_removed_variant_pairs([
        {"workshop_id": "1", "mod_ids": ["Bar", "BarRemoved"]},
    ])
    effective, _ = generator.reconcile_prefer_rules((), inferred)
    active, decisions, _ = generator.resolve_mod_rules(
        ["Bar", "BarRemoved"], rules(generator, prefer=effective), {"Bar"}, previous_active={"Bar"},
    )
    assert active == ["BarRemoved"]
    assert not any(item["status"] == "auto_removed_fallback" for item in decisions)


def test_effective_validation_detects_cycle_introduced_by_inferred_pair():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    explicit = (
        generator.PreferRule("FooRemoved", ("Bar",)),
        generator.PreferRule("Bar", ("Foo",)),
    )
    inferred = (generator.PreferRule("Foo", ("FooRemoved",), source="auto_removed_pair"),)
    effective, _ = generator.reconcile_prefer_rules(explicit, inferred)
    with pytest.raises(
        generator.ModRulesError,
        match="Bar -> Foo -> FooRemoved -> Bar",
    ):
        generator.validate_effective_prefer_rules(effective)


def test_effective_validation_keeps_non_cyclic_explicit_and_inferred_edges():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    explicit = (generator.PreferRule("Foo", ("Bar",)),)
    inferred = (generator.PreferRule("Foo", ("FooRemoved",), source="auto_removed_pair"),)
    effective, _ = generator.reconcile_prefer_rules(explicit, inferred)
    generator.validate_effective_prefer_rules(effective)
    assert effective == explicit + inferred


def test_suppressed_or_replaced_inferred_pairs_do_not_create_effective_cycles():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    inferred = (generator.PreferRule("Foo", ("FooRemoved",), source="auto_removed_pair"),)
    # The disabled matching explicit rule removes the inferred edge, so the
    # remaining rules do not form Foo -> FooRemoved -> Bar -> Foo.
    disabled = (
        generator.PreferRule("Foo", ("FooRemoved",), enabled=False),
        generator.PreferRule("FooRemoved", ("Bar",)),
        generator.PreferRule("Bar", ("Foo",)),
    )
    effective, _ = generator.reconcile_prefer_rules(disabled, inferred)
    generator.validate_effective_prefer_rules(effective)
    # Matching and reverse explicit rules likewise leave one edge only.
    matching = (generator.PreferRule("Foo", ("FooRemoved",)),)
    effective, _ = generator.reconcile_prefer_rules(matching, inferred)
    generator.validate_effective_prefer_rules(effective)
    assert effective == matching
    reverse = (generator.PreferRule("FooRemoved", ("Foo",)),)
    effective, _ = generator.reconcile_prefer_rules(reverse, inferred)
    generator.validate_effective_prefer_rules(effective)
    assert effective == reverse


def test_effective_validation_detects_transitive_cycle_and_skips_disabled_rules():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    explicit = (
        generator.PreferRule("A", ("B",)),
        generator.PreferRule("C", ("D",)),
        generator.PreferRule("D", ("A",)),
        generator.PreferRule("Unused", ("A",), enabled=False),
    )
    inferred = (generator.PreferRule("B", ("C",), source="auto_removed_pair"),)
    effective, _ = generator.reconcile_prefer_rules(explicit, inferred)
    with pytest.raises(generator.ModRulesError, match="A -> B -> C -> D -> A"):
        generator.validate_effective_prefer_rules(effective)


def selection_record(workshop_id, discovered, current=(), explicit=()):
    return {
        "workshop_id": workshop_id,
        "discovered_mod_ids": list(discovered),
        "mod_ids": list(current),
        "explicit_mod_ids": list(explicit),
    }


def select(generator, records, selection_rules, blacklist=(), forced=(), previous=()):
    return generator.resolve_mod_selection(
        records, selection_rules, set(blacklist), list(forced), set(previous),
    )


def final_mod_names(
    generator, records, blacklist=(), project_rules=None, selection_rules=None,
):
    """Exercise selection through the final value written to PZ_MOD_NAMES."""
    blacklist = set(blacklist)
    selected, _decisions, _pairs, _replacements = select(
        generator, records, selection_rules or {}, blacklist=blacklist,
    )
    inferred = generator.detect_removed_variant_pairs(records)
    explicit = () if project_rules is None else project_rules.prefer
    effective, _diagnostics = generator.reconcile_prefer_rules(explicit, inferred)
    rules_file = project_rules or rules(generator)
    resolved, _decisions, _conflicts = generator.resolve_mod_rules(
        selected,
        generator.ModRules(rules_file.always_exclude, effective, rules_file.conflict),
        blacklist,
        available_mod_ids={
            mod_id
            for record in records
            for mod_id in record["discovered_mod_ids"]
        },
    )
    return ";".join(generator.reorder_mod_ids(resolved))


def test_selection_auto_discovers_exact_removed_pairs_without_false_matches():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    pairs = generator.discover_removed_pairs("1", ["Foo", "FooRemoved"])
    assert pairs == [{
        "workshop_id": "1", "base_mod_id": "Foo", "removed_mod_id": "FooRemoved",
    }]
    selected, decisions, auto_pairs, replacements = select(
        generator, [selection_record("1", ["Foo", "FooRemoved"])], {},
    )
    assert selected == ["Foo"]
    assert decisions[0]["reason"] == "auto_removed_pair"
    assert auto_pairs == pairs
    assert replacements == []
    assert generator.discover_removed_pairs(
        "2", ["Foo", "FooRemovedExtra", "Foo2", "Foo2RemovedExtra"]
    ) == []
    assert generator.discover_removed_pairs("3", ["Foo2", "FooRemoved"]) == []


@pytest.mark.parametrize(("discovered", "blacklist", "expected"), [
    (["Foo", "FooRemoved"], ["Foo"], "FooRemoved"),
    (["Foo", "FooRemoved"], ["FooRemoved"], "Foo"),
    (["Foo", "FooRemoved"], ["Foo", "FooRemoved"], ""),
    (["Foo"], ["Foo"], ""),
])
def test_blacklisted_removed_pair_reaches_final_mod_names(
    discovered, blacklist, expected,
):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    assert final_mod_names(
        generator, [selection_record("1", discovered)], blacklist,
    ) == expected


@pytest.mark.parametrize("workshop_id, base_mod_id", [
    ("3546314080", "Waterpipes"),
    ("3439305933", "FunctionalGutters"),
])
def test_real_removed_variants_reach_final_mod_names_without_forced_mods(
    workshop_id, base_mod_id,
):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    removed_mod_id = base_mod_id + "Removed"
    names = final_mod_names(
        generator,
        [selection_record(workshop_id, [base_mod_id, removed_mod_id])],
        [base_mod_id],
        generator.load_mod_rules(ROOT / "mod-rules.toml"),
    ).split(";")
    assert removed_mod_id in names
    assert base_mod_id not in names


def test_waterpipes_and_functional_gutters_removed_variants_share_final_mod_names():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    names = final_mod_names(
        generator,
        [
            selection_record("3546314080", ["Waterpipes", "WaterpipesRemoved"]),
            selection_record("3439305933", ["FunctionalGutters", "FunctionalGuttersRemoved"]),
        ],
        ["Waterpipes", "FunctionalGutters"],
        generator.load_mod_rules(ROOT / "mod-rules.toml"),
    ).split(";")
    assert "WaterpipesRemoved" in names
    assert "FunctionalGuttersRemoved" in names
    assert "Waterpipes" not in names
    assert "FunctionalGutters" not in names


def test_selection_curated_default_optional_and_exclusive_admin_override():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    selection_rules = {
        "1": {
            "mod_ids": ["Full", "Lite", "Extra"],
            "default": ["Full"],
            "optional": ["Extra"],
            "exclusive_groups": [["Full", "Lite"]],
        },
    }
    records = [selection_record("1", ["Full", "Lite", "Extra"])]
    assert select(generator, records, selection_rules)[0] == ["Full"]
    assert select(generator, records, selection_rules, forced=["Extra"])[0] == ["Full", "Extra"]
    assert select(generator, records, selection_rules, forced=["Lite"])[0] == ["Lite"]
    overridden = [selection_record("1", ["Full", "Lite", "Extra"], explicit=["Lite"])]
    assert select(generator, overridden, selection_rules)[0] == ["Lite"]
    with pytest.raises(generator.ModSelectionError, match="Conflicting Mod ID variants"):
        select(generator, records, selection_rules, forced=["Full", "Lite"])
    assert select(generator, records, selection_rules, blacklist=["Full"])[0] == []


def test_ultimate_towing_curated_default_and_administrator_overrides():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    workshop_id = "3790880431"
    discovered = ["UltimateTowing", "UltimateTowingZB"]
    records = [selection_record(workshop_id, discovered)]

    selected, _decisions, _pairs, _replacements = select(
        generator, records, generator.MOD_SELECTION_RULES,
    )
    workshop_items = ";".join(record["workshop_id"] for record in records)
    mods = final_mod_names(
        generator, records, selection_rules=generator.MOD_SELECTION_RULES,
    )
    assert selected == ["UltimateTowing"]
    assert workshop_items.split(";") == [workshop_id]
    assert mods.split(";") == ["UltimateTowing"]
    assert "UltimateTowingZB" not in mods.split(";")

    overridden = [selection_record(workshop_id, discovered, explicit=["UltimateTowingZB"])]
    assert select(
        generator, overridden, generator.MOD_SELECTION_RULES,
    )[0] == ["UltimateTowingZB"]
    assert select(
        generator, records, generator.MOD_SELECTION_RULES, forced=["UltimateTowingZB"],
    )[0] == ["UltimateTowingZB"]

    with pytest.raises(generator.ModSelectionError, match="Conflicting Mod ID variants"):
        select(
            generator,
            records,
            generator.MOD_SELECTION_RULES,
            forced=["UltimateTowing", "UltimateTowingZB"],
        )


def test_selection_condition_and_curated_removed_transition():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    selection_rules = {
        "1": {
            "mod_ids": ["Normal", "Compat"],
            "default": ["Normal"],
            "exclusive_groups": [["Normal", "Compat"]],
            "conditions": [{
                "if_active": ["Dependency"], "select": ["Compat"], "deselect": ["Normal"],
            }],
        },
        "2": {
            "mod_ids": ["X", "XRemoved"],
            "default": ["X"],
            "exclusive_groups": [["X", "XRemoved"]],
            "removed_replacements": {"X": "XRemoved"},
        },
        "3": {"mod_ids": ["Dependency"], "default": ["Dependency"]},
    }
    records = [
        selection_record("1", ["Normal", "Compat"]),
        selection_record("3", ["Dependency"]),
        selection_record("2", ["X", "XRemoved"]),
    ]
    selected, decisions, _pairs, replacements = select(generator, records, selection_rules)
    assert selected == ["Compat", "Dependency", "X"]
    assert decisions[0]["reason"] == "curated_condition"
    assert replacements == []
    selected, _decisions, _pairs, replacements = select(
        generator, records, selection_rules, blacklist=["X"], previous=["X"],
    )
    assert selected == ["Compat", "Dependency", "XRemoved"]
    assert replacements == [{
        "workshop_id": "2", "base_mod_id": "X", "replacement_mod_id": "XRemoved",
        "reason": "previously_active_then_removed", "source": "curated_rule",
    }]


def test_selection_validation_and_phase_one_order_follow_selection():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    with pytest.raises(generator.ModSelectionError, match="selects and deselects"):
        generator.validate_mod_selection_rules({
            "1": {"mod_ids": ["A"], "conditions": [{
                "if_active": ["A"], "select": ["A"], "deselect": ["A"],
            }]},
        })
    with pytest.raises(generator.ModSelectionError, match="default Mod ID as optional"):
        generator.validate_mod_selection_rules({
            "1": {"mod_ids": ["A"], "default": ["A"], "optional": ["A"]},
        })
    selected, _decisions, _pairs, _replacements = select(
        generator,
        [
            selection_record("1", ["Normal", "Compat"]),
            selection_record("2", ["Framework"], current=["Framework"]),
        ],
        {"1": {
            "mod_ids": ["Normal", "Compat"], "default": ["Compat"],
            "exclusive_groups": [["Normal", "Compat"]],
        }},
    )
    assert selected == ["Compat", "Framework"]
    assert generator.reorder_mod_ids(
        selected, load_before=[("Framework", "Compat")], load_after=[], load_first=[], load_last=[],
    ) == ["Framework", "Compat"]
