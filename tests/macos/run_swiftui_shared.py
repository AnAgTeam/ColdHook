#!/usr/bin/env python3
"""Build TestSwiftApp for macOS and optionally run it through shared ColdHook."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tests/TestSwiftApp/TestSwiftApp.xcodeproj"


def build_test_hooks(derived: Path) -> tuple[Path, Path]:
    """Use the same hook assertions as the Simulator fixture, compiled for macOS."""
    hooks = ROOT / "tests/simulator/hooks"
    build = derived / "hooks"
    build.mkdir()
    runtime = build / "libcoldhook.dylib"
    dylib = build / "coldhookdtest.dylib"
    obj = build / "Tweak.o"
    exports = build / "exports.list"
    exports.write_text("\n".join([
        "_COLDHOOK_DYN_SYM_TestSwiftApp__CH__$s12TestSwiftApp3url3forS2S_tF__CH__url",
        "_COLDHOOK_ORIG_SYM_TestSwiftApp__CH__$s12TestSwiftApp3url3forS2S_tF__CH__url",
        "_COLDHOOK_DYN_SYM_TestSwiftApp__CH__$s12TestSwiftApp17get_label_contentSSyF__CH__getLabelContent",
        "_COLDHOOK_ORIG_SYM_TestSwiftApp__CH__$s12TestSwiftApp17get_label_contentSSyF__CH__getLabelContent",
        "_COLDHOOK_DYN_SYM_TestFramework__CH__$s13TestFramework14frameworkProbes5Int32VyF__CH__frameworkProbe",
        "_COLDHOOK_ORIG_SYM_TestFramework__CH__$s13TestFramework14frameworkProbes5Int32VyF__CH__frameworkProbe",
    ]) + "\n")
    subprocess.run(["xcrun", "clang", "-dynamiclib", "-arch", "arm64",
                    "-mmacosx-version-min=13.0", "-I", str(ROOT / "coldhook/include"),
                    "-install_name", "@rpath/libcoldhook.dylib",
                    str(ROOT / "coldhook/shared_runtime.c"), "-o", str(runtime)], check=True)
    subprocess.run(["xcrun", "clang", "-arch", "arm64", "-mmacosx-version-min=13.0",
                    "-I", str(ROOT / "coldhook/include"), "-c", str(hooks / "Tweak.m"),
                    "-o", str(obj)], check=True)
    subprocess.run(["xcrun", "swiftc", "-target", "arm64-apple-macos13.0",
                    "-parse-as-library", "-emit-library", str(hooks / "Tweak.swift"), str(obj),
                    "-L", str(build), "-lcoldhook", "-o", str(dylib),
                    "-Xlinker", "-install_name", "-Xlinker", "@rpath/coldhookdtest.dylib",
                    "-Xlinker", "-exported_symbols_list", "-Xlinker", str(exports),
                    "-Xlinker", "-undefined", "-Xlinker", "dynamic_lookup",
                    "-Xlinker", "-needed_library", "-Xlinker", str(runtime)], check=True)
    return dylib, runtime


def run_ui_test(derived: Path, patched: Path) -> None:
    host = derived / "Build/Products/Release/TestSwiftApp.app"
    shutil.rmtree(host)
    shutil.copytree(patched, host, symlinks=True)
    plans = list((derived / "Build/Products").glob("*.xctestrun"))
    if len(plans) != 1:
        raise RuntimeError(f"Expected one xctestrun test plan, found {plans}")
    # XCTest must load the patched embedded framework, not its original in Build/Products.
    with plans[0].open("rb") as stream:
        plan = plistlib.load(stream)
    def scrub(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in {"DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH",
                           "__XPC_DYLD_FRAMEWORK_PATH", "__XPC_DYLD_LIBRARY_PATH"}:
                    del value[key]
                else:
                    scrub(value[key])
        elif isinstance(value, list):
            for item in value:
                scrub(item)
    scrub(plan)
    with plans[0].open("wb") as stream:
        plistlib.dump(plan, stream)
    result = derived / "SharedHooks.xcresult"
    print(f"XCTest result: {result}", flush=True)
    subprocess.run(["xcodebuild", "test-without-building", "-xctestrun", str(plans[0]),
                    "-destination", "platform=macOS,arch=arm64",
                    "-only-testing:TestSwiftAppUITests/TestSwiftAppUITests/testSharedHooksAreVisible",
                    "-parallel-testing-enabled", "NO", "-resultBundlePath", str(result)],
                   cwd=ROOT, check=True)
    summary = json.loads(subprocess.check_output(
        ["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(result)],
        text=True))
    if (summary.get("totalTestCount") != 1 or summary.get("passedTests") != 1
            or summary.get("failedTests") != 0 or summary.get("skippedTests") != 0):
        raise RuntimeError(f"Expected one executed, passing UI test: {summary}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dylib", help="macOS hook dylib to merge")
    ap.add_argument("--runtime", help="macOS libcoldhook.dylib")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--no-run", action="store_true")
    mode.add_argument("--test", action="store_true", help="build hooks, patch and assert UI with XCTest")
    args = ap.parse_args()

    if bool(args.dylib) != bool(args.runtime):
        ap.error("--dylib и --runtime указываются вместе")

    derived = Path(tempfile.mkdtemp(prefix="coldhook_swiftui_mac_"))
    cmd = ["xcodebuild", "-project", str(PROJECT), "-scheme", "TestSwiftApp",
           "-configuration", "Release", "-sdk", "macosx",
           "-derivedDataPath", str(derived), "MACOSX_DEPLOYMENT_TARGET=13.0",
           "ARCHS=arm64", "ONLY_ACTIVE_ARCH=YES", "ENABLE_TESTABILITY=YES",
           "OTHER_LDFLAGS=$(inherited) -Wl,-headerpad,0x4000",
           "LD_RUNPATH_SEARCH_PATHS=$(inherited) @executable_path/../Frameworks @loader_path/../Frameworks",
           "CODE_SIGNING_ALLOWED=NO", "build-for-testing" if args.test else "build"]
    subprocess.run(cmd, check=True)
    app = derived / "Build/Products/Release/TestSwiftApp.app"

    # The project is primarily an iOS fixture, whose copy phase uses the iOS
    # Frameworks destination. Normalize the macOS bundle layout for local runs.
    framework = derived / "Build/Products/Release/TestFramework.framework"
    mac_frameworks = app / "Contents/Frameworks"
    mac_frameworks.mkdir(parents=True, exist_ok=True)
    if framework.exists():
        subprocess.run(["ditto", str(framework), str(mac_frameworks / "TestFramework.framework")], check=True)

    if args.test and not args.dylib:
        dylib, runtime = build_test_hooks(derived)
        args.dylib, args.runtime = str(dylib), str(runtime)

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
                        str(executable)], check=args.test)

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
        if args.test:
            raise RuntimeError(f"App signing failed: {app_sign.stderr}")
        print("warning: app ad-hoc signing skipped:", app_sign.stderr.strip())
    else:
        verify = subprocess.run(["codesign", "--verify", "--strict", str(app)],
                                capture_output=True, text=True)
        if verify.returncode != 0:
            if args.test:
                raise RuntimeError(f"App signature verification failed: {verify.stderr}")
            print("warning: app signature verification skipped:", verify.stderr.strip())

    print(f"APP={app}")
    if args.test:
        run_ui_test(derived, app)
        return 0
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
