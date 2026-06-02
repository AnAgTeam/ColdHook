#!/usr/bin/env python3
"""ColdHook test app — build (no coverage), install and launch on a physical device.

No real identifiers are baked in. Provide them via environment variables or a local,
untracked ./.coldhook.env (KEY=VALUE per line). Keep that file out of version control.

Usage:
    python3 scripts/build_install.py [--no-launch]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = str(REPO / ".coldhook.env")


def load_env_file(path: str) -> None:
    """Load simple KEY=VALUE lines into os.environ (without overriding existing)."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def cfg(key: str, default: str) -> str:
    return os.environ.get(key, default)


def run(cmd: list[str]) -> None:
    print("==>", " ".join(cmd))
    subprocess.run(cmd, check=True)


MERGER = REPO / "vendor/MachOMerger/.build/release/MachOMerger"


def patch_and_resign(app: str, binary_name: str, hook: str, identity: str) -> None:
    """Merge a hook dylib into the app's main binary (append-mode) and re-sign the bundle.

    The app must already be built/signed by Xcode; we extract its entitlements, swap the
    patched binary in, and re-sign with `identity` so the device accepts the modified bundle.
    """
    import shutil
    binary = os.path.join(app, binary_name)
    merged = binary + ".coldhook"
    run([str(MERGER), binary, hook, merged])
    shutil.move(merged, binary)
    os.chmod(binary, 0o755)
    # Preserve the original entitlements (provisioning needs them on device).
    ent = os.path.join(app, "..", "coldhook_entitlements.plist")
    with open(ent, "wb") as f:
        f.write(subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", binary],
                               capture_output=True).stdout or b"")
    sign = ["codesign", "-f", "-s", identity, "--generate-entitlement-der"]
    if os.path.getsize(ent) > 0:
        sign += ["--entitlements", ent]
    run(sign + [app])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-launch", action="store_true", help="skip launching after install")
    ap.add_argument("--hook", help="hook dylib to merge into the app binary before install "
                                    "(re-signs the bundle with SIGN_IDENTITY)")
    args = ap.parse_args()

    load_env_file(ENV_FILE)

    project = cfg("PROJECT", str(REPO / "tests/TestSwiftApp/TestSwiftApp.xcodeproj"))
    scheme = cfg("SCHEME", "TestSwiftApp")
    config = cfg("CONFIG", "Release")
    derived = cfg("DERIVED", str(REPO / "build_device"))

    team_id = cfg("TEAM_ID", "YOUR_TEAM_ID")
    bundle_id = cfg("BUNDLE_ID", "com.example.app")
    device_udid = cfg("DEVICE_UDID", "YOUR_DEVICE_UDID")        # xcodebuild destination
    coredevice_id = cfg("COREDEVICE_ID", "YOUR_COREDEVICE_ID")  # devicectl --device

    missing = [k for k, v in {
        "TEAM_ID": team_id, "DEVICE_UDID": device_udid, "COREDEVICE_ID": coredevice_id,
    }.items() if v.startswith("YOUR_")]
    if missing:
        sys.exit(f"ERROR: set {', '.join(missing)} (env or ./{ENV_FILE})")

    run([
        "xcodebuild", "-project", project, "-scheme", scheme, "-configuration", config,
        "-destination", f"platform=iOS,id={device_udid}",
        "-derivedDataPath", derived,
        "-allowProvisioningUpdates", f"DEVELOPMENT_TEAM={team_id}",
        "ENABLE_CODE_COVERAGE=NO", "CLANG_ENABLE_CODE_COVERAGE=NO",
        "build",
    ])

    app = f"{derived}/Build/Products/{config}-iphoneos/{scheme}.app"

    if args.hook:
        identity = cfg("SIGN_IDENTITY", "Apple Development")
        print(f"==> patch {scheme} with {os.path.basename(args.hook)} + re-sign ({identity})")
        patch_and_resign(app, scheme, args.hook, identity)

    run(["xcrun", "devicectl", "device", "install", "app", "--device", coredevice_id, app])

    if not args.no_launch:
        run(["xcrun", "devicectl", "device", "process", "launch",
             "--device", coredevice_id, bundle_id])

    print("==> done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
