import json
import struct

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


def test_log_driven_case_fix_rebases_container_workshop_paths_safely(tmp_path):
    module = load_path_module(FIX_DIR / "00-linux-animset-xml-case.py")
    workshop = tmp_path / "host/steamapps/workshop/content/108600"
    mod_root = workshop / "123/mods/Vehicle Repair Overhaul/42/media/scripts"
    mod_root.mkdir(parents=True)
    (mod_root / "test.lua").write_text("lua", encoding="utf-8")
    container_path = (
        "/home/steam/zomboid/steamapps/workshop/content/108600/123/mods/"
        "Vehicle Repair Overhaul/42/media/scripts/Test.lua"
    )
    host_path = str(mod_root / "Test.lua")
    expected_suffix = ("123", "mods", "Vehicle Repair Overhaul", "42", "media", "scripts", "Test.lua")
    assert module.relative_to_workshop(container_path, workshop, ("123",)) == expected_suffix
    assert module.relative_to_workshop(host_path, workshop, ("123",)) == expected_suffix
    assert module.resolve_case_only_path(host_path, workshop, ("123",))[0] == "resolved"
    assert module.relative_to_workshop(container_path.replace("/123/mods/", "/999/mods/"), workshop, ("123",)) is None
    assert module.relative_to_workshop(container_path.replace("/123/mods/", "/123/notmods/"), workshop, ("123",)) is None
    assert module.relative_to_workshop("/home/steam/zomboid/unrelated/108600/123/mods/Foo/a.lua", workshop, ("123",)) is None
    assert module.relative_to_workshop(container_path.replace("/scripts/", "/../scripts/"), workshop, ("123",)) is None
    outside = tmp_path / "outside"
    outside.mkdir()
    (workshop / "123/mods/Escaped").symlink_to(outside, target_is_directory=True)
    escaped = "/home/steam/zomboid/steamapps/workshop/content/108600/123/mods/Escaped/Foo.lua"
    assert module.resolve_case_only_path(escaped, workshop, ("123",))[0] == "outside_active_tree"

    log = tmp_path / "server.log"
    log.write_text(f"java.nio.file.NoSuchFileException: {container_path}\n", encoding="utf-8")
    ctx = fix_context(workshop)
    ctx.update({"active_workshop_ids": ("123",), "latest_pz_server_log": lambda: log})
    assert module.FIX["run"](ctx)
    assert (mod_root / "Test.lua").is_symlink()
    assert not module.FIX["run"](ctx)

    zero = mod_root / "Missing.lua"
    assert module.resolve_case_only_path(str(zero), workshop, ("123",))[0] == "unfixable"
    (mod_root / "other.lua").write_text("one", encoding="utf-8")
    (mod_root / "OTHER.LUA").write_text("two", encoding="utf-8")
    assert module.resolve_case_only_path(str(mod_root / "Other.lua"), workshop, ("123",))[0] == "ambiguous"


def make_glb(document, binary):
    json_data = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_data += b" " * (-len(json_data) % 4)
    binary += b"\0" * (-len(binary) % 4)
    payload = (
        struct.pack("<I4s", len(json_data), b"JSON")
        + json_data
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    return struct.pack("<4sII", b"glTF", 2, 12 + len(payload)) + payload


def radarchery_document(module, name, action_stash_count=0, intended_last=False):
    unsupported_names = sorted(module.UNSUPPORTED_NODE_NAMES)
    intended = {
        "name": name,
        "samplers": [{"input": 0, "output": 0}],
        "channels": (
            [
                {"sampler": 0, "target": {"node": index, "path": "rotation"}}
                for index in range(len(unsupported_names))
            ]
            + [{"sampler": 0, "target": {"node": 5, "path": "scale"}}]
        ),
    }
    action_stash = [
        {"name": f"[Action Stash] {index}", "channels": []}
        for index in range(action_stash_count)
    ]
    animations = action_stash + [intended] if intended_last else [intended] + action_stash
    return {
        "asset": {"version": "2.0"},
        "nodes": ([{"name": name} for name in unsupported_names]
                  + [{"name": "Bip01_Spine"}]),
        "skins": [{"joints": [5]}],
        "accessors": [{"bufferView": 0}],
        "bufferViews": [{"buffer": 0, "byteLength": 4}],
        "buffers": [{"byteLength": 4}],
        "meshes": [{"primitives": []}],
        "materials": [{"name": "unchanged"}],
        "animations": animations,
    }


def radarchery_path(workshop, module, name="bow"):
    path = workshop / module.WORKSHOP_ID / module.BOB_RELATIVE / f"{name}.glb"
    path.parent.mkdir(parents=True)
    return path


def active_radarchery_context(workshop, module, log=None):
    ctx = fix_context(workshop, log)
    ctx["active_workshop_ids"] = (module.WORKSHOP_ID,)
    return ctx


@pytest.mark.parametrize("intended_last", (False, True), ids=("intended-first", "intended-last"))
def test_radarchery_glb_fix_removes_action_stash_and_named_channels(tmp_path, intended_last):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = radarchery_path(workshop, module)
    path.write_bytes(make_glb(radarchery_document(module, path.stem, 3, intended_last), b"\x01\x02\x03\x04"))
    before_document, before_chunks = module.parse_glb(path.read_bytes())

    messages = []
    assert module.FIX["run"](active_radarchery_context(workshop, module, messages.append))
    after_data = path.read_bytes()
    after_document, after_chunks = module.parse_glb(after_data)
    assert [animation["name"] for animation in after_document["animations"]] == [path.stem]
    assert len(after_document["animations"][0]["channels"]) == 1
    assert after_document["animations"][0]["channels"][0]["target"]["node"] == 5
    for section in module.PROTECTED_SECTIONS:
        assert after_document[section] == before_document[section]
    assert after_chunks[1:] == before_chunks[1:]
    assert "files changed=1; Action Stash animations removed=3; channels removed=5" in messages[-1]

    assert not module.FIX["run"](active_radarchery_context(workshop, module, messages.append))
    assert path.read_bytes() == after_data
    assert "files changed=0; Action Stash animations removed=0; channels removed=0" in messages[-1]


def test_radarchery_glb_fix_does_not_rewrite_already_clean_file(tmp_path):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = radarchery_path(workshop, module)
    document = radarchery_document(module, path.stem)
    document["animations"][0]["channels"] = [{"sampler": 0, "target": {"node": 5, "path": "scale"}}]
    original = make_glb(document, b"\x01\x02\x03\x04")
    path.write_bytes(original)

    assert not module.FIX["run"](active_radarchery_context(workshop, module))
    assert path.read_bytes() == original


@pytest.mark.parametrize("kind", ("unexpected", "missing", "duplicate"))
def test_radarchery_glb_fix_refuses_unexpected_animation_sets(tmp_path, kind):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = radarchery_path(workshop, module)
    document = radarchery_document(module, path.stem, 1)
    if kind == "unexpected":
        document["animations"].append({"name": "RealAnimation", "channels": []})
    elif kind == "missing":
        document["animations"][0]["name"] = "OtherAnimation"
    else:
        document["animations"].append(json.loads(json.dumps(document["animations"][0])))
    original = make_glb(document, b"\x01\x02\x03\x04")
    path.write_bytes(original)

    assert not module.FIX["run"](active_radarchery_context(workshop, module))
    assert path.read_bytes() == original


def test_radarchery_glb_fix_refuses_invalid_channel_node_without_partial_repair(tmp_path):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = radarchery_path(workshop, module)
    document = radarchery_document(module, path.stem, 1)
    document["animations"][0]["channels"][0]["target"]["node"] = 999
    original = make_glb(document, b"\x01\x02\x03\x04")
    path.write_bytes(original)

    assert not module.FIX["run"](active_radarchery_context(workshop, module))
    assert path.read_bytes() == original


def test_radarchery_glb_fix_skips_inactive_workshop(tmp_path):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = radarchery_path(workshop, module)
    original = make_glb(radarchery_document(module, path.stem, 1), b"\x01\x02\x03\x04")
    path.write_bytes(original)
    messages = []

    assert not module.FIX["run"](fix_context(workshop, messages.append))
    assert path.read_bytes() == original
    assert messages == ["RadArchery: Workshop 3775407541 is not active; skip."]


def test_radarchery_glb_fix_leaves_malformed_file_untouched(tmp_path):
    module = load_path_module(FIX_DIR / "40-radarchery-bob-glb-channels.py")
    workshop = tmp_path / "workshop"
    path = workshop / module.WORKSHOP_ID / module.BOB_RELATIVE / "broken.glb"
    path.parent.mkdir(parents=True)
    original = b"not a GLB"
    path.write_bytes(original)
    messages = []

    assert not module.FIX["run"](active_radarchery_context(workshop, module, messages.append))
    assert path.read_bytes() == original
    assert "blocked; leaving broken.glb untouched" in messages[0]
