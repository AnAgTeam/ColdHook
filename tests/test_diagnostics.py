"""Diagnostic and tool discovery regressions; no Apple tools required."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from coldhook import cli, config, macho, toolchain
from coldhook.diagnostics import DiagnosticError


class DiagnosticsTests(unittest.TestCase):
    def test_explicit_invalid_merger_does_not_fall_back(self):
        with patch.dict(os.environ, {"COLDHOOK_MERGER": "/missing/merger"}):
            with self.assertRaisesRegex(toolchain.ToolError, "COLDHOOK_MERGER"):
                toolchain.ensure_merger()

    def test_current_directory_merger_without_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp, toolchain._merger_name)
            binary.write_text("placeholder")
            binary.chmod(0o755)
            with patch.dict(os.environ, {"COLDHOOK_MERGER": ""}), patch("os.getcwd", return_value=tmp):
                self.assertEqual(toolchain.ensure_merger(), str(binary))

    def test_path_merger(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp, "tools", toolchain._merger_name)
            binary.parent.mkdir()
            binary.write_text("placeholder")
            binary.chmod(0o755)
            with patch.dict(os.environ, {"COLDHOOK_MERGER": ""}), \
                 patch("os.getcwd", return_value=tmp), \
                 patch("shutil.which", return_value=str(binary)):
                self.assertEqual(toolchain.ensure_merger(), str(binary))

    def test_failed_metadata_preserves_path_and_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp, "test binary")
            binary.write_bytes(b"invalid header")
            with self.assertRaises(DiagnosticError) as caught:
                macho.inspect(str(binary))
            for value in ("Inspecting Mach-O", "Invalid or truncated Mach-O header", str(binary)):
                self.assertIn(value, str(caught.exception))

    def test_config_rejects_string_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "bad.toml")
            path.write_text('[target]\nbinary="App"\nsources="hook.c"\n')
            with self.assertRaisesRegex(DiagnosticError, "sources должен быть массивом"):
                config.load(str(path))

    def test_cli_missing_dependency_and_traceback_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp, "run.log")
            with patch("importlib.import_module", side_effect=ImportError("missing lief")), \
                 contextlib.redirect_stderr(io.StringIO()) as stderr:
                result = cli.main(["--log-file", str(log_path), "info", "dummy"])
            self.assertEqual(result, 1)
            self.assertIn("pip install", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertIn(f"Detailed log: {log_path}", stderr.getvalue())
            self.assertIn("Traceback", log_path.read_text())

    def test_normal_cli_error_has_no_internal_log_prefix(self):
        with patch("importlib.import_module", side_effect=ImportError("missing lief")), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = cli.main(["info", "dummy"])
        output = stderr.getvalue()
        self.assertEqual(result, 1)
        self.assertIn("error:", output)
        self.assertNotIn(" INFO ", output)
        self.assertNotIn(" DEBUG ", output)
        self.assertNotIn("Traceback", output)

    def test_stage_events_are_debug_diagnostics(self):
        with self.assertLogs("coldhook", level="DEBUG") as caught:
            with cli.stage("Тестовый этап"):
                pass
        self.assertTrue(all(record.levelname == "DEBUG" for record in caught.records))

    def test_help_works_without_dependency_check(self):
        with patch("importlib.import_module", side_effect=ImportError), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--help"])
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
