"""Explicit opt-in for tests that compile and execute native fixtures."""
import platform

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("coldhook")
    group.addoption("--run-native", action="store_true", help="run macOS arm64 harnesses")
    group.addoption("--run-simulator", action="store_true", help="run iOS Simulator integration")
    group.addoption("--simulator-udid", help="UDID of an already booted iOS Simulator")
    group.addoption("--harness-timeout", type=int, default=600, help="seconds per harness")


def pytest_configure(config):
    if config.getoption("--harness-timeout") <= 0:
        raise pytest.UsageError("--harness-timeout must be positive")
    if config.getoption("--run-simulator") and not config.getoption("--simulator-udid"):
        raise pytest.UsageError("--run-simulator requires --simulator-udid")
    if (config.getoption("--run-native") or config.getoption("--run-simulator")) and (
            getattr(config.option, "numprocesses", None) or hasattr(config, "workerinput")):
        raise pytest.UsageError("Native harnesses share build directories; run without pytest-xdist (-n)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        category = "simulator" if "simulator" in item.keywords else "native" if "native" in item.keywords else None
        if category is None:
            continue
        if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
            reason = "requires macOS on Apple Silicon (native arm64 Python)"
        elif not config.getoption(f"--run-{category}"):
            reason = f"enable with --run-{category}"
        else:
            continue
        item.add_marker(pytest.mark.skip(reason=reason))
