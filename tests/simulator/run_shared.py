#!/usr/bin/env python3
"""Build, patch, install and launch TestSwiftApp in iOS Simulator."""
from __future__ import annotations

import argparse
import sys
import plistlib
import subprocess
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "tests/TestSwiftApp/TestSwiftApp.xcodeproj"
DEFAULT_UDID = "837FA311-34F4-4CBB-B35A-73A887B09B30"
BUNDLE_ID = "org.toilettrauma.TestSwiftApp"


def run(cmd: list[str], **kwargs) -> None:
    kwargs.setdefault("check", True)
    subprocess.run(cmd, **kwargs)


def restrict_app_rpaths(binary: Path) -> None:
    """Keep only the embedded-framework runpath in the test host."""
    text = subprocess.check_output(["xcrun", "otool", "-l", str(binary)], text=True)
    rpaths = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            for candidate in lines[i + 1:i + 5]:
                value = candidate.strip()
                if value.startswith("path "):
                    rpaths.append(value.split(" ", 2)[1])
                    break
    keep = "@executable_path/Frameworks"
    for rpath in rpaths:
        if rpath != keep:
            run(["xcrun", "install_name_tool", "-delete_rpath", rpath, str(binary)])


def clear_xctest_dyld_paths(xctestrun: Path) -> None:
    """Prevent XCTest from redirecting dyld to the unpatched build products."""
    with xctestrun.open("rb") as stream:
        document = plistlib.load(stream)
    blocked = {"DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH",
               "__XPC_DYLD_FRAMEWORK_PATH", "__XPC_DYLD_LIBRARY_PATH"}
    def scrub(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in blocked:
                    del value[key]
                else:
                    scrub(value[key])
        elif isinstance(value, list):
            for item in value:
                scrub(item)
    scrub(document)
    with xctestrun.open("wb") as stream:
        plistlib.dump(document, stream, fmt=plistlib.FMT_BINARY)


def sign_simulator_bundle(app: Path) -> None:
    frameworks = app / "Frameworks"
    if frameworks.exists():
        for item in sorted(frameworks.iterdir(), key=lambda p: len(p.parts), reverse=True):
            if item.suffix in (".framework", ".dylib") or item.name.endswith(".dylib"):
                run(["codesign", "--force", "--sign", "-", str(item)])
    run(["codesign", "--force", "--deep", "--sign", "-", str(app)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dylib")
    ap.add_argument("--runtime")
    ap.add_argument("--udid", default=DEFAULT_UDID)
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()

    derived = Path(tempfile.mkdtemp(prefix="coldhook_sim_"))
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    hook_build = derived / "hooks"
    hook_build.mkdir()
    dylib = Path(args.dylib) if args.dylib else hook_build / "coldhookdtest.dylib"
    runtime = Path(args.runtime) if args.runtime else hook_build / "libcoldhook.dylib"
    if not args.runtime:
        run(["clang", "-dynamiclib", "-arch", "arm64", "-isysroot", sdk,
             "-mios-simulator-version-min=15.0", "-I", str(ROOT / "coldhook/include"),
             "-install_name", "@rpath/libcoldhook.dylib", str(ROOT / "coldhook/shared_runtime.c"),
             "-o", str(runtime)])
    if not args.dylib:
        hooks = ROOT / "tests/simulator/hooks"
        exports = hook_build / "exports.list"
        exports.write_text("\n".join([
            "_COLDHOOK_DYN_SYM_TestSwiftApp__CH__$s12TestSwiftApp3url3forS2S_tF__CH__url",
            "_COLDHOOK_ORIG_SYM_TestSwiftApp__CH__$s12TestSwiftApp3url3forS2S_tF__CH__url",
            "_COLDHOOK_DYN_SYM_TestSwiftApp__CH__$s12TestSwiftApp17get_label_contentSSyF__CH__getLabelContent",
            "_COLDHOOK_ORIG_SYM_TestSwiftApp__CH__$s12TestSwiftApp17get_label_contentSSyF__CH__getLabelContent",
            "_COLDHOOK_DYN_SYM_TestFramework__CH__$s13TestFramework14frameworkProbes5Int32VyF__CH__frameworkProbe",
            "_COLDHOOK_ORIG_SYM_TestFramework__CH__$s13TestFramework14frameworkProbes5Int32VyF__CH__frameworkProbe",
        ]) + "\n")
        swift_obj = hook_build / "Tweak.swift.o"
        c_obj = hook_build / "Tweak.m.o"
        run(["swiftc", "-target", "arm64-apple-ios15.0-simulator", "-sdk", sdk,
             "-parse-as-library", "-emit-object", str(hooks / "Tweak.swift"), "-o", str(swift_obj)])
        run(["clang", "-target", "arm64-apple-ios15.0-simulator", "-isysroot", sdk,
             "-I", str(ROOT / "coldhook/include"), "-c", str(hooks / "Tweak.m"), "-o", str(c_obj)])
        run(["swiftc", "-target", "arm64-apple-ios15.0-simulator", "-sdk", sdk,
             "-parse-as-library", "-emit-library", str(hooks / "Tweak.swift"), str(c_obj),
             "-L", str(hook_build), "-lcoldhook", "-o", str(dylib),
             "-Xlinker", "-install_name", "-Xlinker", "@rpath/coldhookdtest.dylib",
             "-Xlinker", "-exported_symbols_list", "-Xlinker", str(exports),
             "-Xlinker", "-undefined", "-Xlinker", "dynamic_lookup",
             "-Xlinker", "-needed_library", "-Xlinker", str(runtime)])
    app = derived / "Build/Products/Release-iphonesimulator/TestSwiftApp.app"
    run([
        "xcodebuild", "-project", str(PROJECT), "-scheme", "TestSwiftApp",
        "-configuration", "Release", "-sdk", "iphonesimulator",
        "-derivedDataPath", str(derived), "ARCHS=arm64",
        "ONLY_ACTIVE_ARCH=YES",
        "OTHER_LDFLAGS=$(inherited) -Wl,-headerpad,0x4000",
        "SWIFT_ENABLE_TESTABILITY=YES",
        "LD_RUNPATH_SEARCH_PATHS=@executable_path/Frameworks",
        "CODE_SIGNING_ALLOWED=NO", "build-for-testing",
    ])

    patched = derived / "TestSwiftApp-coldhook.app"
    run([
        sys.executable, "-m", "coldhook", "shared", str(app),
        "--dylib", str(dylib), "--runtime", str(runtime),
        "--out", str(patched), "--verbose", "--skip-unsupported",
    ], cwd=ROOT)
    sign_simulator_bundle(patched)
    # Replace the build-for-testing host app with the patched one so the
    # generated xctestrun file launches the merged image.
    shutil.rmtree(app)
    run(["ditto", str(patched), str(app)])
    run(["xcrun", "simctl", "install", args.udid, str(patched)])
    if not args.no_launch:
        run(["xcrun", "simctl", "spawn", args.udid, "launchctl", "setenv", "COLDHOOK_DEBUG", "1"])
        xctestruns = list((derived / "Build/Products").rglob("*.xctestrun"))
        if xctestruns:
            clear_xctest_dyld_paths(xctestruns[0])
            run(["xcodebuild", "test-without-building", "-xctestrun", str(xctestruns[0]),
                 "-destination", f"id={args.udid}",
                 "-only-testing:TestSwiftAppUITests/TestSwiftAppUITests/testSharedHooksAreVisible",
                 "-parallel-testing-enabled", "NO",
                 "-maximum-concurrent-test-simulator-destinations", "1"], cwd=ROOT)
        else:
            # Only the non-UI-test path launches the app directly.
            run(["xcrun", "simctl", "launch", args.udid, BUNDLE_ID])
            print("Logs:")
            subprocess.run([
                "xcrun", "simctl", "spawn", args.udid, "log", "show", "--last", "15s",
                "--style", "compact", "--predicate",
                'subsystem == "com.coldhook.runtime"',
            ])
    print(f"APP={patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
