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


def kseries_path(workshop, version):
    return (
        workshop
        / "3161951724/mods/76chevyKseries"
        / version
        / "media/scripts/vehicles/template_CH76_spareTires.txt"
    )


def install_kseries(workshop, version, content):
    path = kseries_path(workshop, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
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
    messages = []
    ctx = fix_context(workshop, messages.append)
    ctx["active_mod_ids"] = ("AquaTsarOptionalBoat",)

    assert not module.FIX["run"](ctx)
    assert path.read_bytes() == b"template = ApiBoatAirbag,\n"
    assert any("Aquatsar detected" in message for message in messages)


def test_motorclub_patches_when_aquatsar_is_installed_but_inactive(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    path = install_waverunner(workshop, module, "42.13", b"template = ApiBoatAirbag,\n")
    cached_info = workshop / "999/mods/AquaTsar/42/mod.info"
    cached_info.parent.mkdir(parents=True)
    cached_info.write_text("name=AquaTsar\nid=AquaTsar\n", encoding="utf-8")
    ctx = fix_context(workshop)
    ctx["active_mod_ids"] = ("UnrelatedActiveMod",)

    assert module.FIX["run"](ctx)
    assert path.read_bytes() == b""


def test_kseries_fixes_only_bad_42_20_parent_template(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    path = install_kseries(
        workshop,
        "42.20",
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = DAMNSpareTireRoof,\n}\n",
    )

    assert module.FIX["run"](fix_context(workshop))
    assert path.read_text(encoding="utf-8") == (
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = CH76SpareTireRoof,\n}\n"
    )


def test_kseries_correct_42_20_and_42_13_are_left_unchanged(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    correct = install_kseries(
        workshop,
        "42.20",
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = CH76SpareTireRoof,\n}\n",
    )
    legacy = install_kseries(
        workshop,
        "42.13",
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = DAMNSpareTireRoof,\n}\n",
    )

    assert not module.FIX["run"](fix_context(workshop))
    assert correct.read_text(encoding="utf-8") == (
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = CH76SpareTireRoof,\n}\n"
    )
    assert "DAMNSpareTireRoof" in legacy.read_text(encoding="utf-8")


def test_kseries_blocks_unexpected_42_20_parent_template_structure(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "32-vehicle-b42-regression-fixes.py")
    workshop = tmp_path / "workshop"
    content = (
        "template vehicle CH76SpareTireRoofDually\n{\n"
        "    template! = DAMNSpareTireRoof,\n"
        "    template! = CH76SpareTireRoof,\n}\n"
    )
    path = install_kseries(workshop, "42.20", content)

    assert not module.FIX["run"](fix_context(workshop))
    assert path.read_text(encoding="utf-8") == content
