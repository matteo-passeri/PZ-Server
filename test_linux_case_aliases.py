import importlib.util
import tempfile
import unittest
from pathlib import Path


FIX_SCRIPTS = Path(__file__).with_name("fix-scripts")


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name,
        FIX_SCRIPTS / filename,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPANION_DOGS = load_module(
    "companion_dogs_animsets_case",
    "21-companion-dogs-animsets-case.py",
)
HOT_BRASS = load_module(
    "hot_brass_linux_case",
    "23-hot-brass-linux-case.py",
)
GENERIC_CASE_FIX = load_module(
    "generic_linux_animset_xml_case",
    "24-linux-animset-xml-case.py",
)


class LinuxCaseAliasTests(unittest.TestCase):
    def run_generic_case_fix(self, workshop, log_path, logs):
        return GENERIC_CASE_FIX.run({
            "WORKSHOP": workshop,
            "active_workshop_ids": {"123"},
            "latest_pz_server_log": lambda: log_path,
            "log": logs.append,
        })

    def test_generic_fix_creates_case_only_xml_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = root / "workshop"
            animsets = workshop / "123" / "mods" / "Example" / "media" / "AnimSets"
            animsets.mkdir(parents=True)
            source = animsets / "DefaultPathfind.XML"
            source.write_text("", encoding="utf-8")
            missing = animsets / "defaultpathfind.xml"
            log_path = root / "server-console.txt"
            log_path.write_text(
                f"ERROR: file not found: '{missing}'\n",
                encoding="utf-8",
            )

            logs = []
            self.assertTrue(self.run_generic_case_fix(workshop, log_path, logs))
            self.assertTrue(missing.is_symlink())
            self.assertFalse(missing.readlink().is_absolute())
            self.assertTrue(missing.samefile(source))
            self.assertFalse(self.run_generic_case_fix(workshop, log_path, logs))

    def test_generic_fix_ignores_inactive_workshop_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = root / "workshop"
            animsets = workshop / "999" / "mods" / "Example" / "media" / "AnimSets"
            animsets.mkdir(parents=True)
            source = animsets / "Default.XML"
            source.write_text("", encoding="utf-8")
            missing = animsets / "default.xml"
            log_path = root / "server-console.txt"
            log_path.write_text(
                f"ERROR: missing '{missing}'\n",
                encoding="utf-8",
            )

            self.assertFalse(self.run_generic_case_fix(workshop, log_path, []))
            self.assertFalse(missing.exists() or missing.is_symlink())

    def test_generic_fix_leaves_ambiguous_case_matches_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = root / "workshop"
            animsets = workshop / "123" / "mods" / "Example" / "media" / "AnimSets"
            animsets.mkdir(parents=True)
            (animsets / "Default.XML").write_text("", encoding="utf-8")
            (animsets / "dEFAULT.xml").write_text("", encoding="utf-8")
            missing = animsets / "default.XML"
            log_path = root / "server-console.txt"
            log_path.write_text(
                f"ERROR: missing '{missing}'\n",
                encoding="utf-8",
            )

            logs = []
            self.assertFalse(self.run_generic_case_fix(workshop, log_path, logs))
            self.assertFalse(missing.exists() or missing.is_symlink())
            self.assertTrue(any("ambiguous" in message for message in logs))

    def test_generic_fix_keeps_correct_existing_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = root / "workshop"
            animsets = workshop / "123" / "mods" / "Example" / "media" / "AnimSets"
            animsets.mkdir(parents=True)
            source = animsets / "Default.XML"
            source.write_text("", encoding="utf-8")
            missing = animsets / "default.xml"
            missing.symlink_to("Default.XML")
            log_path = root / "server-console.txt"
            log_path.write_text(
                f"ERROR: cannot open '{missing}'\n",
                encoding="utf-8",
            )

            self.assertFalse(self.run_generic_case_fix(workshop, log_path, []))
            self.assertTrue(missing.samefile(source))

    def test_generic_fix_creates_log_proven_common_directory_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workshop = root / "workshop"
            common = workshop / "123" / "mods" / "Common"
            (common / "media").mkdir(parents=True)
            missing = workshop / "123" / "mods" / "common" / "media"
            log_path = root / "server-console.txt"
            log_path.write_text(
                f"ERROR: no such file '{missing}'\n",
                encoding="utf-8",
            )

            self.assertTrue(self.run_generic_case_fix(workshop, log_path, []))
            self.assertTrue((workshop / "123" / "mods" / "common").samefile(common))

    def test_existing_relative_symlink_to_source_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "aliases" / "destination"
            source.mkdir()
            destination.parent.mkdir()
            destination.symlink_to("../source", target_is_directory=True)

            self.assertEqual(
                COMPANION_DOGS.ensure_targeted_alias(
                    lambda message: None,
                    source,
                    destination,
                    "different-link-text",
                    "test",
                ),
                "present",
            )
            self.assertEqual(
                HOT_BRASS.ensure_alias(
                    source,
                    destination,
                    "different-link-text",
                ),
                "present",
            )

    def test_existing_symlink_to_another_target_is_unexpected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            other = root / "other"
            destination = root / "aliases" / "destination"
            source.mkdir()
            other.mkdir()
            destination.parent.mkdir()
            destination.symlink_to("../other", target_is_directory=True)

            self.assertEqual(
                COMPANION_DOGS.ensure_targeted_alias(
                    lambda message: None,
                    source,
                    destination,
                    "source",
                    "test",
                ),
                "unexpected",
            )
            self.assertEqual(
                HOT_BRASS.ensure_alias(source, destination, "source"),
                "unexpected",
            )

    def test_hot_brass_prefers_42_15_over_unversioned_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media" / "AnimSets").mkdir(parents=True)
            versioned = root / "42.15"
            (versioned / "media" / "AnimSets").mkdir(parents=True)

            self.assertEqual(HOT_BRASS.select_active_b42_tree(root), versioned)

    def test_hot_brass_prefers_42_20_over_other_42_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media" / "AnimSets").mkdir(parents=True)
            (root / "42.15" / "media" / "AnimSets").mkdir(parents=True)
            preferred = root / "42.20"
            (preferred / "media" / "AnimSets").mkdir(parents=True)

            self.assertEqual(HOT_BRASS.select_active_b42_tree(root), preferred)

    def test_hot_brass_uses_root_only_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media" / "AnimSets").mkdir(parents=True)

            self.assertEqual(HOT_BRASS.select_active_b42_tree(root), root)

    def test_repeat_runs_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workshop = Path(tmp)
            mod_root = (
                workshop
                / HOT_BRASS.WORKSHOP_ID
                / "mods"
                / HOT_BRASS.MOD_DIRECTORY
            )
            (mod_root / "42.15" / "media" / "AnimSets").mkdir(parents=True)
            logs: list[str] = []
            context = {"WORKSHOP": workshop, "log": logs.append}

            self.assertTrue(HOT_BRASS.run(context))
            self.assertFalse(HOT_BRASS.run(context))

    def test_companion_dogs_repeat_runs_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workshop = Path(tmp)
            media = (
                workshop
                / COMPANION_DOGS.WORKSHOP_ID
                / "mods"
                / COMPANION_DOGS.MOD_NAME
                / "42"
                / "media"
            )
            for name in ("lua", "AnimSets", "scripts", "models_X"):
                (media / name).mkdir(parents=True, exist_ok=True)
            pathfind = media / "AnimSets" / "raccoon" / "pathfind"
            pathfind.mkdir(parents=True)
            (pathfind / "defaultPathfind.xml").write_text("", encoding="utf-8")
            logs: list[str] = []
            context = {"WORKSHOP": workshop, "log": logs.append}

            self.assertTrue(COMPANION_DOGS.run(context))
            self.assertFalse(COMPANION_DOGS.run(context))


if __name__ == "__main__":
    unittest.main()
