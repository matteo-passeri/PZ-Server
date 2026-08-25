import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit-server-log.py")


def load_auditor():
    spec = importlib.util.spec_from_file_location("audit_server_log", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDITOR = load_auditor()


class AuditServerLogTests(unittest.TestCase):
    def make_reports(self, content: str, requested: str = "all") -> tuple[list[Path], Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        source = root / "2026-08-25_12-40-DebugLog-server.txt"
        source.write_text(content, encoding="utf-8")
        previous_reports_dir = AUDITOR.REPORTS_DIR
        AUDITOR.REPORTS_DIR = root / "reports"
        self.addCleanup(setattr, AUDITOR, "REPORTS_DIR", previous_reports_dir)
        return AUDITOR.generate_reports(source, requested), source

    def test_successful_startup_writes_no_serious_runtime_message(self) -> None:
        reports, _ = self.make_reports(
            "2026-08-25 12:39:00 ERROR: Missing ThumpSound chair\n"
            "*** SERVER STARTED ****\n"
            "2026-08-25 12:41:00 INFO: Server ready\n"
        )

        self.assertEqual(len(reports), 2)
        startup, runtime = (path.read_text(encoding="utf-8") for path in reports)
        self.assertIn("LOW / NOISE (1)", startup)
        self.assertIn("No serious runtime errors detected after server startup.", runtime)

    def test_startup_critical_java_and_lua_errors_include_context(self) -> None:
        reports, _ = self.make_reports(
            "2026-08-25 12:39:00 ERROR: java.lang.NullPointerException\n"
            "  at zombie.Server.main(Server.java:42)\n"
            "2026-08-25 12:39:01 ERROR: attempt to call a nil value\n"
            "*** SERVER STARTED ****\n"
        )

        startup = reports[0].read_text(encoding="utf-8")
        self.assertIn("CRITICAL / HIGH (2)", startup)
        self.assertIn("at zombie.Server.main", startup)
        self.assertIn("attempt to call a nil value", startup)

    def test_missing_started_marker_creates_incomplete_startup_only(self) -> None:
        reports, _ = self.make_reports("2026-08-25 12:39:00 WARN: still starting\n")

        self.assertEqual(len(reports), 1)
        text = reports[0].read_text(encoding="utf-8")
        self.assertIn("INCOMPLETE STARTUP: SERVER STARTED was not reached.", text)
        self.assertIn("SERVER STARTED line number: not reached", text)

    def test_runtime_error_is_not_in_startup_report(self) -> None:
        reports, _ = self.make_reports(
            "2026-08-25 12:39:00 INFO: booting\n"
            "*** SERVER STARTED ****\n"
            "2026-08-25 12:41:00 ERROR: java.lang.IllegalStateException: broken runtime state\n"
        )

        startup, runtime = (path.read_text(encoding="utf-8") for path in reports)
        self.assertNotIn("broken runtime state", startup)
        self.assertIn("CRITICAL / HIGH (1)", runtime)
        self.assertIn("broken runtime state", runtime)

    def test_repetitive_startup_errors_are_grouped(self) -> None:
        reports, _ = self.make_reports(
            "ERROR: Could not find bone index for HeadA\n"
            "ERROR: Could not find bone index for HeadB\n"
            "ERROR: Could not find bone index for HeadC\n"
            "*** SERVER STARTED ****\n"
        )

        startup = reports[0].read_text(encoding="utf-8")
        self.assertIn("3 x Could not find bone index for ...", startup)

    def test_required_mod_not_found_is_dependency_configuration(self) -> None:
        reports, _ = self.make_reports(
            "ERROR: required mod \"ExampleMod\" not found\n"
            "*** SERVER STARTED ****\n"
        )

        startup = reports[0].read_text(encoding="utf-8")
        self.assertIn("DEPENDENCY / CONFIG (1)", startup)
        self.assertIn('required mod "ExampleMod" not found', startup)

    def test_cli_runs_outside_repository_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "outside-DebugLog-server.txt"
            source.write_text("*** SERVER STARTED ****\n", encoding="utf-8")
            report = AUDITOR.REPORTS_DIR / "outside-DebugLog-server-startup-errors.txt"
            self.addCleanup(report.unlink, missing_ok=True)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(source), "--startup"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(report.is_file())


if __name__ == "__main__":
    unittest.main()
