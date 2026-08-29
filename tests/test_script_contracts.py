import importlib
import py_compile

import pytest

from conftest import FIX_SCRIPTS, ROOT, load_path_module


PATH_MODULES = (
    "apply-local-fixes.py",
    "audit-server-log.py",
    "check-mod-updates.py",
    "generate-mod-list.py",
    "mod_active_state.py",
    "run-startup-audit.py",
    "verify-vehicle-compat.py",
    "fix-scripts/00-linux-animset-xml-case.py",
    "fix-scripts/10-weldingrodmod-craft-plaster.py",
    "fix-scripts/20-companion-dogs.py",
    "fix-scripts/21-companion-dogs-animsets-case.py",
    "fix-scripts/22-car-roof-fix-animsets-case.py",
    "fix-scripts/23-hot-brass-linux-case.py",
    "fix-scripts/24-ebf-chainsaw-linux-case.py",
    "fix-scripts/30-damnlib-vehicle-template-compat.py",
    "fix-scripts/31-ki5-vehicle-template-compat.py",
    "fix-scripts/32-vehicle-b42-regression-fixes.py",
    "fix-scripts/40-radarchery-bob-glb-channels.py",
    "fix-scripts/60-door-unlock-from-inside-force-locked-v2.py",
    "fix-scripts/_vehicle_compat.py",
)
PACKAGE_MODULES = (
    "check_mod_updates",
    "check_mod_updates.config",
    "check_mod_updates.runner",
    "check_mod_updates.server",
    "check_mod_updates.state",
    "check_mod_updates.steam",
)


@pytest.mark.parametrize("relative", PATH_MODULES)
def test_path_script_compiles_and_imports_without_running_cli(relative):
    path = ROOT / relative
    py_compile.compile(path, doraise=True)
    module = load_path_module(path)
    if path.parent == FIX_SCRIPTS and not path.name.startswith("_"):
        assert isinstance(module.FIX, dict)
        assert module.FIX["name"]
        assert callable(module.FIX["run"])


@pytest.mark.parametrize("module_name", PACKAGE_MODULES)
def test_package_module_imports(module_name):
    assert importlib.import_module(module_name)
