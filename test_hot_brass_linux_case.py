import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parent / "fix-scripts" / "23-hot-brass-linux-case.py"
SPEC = importlib.util.spec_from_file_location("hot_brass_linux_case", SCRIPT_PATH)
assert SPEC and SPEC.loader
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)


class HotBrassLinuxCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workshop = Path(self.tmp.name)
        self.logs: list[str] = []
        self.mod_root = self.workshop / FIX.WORKSHOP_ID / "mods" / FIX.MOD_DIRECTORY
        self.active_tree = self.create_version("42.15")
        self.actions = self.active_tree / "media" / "AnimSets" / "player" / "actions"
        self.actions.mkdir(parents=True)
        for name in ("LoadFAL_HB.xml", "RackShotgunSemi_HB.xml", "alreadylowercase.xml"):
            (self.actions / name).write_text("<animNode />")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_version(self, name: str) -> Path:
        version = self.mod_root / name
        (version / "media" / "AnimSets").mkdir(parents=True, exist_ok=True)
        return version

    def run_fix(self) -> bool:
        return FIX.run({"WORKSHOP": self.workshop, "log": self.logs.append})

    def test_creates_lowercase_root_animsets_and_xml_aliases(self) -> None:
        self.assertTrue(self.run_fix())

        lowercase_root = self.mod_root.parent / FIX.MOD_DIRECTORY.lower()
        self.assertTrue(lowercase_root.is_symlink())
        self.assertEqual(lowercase_root.readlink(), Path(FIX.MOD_DIRECTORY))
        self.assertTrue(lowercase_root.samefile(self.mod_root))

        animsets = self.active_tree / "media" / "animsets"
        self.assertTrue(animsets.is_symlink())
        self.assertEqual(animsets.readlink(), Path("AnimSets"))
        self.assertTrue(animsets.samefile(self.active_tree / "media" / "AnimSets"))

        for original in ("LoadFAL_HB.xml", "RackShotgunSemi_HB.xml"):
            alias = self.actions / original.lower()
            self.assertTrue(alias.is_symlink())
            self.assertEqual(alias.readlink(), Path(original))
            self.assertTrue(alias.samefile(self.actions / original))
        self.assertFalse((self.actions / "alreadylowercase.xml").is_symlink())

    def test_second_run_is_idempotent(self) -> None:
        self.assertTrue(self.run_fix())
        aliases = [
            self.mod_root.parent / FIX.MOD_DIRECTORY.lower(),
            self.active_tree / "media" / "animsets",
            self.actions / "loadfal_hb.xml",
            self.actions / "rackshotgunsemi_hb.xml",
        ]
        before = [path.lstat().st_ino for path in aliases]

        self.assertFalse(self.run_fix())
        self.assertEqual([path.lstat().st_ino for path in aliases], before)

    def test_upstream_lowercase_xml_file_is_left_untouched(self) -> None:
        upstream_file = self.actions / "rackshotgunsemi_hb.xml"
        upstream_file.write_text("upstream")

        self.assertTrue(self.run_fix())
        self.assertFalse(upstream_file.is_symlink())
        self.assertEqual(upstream_file.read_text(), "upstream")
        self.assertTrue(any("upstream lowercase XML file exists" in line for line in self.logs))

    def test_wrong_xml_symlink_is_not_replaced(self) -> None:
        self.assertTrue(self.run_fix())
        alias = self.actions / "rackshotgunsemi_hb.xml"
        alias.unlink()
        alias.symlink_to("unexpected.xml")

        self.assertFalse(self.run_fix())
        self.assertEqual(alias.readlink(), Path("unexpected.xml"))
        self.assertTrue(any("unexpected symlink target" in line for line in self.logs))

    def test_upstream_lowercase_mod_directory_is_left_untouched(self) -> None:
        lowercase_root = self.mod_root.parent / FIX.MOD_DIRECTORY.lower()
        lowercase_root.mkdir()

        self.assertTrue(self.run_fix())
        self.assertTrue(lowercase_root.is_dir())
        self.assertFalse(lowercase_root.is_symlink())
        self.assertTrue(any("upstream lowercase mod-root path exists" in line for line in self.logs))

    def test_prefers_42_20_over_other_42_versions(self) -> None:
        preferred_tree = self.create_version("42.20")
        preferred_actions = preferred_tree / "media" / "AnimSets" / "player" / "actions"
        preferred_actions.mkdir(parents=True)
        (preferred_actions / "RackRifle_HB.xml").write_text("<animNode />")

        self.assertTrue(self.run_fix())
        self.assertTrue((preferred_tree / "media" / "animsets").is_symlink())
        self.assertTrue((preferred_actions / "rackrifle_hb.xml").is_symlink())
        self.assertFalse((self.active_tree / "media" / "animsets").exists())
        self.assertFalse((self.actions / "rackshotgunsemi_hb.xml").exists())

    def test_missing_mod_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs: list[str] = []
            self.assertFalse(FIX.run({"WORKSHOP": Path(tmp), "log": logs.append}))
            self.assertEqual(logs, ["HotBrass: mod not present; skip."])


if __name__ == "__main__":
    unittest.main()
