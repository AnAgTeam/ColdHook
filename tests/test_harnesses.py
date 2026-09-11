"""Adapt existing script harnesses to pytest without importing/executing at collection."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = {"run_initaddr.py"}
MACOS = sorted((ROOT / "tests/macos").glob("run*.py"))


def run_harness(script, request, tmp_path, *args, env=None):
    command = [sys.executable, "-u", str(script), *args]
    logfile = tmp_path / (script.stem + ".log")
    timeout = request.config.getoption("--harness-timeout")
    timed_out = False
    with logfile.open("wb") as output:
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output,
                                stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if proc.poll() is None:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    text = logfile.read_text(encoding="utf-8", errors="replace")
    request.node.add_report_section("call", "harness log", text)
    detail = f"command: {command}\nlog: {logfile}\n{text[-16000:]}"
    if timed_out:
        pytest.fail(f"Harness timed out after {timeout}s\n{detail}", pytrace=False)
    if proc.returncode:
        pytest.fail(f"Harness exited {proc.returncode}\n{detail}", pytrace=False)
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    skip = re.search(r"(?m)^SKIP[^\n]*", clean)
    if skip:
        pytest.skip(skip.group(0))


def native_environment(script):
    missing = [name for name in ("xcrun", "codesign", "otool", "nm") if not shutil.which(name)]
    if missing:
        pytest.fail("Native suite requested, missing tools: " + ", ".join(missing), pytrace=False)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    if script.name not in {"run_swift_offset.py"}:
        from coldhook.toolchain import ensure_merger
        env["COLDHOOK_MERGER"] = ensure_merger()
    return env


@pytest.mark.parametrize("script", [
    pytest.param(path, id=path.stem, marks=() if path.name in PORTABLE else pytest.mark.native)
    for path in MACOS
])
def test_macos_harness(script, request, tmp_path):
    env = None if script.name in PORTABLE else native_environment(script)
    # Use the finite XCTest pipeline instead of the interactive Ctrl-C loop.
    args = ["--test"] if script.name == "run_swiftui_shared.py" else []
    run_harness(script, request, tmp_path, *args, env=env)


@pytest.mark.simulator
def test_simulator_shared(request, tmp_path):
    script = ROOT / "tests/simulator/run_shared.py"
    env = native_environment(script)
    udid = request.config.getoption("--simulator-udid")
    check = subprocess.run(["xcrun", "simctl", "list", "devices", "available", "--json"],
                           capture_output=True, text=True, timeout=30)
    assert check.returncode == 0, check.stderr
    devices = [device for group in json.loads(check.stdout)["devices"].values() for device in group]
    assert any(d["udid"] == udid and d["state"] == "Booted" for d in devices), (
        f"Simulator {udid} must exist, be available and already booted")
    run_harness(script, request, tmp_path, "--udid", udid, env=env)
