"""Exercise runner failure/skip/timeout reporting using tiny child processes."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_harnesses import run_harness
from conftest import pytest_collection_modifyitems


def test_platform_skips_native_on_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    marks = []
    item = SimpleNamespace(keywords={"native": True}, add_marker=marks.append)
    pytest_collection_modifyitems(SimpleNamespace(), [item])
    assert len(marks) == 1
    assert "macOS" in marks[0].kwargs["reason"]


@pytest.mark.parametrize("code,exception,message", [
    ("print('SKIP: missing optional tool')", pytest.skip.Exception, "missing optional tool"),
    ("import sys; print('compile failed'); sys.exit(3)", pytest.fail.Exception, "exited 3"),
    ("import time; time.sleep(30)", pytest.fail.Exception, "timed out"),
])
def test_harness_outcomes(tmp_path, code, exception, message):
    script = tmp_path / "child.py"
    script.write_text(code)
    reports = []
    request = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: 1),
        node=SimpleNamespace(add_report_section=lambda *args: reports.append(args)),
    )
    with pytest.raises(exception, match=message):
        run_harness(script, request, tmp_path)
    assert reports
    assert Path(tmp_path, "child.log").exists()
