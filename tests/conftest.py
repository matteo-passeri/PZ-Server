import hashlib
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX_SCRIPTS = ROOT / "fix-scripts"

for path in (ROOT, FIX_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_path_module(path: Path):
    """Load a script by path without invoking its command-line entry point."""
    name = "test_target_" + hashlib.sha1(str(path).encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fix_context(workshop: Path, log=None):
    """Return the minimal isolated context accepted by every local fix."""
    log = log or (lambda _message: None)

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def ensure_symlink(source: Path, destination: Path, link_target=None):
        if not source.exists():
            return "source_missing"
        if destination.is_symlink():
            return "present" if destination.samefile(source) else "blocked"
        if destination.exists():
            return "blocked"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(link_target or source.name, target_is_directory=source.is_dir())
        return "created"

    return {
        "WORKSHOP": workshop,
        "active_workshop_ids": (),
        "latest_pz_server_log": lambda: None,
        "log": log,
        "sha256": sha256,
        "ensure_symlink": ensure_symlink,
        "state": {"managed_files": {}},
    }
