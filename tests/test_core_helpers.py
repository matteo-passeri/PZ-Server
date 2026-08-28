import importlib
from types import SimpleNamespace

import pytest

from conftest import ROOT, load_path_module


def test_audit_filters_optional_probe_blocks_and_keeps_real_animation(tmp_path):
    audit = load_path_module(ROOT / "audit-server-log.py")
    base = "/home/steam/steamapps/workshop/content/108600/123/mods/Vehicle Repair Overhaul"
    optional = f"java.nio.file.NoSuchFileException: {base}/common/media/AnimSets at UnixException.translateToIOException(null:-1)."
    frames = [
        "    at zombie.core.skinnedmodel.advancedanimation.AdvancedAnimator.searchFolders(AdvancedAnimator.java:1)",
        "    at zombie.core.skinnedmodel.advancedanimation.AdvancedAnimator.load(AdvancedAnimator.java:2)",
        "java.base/sun.nio.fs.UnixException.rethrowAsIOException(UnixException.java:111)",
        "  at java.base/sun.nio.fs.UnixException.translateToIOException(UnixException.java:92)",
    ]
    analysis = audit.analyze_optional_probe_blocks([optional, *frames], 0, 5)
    assert len(analysis.details) == 1
    assert analysis.suppressed_line_indexes == {0, 1, 2, 3, 4}
    assert audit.find_events([optional, *frames], 0, 5) == []
    assert audit.classify(frames[2]) is None
    assert audit.classify('LOG : Mod "damnlib" overrides media/animsets/player/foo.xml.') is None
    assert audit.classify("Animation: Warning.") is None
    assert audit.classify("ERROR: Could not find bone index for Bip01_Root")[0] == "ANIMATION / ASSET"
    real = f"java.nio.file.NoSuchFileException: {base}/42/media/AnimSets/player/missing.xml at UnixException.translateToIOException(null:-1)."
    assert audit.find_events([real], 0, 1)[0].category == "ANIMATION / ASSET"


def test_audit_report_uses_filtered_events_for_common_errors(tmp_path):
    audit = load_path_module(ROOT / "audit-server-log.py")
    source = tmp_path / "DebugLog-server.txt"
    source.write_text("fixture\n", encoding="utf-8")
    probe = "java.nio.file.NoSuchFileException: /x/steamapps/workshop/content/108600/123/mods/Foo/common/media/actiongroups at UnixException.translateToIOException(null:-1)."
    frames = [
        "java.base/sun.nio.fs.UnixException.rethrowAsIOException(UnixException.java:111)",
        "at java.base/sun.nio.fs.UnixException.translateToIOException(UnixException.java:92)",
    ]
    report = audit.format_report(source, [probe, *frames], "startup", 0, 3, None)
    assert "Suppressed optional animation directory probes: 1" in report
    assert "UnixException.rethrowAsIOException" not in report
    assert "UnixException.translateToIOException" not in report
    assert "Most common errors\nNone." in report


def test_startup_audit_selects_current_log_and_parses_podman_time(tmp_path, monkeypatch):
    startup = load_path_module(ROOT / "run-startup-audit.py")
    log = tmp_path / "2026-01-01_DebugLog-server.txt"
    log.write_text(startup.STARTED_MARKER, encoding="utf-8")
    assert startup.select_current_log(tmp_path, log.stat().st_mtime) == log
    assert startup.has_started_marker(log)
    monkeypatch.setattr(
        startup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='"2026-01-01T01:02:03.123456789Z"'),
    )
    assert startup.container_start_time("pz") > 0


def test_successful_mod_state_is_atomic_and_only_written_after_startup_marker(tmp_path, capsys):
    state = importlib.import_module("mod_active_state")
    startup = load_path_module(ROOT / "run-startup-audit.py")
    path = state.state_file(tmp_path)
    assert state.read_last_active_mods(path, lambda _: None) == []
    path.write_text("not json", encoding="utf-8")
    assert state.read_last_active_mods(path, lambda message: print(message)) == []
    assert "Ignoring malformed successful-mod state" in capsys.readouterr().out
    # A failed generation/startup never calls this function, so prior state
    # stays intact until the caller has observed SERVER STARTED.
    state.write_last_active_mods(path, ["Previous"])
    startup.record_successful_mod_state({"PZ_MOD_NAMES": "A;B;A"}, tmp_path)
    assert state.read_last_active_mods(path, lambda _: None) == ["A", "B"]


def test_failed_startup_does_not_replace_successful_mod_state(tmp_path):
    state = importlib.import_module("mod_active_state")
    startup = load_path_module(ROOT / "run-startup-audit.py")
    path = state.state_file(tmp_path)
    state.write_last_active_mods(path, ["Previous"])
    assert startup.wait_for_startup_log(
        tmp_path, 0, timeout=0, poll_interval=0, clock=lambda: 0, sleep=lambda _: None,
    ) is None
    assert state.read_last_active_mods(path, lambda _: None) == ["Previous"]


def test_world_dictionary_removed_mod_audit_uses_declared_fallback_only(tmp_path):
    audit = load_path_module(ROOT / "audit-server-log.py")
    source = tmp_path / "DebugLog-server.txt"
    source.write_text("fixture\n", encoding="utf-8")
    lines = [
        "ERROR: WorldDictionaryException",
        'removed = true modID = "SomeMod"',
        "Cannot load world due to WorldDictionary error",
        "ERROR: WorldDictionaryException",
        "removed = true modID = UnknownMod",
    ]
    assert audit.classify(lines[0])[0] == "WORLD DICTIONARY / REMOVED MOD"
    findings = audit.find_world_dictionary_removed_mods(lines, 0, len(lines))
    assert [finding.mod_id for finding in findings] == ["SomeMod", "UnknownMod"]
    report = audit.format_report(
        source, lines, "startup", 0, len(lines), None,
        {"SomeMod": "SomeModRemoved"},
    )
    assert "Known fallback: SomeModRemoved" in report
    assert "No declared fallback; manual investigation required." in report
    assert "UnknownModRemoved" not in report


def test_generator_parses_mod_info_and_orders_hard_rules(tmp_path):
    generator = load_path_module(ROOT / "generate-mod-list.py")
    info = tmp_path / "mod.info"
    info.write_text(
        "id=Foo\nloadmodafter=\\Bar;Baz,Qux\n"
        "require=LibraryA, LibraryB\nincompatible=BadA; BadB\n",
        encoding="utf-8",
    )
    parsed = generator.parse_mod_info(info)
    assert parsed["loadmodafter"] == ["Bar", "Baz", "Qux"]
    assert parsed["require"] == ["LibraryA", "LibraryB"]
    assert parsed["incompatible"] == ["BadA", "BadB"]
    assert generator.normalize_collection_ids(["1, 2", "2"]) == ["1", "2"]
    assert generator.reorder_mod_ids(
        ["third", "first", "second"],
        load_before=[("first", "second")],
        load_after=[],
        load_first=("first",),
        load_last=("third",),
    ) == ["first", "second", "third"]
    with pytest.raises(generator.ModLoadOrderError):
        generator.reorder_mod_ids(["a", "b"], [("a", "b"), ("b", "a")], [], (), ())


def test_mod_info_runtime_rules_validate_dependencies_conflicts_and_order():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    metadata = [{
        "workshop_id": "123",
        "mod_id": "Feature",
        "mod_info": "/workshop/123/mods/Feature/42/mod.info",
        "require": ["Library", "Missing"],
        "incompatible": ["Bad"],
        "loadmodafter": ["Library"],
        "loadmodbefore": ["Late"],
    }, {
        "workshop_id": "456",
        "mod_id": "Bad",
        "mod_info": "/workshop/456/mod.info",
        "require": [],
        "incompatible": ["Feature"],
        "loadmodafter": [],
        "loadmodbefore": [],
    }]
    edges, missing, conflicts = generator.mod_info_runtime_rules(
        ["Feature", "Library", "Late", "Bad"], metadata,
    )
    assert edges == [("Library", "Feature"), ("Feature", "Late")]
    assert missing == [{
        "mod_id": "Feature", "required_mod_id": "Missing", "workshop_id": "123",
        "source": "/workshop/123/mods/Feature/42/mod.info",
    }]
    assert conflicts == [{
        "mods": ["Bad", "Feature"], "reason": "declared incompatible in mod.info",
        "source": "mod.info", "workshop_id": "123",
        "mod_info": "/workshop/123/mods/Feature/42/mod.info",
    }]
    # require= is validation only, never a synthetic load-order edge.
    assert generator.mod_info_runtime_rules(["Feature", "Library"], [{
        **metadata[0], "require": ["Library"], "loadmodafter": [], "loadmodbefore": [],
    }])[0] == []


def test_mod_info_edges_deduplicate_with_curated_rules_and_keep_cycle_detection():
    generator = load_path_module(ROOT / "generate-mod-list.py")
    edges = generator.active_mod_load_order_edges(
        ["NeatUI_Framework", "CleanUI"],
        mod_info_edges=[("NeatUI_Framework", "CleanUI")],
    )
    assert edges.count(("NeatUI_Framework", "CleanUI")) == 1
    with pytest.raises(generator.ModLoadOrderError):
        generator.reorder_mod_ids(
            ["A", "B"],
            load_before=[("A", "B")],
            load_after=[],
            load_first=(),
            load_last=(),
            mod_info_edges=[("B", "A")],
        )


def test_update_checker_configuration_state_and_remote_diff(tmp_path):
    config = importlib.import_module("check_mod_updates.config")
    state = importlib.import_module("check_mod_updates.state")
    steam = importlib.import_module("check_mod_updates.steam")
    env = tmp_path / ".env"
    env.write_text("PZ_MOD_IDS=1; 2;1\n", encoding="utf-8")
    assert config.get_configured_workshop_ids(config.read_env(env)) == ["1", "2"]
    config.STATE_FILE = tmp_path / "state.json"
    state.save_state({"1": {"result": 1, "time_updated": 9, "title": "One"}}, ["1", "2"])
    assert state.load_state()["items"]["1"]["time_updated"] == 9
    updates, inaccessible = steam.find_updates(
        ["1", "2"],
        {"1": {"result": 1, "time_updated": 10, "title": "One"}},
        {"items": {"1": {"time_updated": 9}}},
    )
    assert updates[0]["id"] == "1"
    assert inaccessible == [("2", "no response from Steam")]


def test_server_state_and_rcon_player_parsing(monkeypatch):
    server = importlib.import_module("check_mod_updates.server")
    assert server.validate_fresh_container_state({"running": True, "restarting": False, "restart_count": 0}) is None
    with pytest.raises(RuntimeError):
        server.validate_fresh_container_state({"running": True, "restarting": False, "restart_count": 1})
    monkeypatch.setattr(server, "rcon_command", lambda command: "Players connected ( 3 )")
    assert server.get_player_count() == (3, "Players connected ( 3 )")


def test_vehicle_helpers_preserve_balanced_templates(tmp_path):
    helper = load_path_module(ROOT / "fix-scripts/_vehicle_compat.py")
    source = "template vehicle Old { part Door { } }"
    assert helper.balanced(source)
    assert helper.clone_template(source, "Old", "New").startswith("template vehicle New")
    target = tmp_path / "compat.txt"
    changed = helper.add_compatibility_templates(
        target,
        {"New": "template vehicle New { }"},
        {},
        lambda _: None,
        "test",
    )
    assert changed and "template vehicle New" in target.read_text(encoding="utf-8")
