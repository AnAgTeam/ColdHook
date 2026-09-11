"""Check XCTest orchestration without an Apple toolchain."""
import importlib.util
import json
from pathlib import Path
import plistlib

import pytest

spec = importlib.util.spec_from_file_location(
    "swiftui_harness", Path(__file__).parent / "macos/run_swiftui_shared.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@pytest.mark.parametrize("passed,skipped", [(0, 0), (0, 1), (1, 0)])
def test_ui_test_requires_executed_assertions(tmp_path, monkeypatch, passed, skipped):
    products = tmp_path / "Build/Products"
    host = products / "Release/TestSwiftApp.app"
    host.mkdir(parents=True)
    (host / "binary").write_text("original")
    patched = tmp_path / "patched.app"
    patched.mkdir()
    (patched / "binary").write_text("patched")
    plan = products / "test.xctestrun"
    plan.write_bytes(plistlib.dumps({"EnvironmentVariables": {
        "DYLD_FRAMEWORK_PATH": "/unpatched", "KEEP": "yes"}}))
    commands = []
    monkeypatch.setattr(harness.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(harness.subprocess, "check_output", lambda *a, **kw: json.dumps({
        "totalTestCount": passed + skipped, "passedTests": passed,
        "failedTests": 0, "skippedTests": skipped}))
    if passed:
        harness.run_ui_test(tmp_path, patched)
    else:
        with pytest.raises(RuntimeError, match="executed, passing UI test"):
            harness.run_ui_test(tmp_path, patched)
    assert (host / "binary").read_text() == "patched"
    assert plistlib.loads(plan.read_bytes())["EnvironmentVariables"] == {"KEEP": "yes"}
    assert "test-without-building" in commands[0]
    assert any("testSharedHooksAreVisible" in arg for arg in commands[0])
