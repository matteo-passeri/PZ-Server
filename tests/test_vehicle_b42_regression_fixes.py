import os
import stat

from conftest import FIX_SCRIPTS, fix_context, load_path_module


def motorclub_path(workshop, module, version):
    return (
        workshop
        / module.MOTORCLUB_WORKSHOP_ID
        / "mods"
        / module.MOTORCLUB_MOD_NAME
        / version
        / module.MOTORCLUB_WAVERUNNER_RELATIVE
    )


def install_waverunner(workshop, module, version, content):
    path = motorclub_path(workshop, module, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_motorclub_removes_only_api_boat_airbag_and_preserves_file_metadata(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    original = (
        b"vehicle Waverunner\r\n{\r\n"
        b"  template = ApiBoatAirbag,  \r\n"
        b"  template = ApiBoatSomethingElse,\r\n}\r\n"
    )
    path = install_waverunner(workshop, module, "common", original)
    os.chmod(path, 0o640)
    before = path.stat()

    assert module.FIX["run"](fix_context(workshop))
    assert path.read_bytes() == (
        b"vehicle Waverunner\r\n{\r\n"
        b"  template = ApiBoatSomethingElse,\r\n}\r\n"
    )
    after = path.stat()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)

    assert not module.FIX["run"](fix_context(workshop))


def test_motorclub_patches_every_present_version_and_skips_missing_versions(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    common = install_waverunner(workshop, module, "common", b"template = ApiBoatAirbag,\n")
    v4215 = install_waverunner(workshop, module, "42.15", b"\ttemplate=ApiBoatAirbag,\n")

    assert module.FIX["run"](fix_context(workshop))
    assert common.read_bytes() == b""
    assert v4215.read_bytes() == b""


def test_motorclub_leaves_references_unchanged_when_aquatsar_is_active(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    path = install_waverunner(workshop, module, "42.13", b"template = ApiBoatAirbag,\n")
    aquatsar_info = workshop / "999/mods/OptionalBoat/42/mod.info"
    aquatsar_info.parent.mkdir(parents=True)
    aquatsar_info.write_text("name=AquaTsar Optional Boat\nid=BoatAddon\n", encoding="utf-8")
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx["active_workshop_ids"] = ("999",)

    assert not module.FIX["run"](ctx)
    assert path.read_bytes() == b"template = ApiBoatAirbag,\n"
    assert any("Aquatsar detected" in message for message in messages)
