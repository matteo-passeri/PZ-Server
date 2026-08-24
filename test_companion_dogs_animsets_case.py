import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parent / "fix-scripts" / "21-companion-dogs-animsets-case.py"
)
SPEC = importlib.util.spec_from_file_location("companion_dogs_case", SCRIPT_PATH)
assert SPEC and SPEC.loader
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)


class CompanionDogsAliasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workshop = Path(self.tmp.name)
        self.logs: list[str] = []
        self.media = (
            self.workshop
            / FIX.WORKSHOP_ID
            / "mods"
            / FIX.MOD_NAME
            / "42"
            / "media"
        )
        for name in ("lua", "AnimSets", "scripts", "models_X"):
            (self.media / name).mkdir(parents=True, exist_ok=True)

        pathfind = self.media / "AnimSets" / "raccoon" / "pathfind"
        pathfind.mkdir(parents=True)
        (pathfind / "defaultPathfind.xml").write_text("<pathfind />")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_fix(self) -> bool:
        return FIX.run({"WORKSHOP": self.workshop, "log": self.logs.append})

    def lowercase_media(self) -> Path:
        return (
            self.workshop
            / FIX.WORKSHOP_ID
            / "mods"
            / FIX.MOD_NAME.lower()
            / "42"
            / "media"
        )

    def test_fresh_tree_creates_all_targeted_aliases(self) -> None:
        self.assertTrue(self.run_fix())

        expected = {
            "lua": "../../../CompanionDogs/42/media/lua",
            "animsets": "../../../CompanionDogs/42/media/AnimSets",
            "scripts": "../../../CompanionDogs/42/media/scripts",
            "models_X": "../../../CompanionDogs/42/media/models_X",
        }
        for name, target in expected.items():
            alias = self.lowercase_media() / name
            self.assertTrue(alias.is_symlink())
            self.assertEqual(alias.readlink(), Path(target))
            self.assertTrue(alias.samefile(self.media / ("AnimSets" if name == "animsets" else name)))

        pathfind = self.media / "AnimSets" / "raccoon" / "pathfind"
        lowercase_pathfind = pathfind / "defaultpathfind.xml"
        self.assertTrue(lowercase_pathfind.is_symlink())
        self.assertEqual(lowercase_pathfind.readlink(), Path("defaultPathfind.xml"))
        self.assertTrue(lowercase_pathfind.samefile(pathfind / "defaultPathfind.xml"))

    def test_second_run_is_idempotent(self) -> None:
        self.assertTrue(self.run_fix())
        aliases = [self.lowercase_media() / name for name in ("lua", "animsets", "scripts", "models_X")]
        before = [alias.lstat().st_ino for alias in aliases]

        self.assertFalse(self.run_fix())
        self.assertEqual([alias.lstat().st_ino for alias in aliases], before)

    def test_upstream_scripts_and_models_takeover_is_left_untouched(self) -> None:
        lowercase_media = self.lowercase_media()
        scripts = lowercase_media / "scripts"
        models = lowercase_media / "models_X"
        scripts.mkdir(parents=True)
        models.mkdir()

        self.assertTrue(self.run_fix())
        self.assertTrue(scripts.is_dir())
        self.assertFalse(scripts.is_symlink())
        self.assertTrue(models.is_dir())
        self.assertFalse(models.is_symlink())
        self.assertTrue(any("scripts path exists as a real" in line for line in self.logs))
        self.assertTrue(any("models_X path exists as a real" in line for line in self.logs))

    def test_wrong_symlink_is_not_replaced(self) -> None:
        self.assertTrue(self.run_fix())
        scripts = self.lowercase_media() / "scripts"
        scripts.unlink()
        scripts.symlink_to("../../../unexpected/scripts", target_is_directory=True)

        self.assertFalse(self.run_fix())
        self.assertEqual(scripts.readlink(), Path("../../../unexpected/scripts"))
        self.assertTrue(any("scripts alias points to an unexpected target" in line for line in self.logs))

    def test_never_creates_a_whole_mod_root_alias(self) -> None:
        self.run_fix()
        lowercase_root = self.workshop / FIX.WORKSHOP_ID / "mods" / FIX.MOD_NAME.lower()
        self.assertTrue(lowercase_root.is_dir())
        self.assertFalse(lowercase_root.is_symlink())

    def test_missing_mod_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs: list[str] = []
            self.assertFalse(FIX.run({"WORKSHOP": Path(tmp), "log": logs.append}))
            self.assertEqual(logs, ["CompanionDogs: mod not present; skip."])


if __name__ == "__main__":
    unittest.main()
