#!/usr/bin/env python3
"""Build TestSwiftApp for macOS and optionally run it through shared ColdHook."""
from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tests/TestSwiftApp/TestSwiftApp.xcodeproj"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dylib", help="macOS hook dylib to merge")
    ap.add_argument("--runtime", help="macOS libcoldhook.dylib")
    ap.add_argument("--no-run", action="store_true")
    args = ap.parse_args()

    derived = Path(tempfile.mkdtemp(prefix="coldhook_swiftui_mac_"))
    cmd = ["xcodebuild", "-project", str(PROJECT), "-scheme", "TestSwiftApp",
           "-configuration", "Release", "-sdk", "macosx",
           "-derivedDataPath", str(derived), "MACOSX_DEPLOYMENT_TARGET=13.0",
           "ARCHS=arm64", "ONLY_ACTIVE_ARCH=YES",
           "OTHER_LDFLAGS=$(inherited) -Wl,-headerpad,0x4000",
           "LD_RUNPATH_SEARCH_PATHS=$(inherited) @executable_path/../Frameworks @loader_path/../Frameworks",
           "CODE_SIGNING_ALLOWED=NO", "build"]
    subprocess.run(cmd, check=True)
    app = derived / "Build/Products/Release/TestSwiftApp.app"

    # The project is primarily an iOS fixture, whose copy phase uses the iOS
    # Frameworks destination. Normalize the macOS bundle layout for local runs.
    framework = derived / "Build/Products/Release/TestFramework.framework"
    mac_frameworks = app / "Contents/Frameworks"
    mac_frameworks.mkdir(parents=True, exist_ok=True)
    if framework.exists():
        subprocess.run(["ditto", str(framework), str(mac_frameworks / "TestFramework.framework")], check=True)

    if args.dylib:
        if not args.runtime:
            ap.error("--runtime обязателен вместе с --dylib")
        output = derived / "TestSwiftApp-coldhook.app"
        merge = [sys.executable, "-m", "coldhook", "shared", str(app),
                 "--dylib", args.dylib, "--runtime", args.runtime,
                 "--out", str(output), "--verbose",
                 "--import-path", "@executable_path/../Frameworks/" + Path(args.dylib).name]
        subprocess.run(merge, cwd=ROOT, check=True)
        app = output

        # coldhook's generic IPA path is iOS-oriented and creates a root
        # Frameworks directory. Normalize it to the macOS bundle layout.
        root_frameworks = app / "Frameworks"
        mac_frameworks = app / "Contents/Frameworks"
        if root_frameworks.exists():
            mac_frameworks.mkdir(parents=True, exist_ok=True)
            for item in root_frameworks.iterdir():
                item.rename(mac_frameworks / item.name)
            root_frameworks.rmdir()
        # Supplying --import-path disables generic hook-dylib bundling, so
        # place the macOS hook next to the runtime explicitly.
        mac_frameworks.mkdir(parents=True, exist_ok=True)
        hook_copy = mac_frameworks / Path(args.dylib).name
        if not hook_copy.exists():
            shutil.copy2(args.dylib, hook_copy)
        if not hook_copy.exists():
            raise RuntimeError(f"hook dylib was not bundled: {hook_copy}")
        # Some merger paths preserve an @rpath LC_LOAD_DYLIB from the hook
        # image. Normalize it on the final macOS executable explicitly.
        executable = app / "Contents/MacOS/TestSwiftApp"
        subprocess.run(["install_name_tool", "-change",
                        "@rpath/" + Path(args.dylib).name,
                        "@executable_path/../Frameworks/" + Path(args.dylib).name,
                        str(executable)], check=False)

    # LaunchServices rejects unsigned temporary .app bundles even when the
    # executable itself is otherwise valid. Sign after all Mach-O mutations.
    # Sign nested code explicitly; --deep can report a versioned macOS
    # framework as an ambiguous bundle.
    nested = app / "Contents/Frameworks"
    if nested.exists():
        for item in sorted(nested.iterdir(), key=lambda p: len(p.parts), reverse=True):
            if item.is_dir() and item.suffix == ".framework":
                framework_binary = item / "Versions/A" / item.stem
                if not framework_binary.exists():
                    framework_binary = item / item.stem
                subprocess.run(["codesign", "--force", "--sign", "-", str(framework_binary)], check=True)
            elif item.is_file() and item.suffix == ".dylib":
                subprocess.run(["codesign", "--force", "--sign", "-", str(item)], check=True)
    app_sign = subprocess.run(["codesign", "--force", "--sign", "-", str(app)],
                               capture_output=True, text=True)
    if app_sign.returncode != 0:
        print("warning: app ad-hoc signing skipped:", app_sign.stderr.strip())
    else:
        verify = subprocess.run(["codesign", "--verify", "--strict", str(app)],
                                capture_output=True, text=True)
        if verify.returncode != 0:
            print("warning: app signature verification skipped:", verify.stderr.strip())

    print(f"APP={app}")
    if args.no_run:
        return 0

    log = subprocess.Popen(
        ["log", "stream", "--style", "compact", "--level", "debug",
         "--predicate", 'subsystem == "com.coldhook.runtime"'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    launch_env = os.environ.copy()
    launch_env["COLDHOOK_DEBUG"] = "1"
    # Use the executable directly so COLDHOOK_DEBUG is inherited reliably;
    # LaunchServices does not propagate custom environment variables.
    executable = app / "Contents/MacOS/TestSwiftApp"
    subprocess.Popen([str(executable)], env=launch_env)
    print("Запущено. Нажми Ctrl-C для остановки и вывода логов.")
    try:
        while True:
            line = log.stdout.readline() if log.stdout else ""
            if line:
                print(line, end="")
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        log.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    raise SystemExit(main())
