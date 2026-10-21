"""Regressions for compact user-facing progress output."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from coldhook import ipa


class CliOutputTests(unittest.TestCase):
    def test_thin_merge_reads_machine_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp, "patched"))

            def merge(_target, _hook, out, **kwargs):
                Path(out).write_bytes(b"patched")
                Path(kwargs["report_json"]).write_text(json.dumps({
                    "version": 1,
                    "status": "patched",
                    "hooks": [{"kind": "symbol", "selector": "Main",
                               "locator": "target", "handler": "replacement"}],
                }))

            with patch.object(ipa.build.toolchain, "merge", side_effect=merge) as merger:
                report = ipa._merge_shared_thin("Main", "Hooks.dylib", output,
                                                None, target_path="Original.app/Main")

            self.assertEqual(report["status"], "patched")
            self.assertEqual(report["hooks"][0]["handler"], "replacement")
            self.assertFalse(Path(output + ".report.json").exists())
            self.assertEqual(merger.call_args.kwargs["target_path"], "Original.app/Main")

    def test_shared_progress_and_changed_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Input.app"
            framework = app / "Frameworks" / "Example.framework"
            framework.mkdir(parents=True)
            (app / "Main").write_bytes(b"main")
            (framework / "Example").write_bytes(b"framework")
            hook = root / "Hooks.dylib"
            runtime = root / "libcoldhook.dylib"
            hook.write_bytes(b"hook")
            runtime.write_bytes(b"runtime")
            output = root / "Output.app"

            def merge(target, _dylib, merged, _import_path):
                if Path(target).name == "Main":
                    Path(merged).write_bytes(b"patched main")
                    return {"version": 1, "status": "patched", "hooks": [{
                        "kind": "symbol", "selector": "Main",
                        "locator": "target_symbol",
                        "handler": "replacement",
                    }]}
                else:
                    shutil.copy2(target, merged)
                    return {"version": 1, "status": "no-applicable-hooks", "hooks": []}

            is_macho = lambda path: Path(path).name in {"Main", "Example"}
            with patch.object(ipa.build.toolchain, "ensure_merger"), \
                 patch.object(ipa, "_validate_shared_selectors"), \
                 patch.object(ipa, "_shared_hook_descriptions", return_value=["Main:hook"]), \
                 patch.object(ipa.build.macho, "is_macho", side_effect=is_macho), \
                 patch.object(ipa, "_merge_shared", side_effect=merge), \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                ipa.patch_shared_bundle(str(app), str(hook), str(output),
                                        runtime=str(runtime), verbose=True)

            text = stdout.getvalue()
            self.assertIn("==> Declared hooks: 1", text)
            self.assertIn("Main:hook", text)
            self.assertIn("[1/2]", text)
            self.assertIn("[2/2]", text)
            self.assertIn("Hooks applied: 1", text)
            self.assertIn("SYMBOL  target_symbol → replacement", text)
            self.assertIn("No applicable hooks", text)
            self.assertIn("patched 1, hooks 1, unchanged 1", text)
            self.assertEqual((output / "Main").read_bytes(), b"patched main")


if __name__ == "__main__":
    unittest.main()
