from conftest import ROOT, load_path_module


def test_update_existing_key(tmp_path):
    editor = load_path_module(ROOT / "config_editor.py")
    config = tmp_path / "server.ini"
    config.write_text("Foo=1\nBar=2\n", encoding="utf-8")

    editor.update_config_file(config, "Bar", "updated")

    assert config.read_text(encoding="utf-8") == "Foo=1\nBar=updated\n"


def test_append_missing_key_to_file_with_final_newline(tmp_path):
    editor = load_path_module(ROOT / "config_editor.py")
    config = tmp_path / "server.ini"
    config.write_text("Foo=1\n", encoding="utf-8")

    editor.update_config_file(config, "Bar", "2")

    assert config.read_text(encoding="utf-8") == "Foo=1\nBar=2\n"


def test_append_missing_key_to_file_without_final_newline(tmp_path):
    editor = load_path_module(ROOT / "config_editor.py")
    config = tmp_path / "server.ini"
    config.write_text("Foo=1\nChatMessageSlowModeTime=3", encoding="utf-8")

    editor.update_config_file(config, "AntiCheatProtectionType21", "false")

    assert config.read_text(encoding="utf-8") == (
        "Foo=1\nChatMessageSlowModeTime=3\nAntiCheatProtectionType21=false\n"
    )


def test_append_missing_key_to_empty_file(tmp_path):
    editor = load_path_module(ROOT / "config_editor.py")
    config = tmp_path / "server.ini"
    config.write_text("", encoding="utf-8")

    editor.update_config_file(config, "Bar", "2")

    assert config.read_text(encoding="utf-8") == "Bar=2\n"


def test_repeated_update_does_not_duplicate_key(tmp_path):
    editor = load_path_module(ROOT / "config_editor.py")
    config = tmp_path / "server.ini"
    config.write_text("Foo=1", encoding="utf-8")

    editor.update_config_file(config, "Bar", "2")
    editor.update_config_file(config, "Bar", "2")

    assert config.read_text(encoding="utf-8") == "Foo=1\nBar=2\n"
