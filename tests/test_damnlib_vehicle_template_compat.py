import pytest

from conftest import FIX_SCRIPTS, fix_context, load_path_module


def mod_root(workshop, workshop_id, name):
    return workshop / workshop_id / "mods" / name


def install_mod(workshop, workshop_id, name, mod_id, version="42.20"):
    root = mod_root(workshop, workshop_id, name)
    info = root / version / "mod.info"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text(f"id={mod_id}\n", encoding="utf-8")
    return root


def install_reference(root, version, name):
    path = root / version / "media/scripts/vehicles/references.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"template = {name},\n", encoding="utf-8")
    return path


def install_damnlib(workshop, module):
    return install_mod(workshop, module.WORKSHOP_ID, module.MOD_NAME, "damnlib")


def compatibility_target(root, module):
    return root / module.ACTIVE_VERSION / "media/scripts/commonItems/ZZ_DAMN_42_20_Compatibility.txt"


def active_context(workshop, module, workshop_ids, mod_ids):
    ctx = fix_context(workshop)
    ctx["active_workshop_ids"] = tuple(workshop_ids)
    ctx["active_mod_ids"] = tuple(mod_ids)
    return ctx


@pytest.mark.parametrize("version", ("common", "42.0", "42.13", "42.20"))
def test_discovers_references_in_installed_active_script_versions(tmp_path, version):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    vehicle = install_mod(workshop, "200", "Vehicle", "VehicleMod")
    install_reference(vehicle, version, "DAMN76chevyK10mccoy")

    assert module.FIX["run"](active_context(
        workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    assert "DAMN76chevyK10mccoy" in compatibility_target(damnlib, module).read_text(encoding="utf-8")


def test_explicit_placeholder_only_adds_referenced_names_inside_module_base(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    vehicle = install_mod(workshop, "200", "Vehicle", "VehicleMod")
    install_reference(vehicle, "42.20", "DAMN85chevyStepVanBlacksmith")

    assert module.FIX["run"](active_context(
        workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    text = compatibility_target(damnlib, module).read_text(encoding="utf-8")
    assert "module Base\n{" in text
    assert "template vehicle DAMN85chevyStepVanBlacksmith\n{\n/* */\n}" in text
    assert "DAMN85chevyStepVanZippeeMarket" not in text


def test_upstream_or_existing_compatibility_definition_is_not_duplicated(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    vehicle = install_mod(workshop, "200", "Vehicle", "VehicleMod")
    name = "DAMN85chevyImpalaPD"
    install_reference(vehicle, "42.20", name)
    upstream = damnlib / "42.20/media/scripts/vehicles/upstream.txt"
    upstream.parent.mkdir(parents=True)
    upstream.write_text(f"template vehicle {name}\n{{\n/* upstream */\n}}\n", encoding="utf-8")

    assert not module.FIX["run"](active_context(
        workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    assert not compatibility_target(damnlib, module).exists()

    upstream.unlink()
    target = compatibility_target(damnlib, module)
    target.parent.mkdir(parents=True)
    target.write_text(f"module Base\n{{\ntemplate vehicle {name}\n{{\n/* */\n}}\n}}\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    assert not module.FIX["run"](active_context(
        workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    assert target.read_text(encoding="utf-8") == before


def test_historical_safe_empty_template_is_recovered_but_part_template_is_rejected(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    vehicle = install_mod(workshop, "200", "Vehicle", "VehicleMod")
    install_reference(vehicle, "42.13", "DAMNHistoricalSafe")
    source = damnlib / "42.13/media/scripts/vehicles/history.txt"
    source.parent.mkdir(parents=True)
    source.write_text("template vehicle DAMNHistoricalSafe\n{\n/* */\n}\n", encoding="utf-8")

    ctx = active_context(workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod"))
    assert module.FIX["run"](ctx)
    assert "DAMNHistoricalSafe" in compatibility_target(damnlib, module).read_text(encoding="utf-8")

    blocked_workshop = tmp_path / "blocked-workshop"
    blocked_damnlib = install_damnlib(blocked_workshop, module)
    blocked_vehicle = install_mod(blocked_workshop, "200", "Vehicle", "VehicleMod")
    install_reference(blocked_vehicle, "42.20", "DAMNHistoricalWithPart")
    blocked = blocked_damnlib / "42.13/media/scripts/vehicles/history.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text(
        "template vehicle DAMNHistoricalWithPart\n{\npart Door\n{\n}\n}\n",
        encoding="utf-8",
    )
    assert not module.FIX["run"](active_context(
        blocked_workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    assert not compatibility_target(blocked_damnlib, module).exists()


def test_multiple_required_templates_share_one_balanced_module(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    vehicle = install_mod(workshop, "200", "Vehicle", "VehicleMod")
    path = install_reference(vehicle, "42.20", "DAMN76chevyK20fossoil")
    path.write_text(
        "template = DAMN76chevyK20fossoil,\n"
        "template = DAMN85chevyStepVanZippeeMarket,\n",
        encoding="utf-8",
    )

    assert module.FIX["run"](active_context(
        workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod")
    ))
    text = compatibility_target(damnlib, module).read_text(encoding="utf-8")
    assert text.count("module Base") == 1
    assert text.count("{") == text.count("}")


def test_inactive_workshop_and_lowercase_symlink_aliases_are_not_scanned_twice(tmp_path):
    module = load_path_module(FIX_SCRIPTS / "30-damnlib-vehicle-template-compat.py")
    workshop = tmp_path / "workshop"
    damnlib = install_damnlib(workshop, module)
    active_vehicle = install_mod(workshop, "200", "VehicleActual", "VehicleMod")
    script = install_reference(active_vehicle, "42.20", "DAMN76chevyK20helton")
    (active_vehicle.parent / "vehicleactual").symlink_to(active_vehicle, target_is_directory=True)
    inactive_vehicle = install_mod(workshop, "300", "InactiveVehicle", "InactiveMod")
    install_reference(inactive_vehicle, "42.20", "DAMN85chevyStepVanZippeeMarket")
    ctx = active_context(workshop, module, (module.WORKSHOP_ID, "200"), ("damnlib", "VehicleMod"))

    discovered = list(module.active_mod_script_files(
        workshop, ctx["active_workshop_ids"], ctx["active_mod_ids"]
    ))
    assert discovered.count(script) == 1
    assert module.FIX["run"](ctx)
    text = compatibility_target(damnlib, module).read_text(encoding="utf-8")
    assert "DAMN76chevyK20helton" in text
    assert "DAMN85chevyStepVanZippeeMarket" not in text
