#!/usr/bin/env python3
"""Build-phase regression for @ColdHookOffset Swift glue generation."""
import os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / "coldhook/templates/coldhook-swift-shared/coldhook_swift_preprocess.py"

def main():
    with tempfile.TemporaryDirectory(prefix="coldhook_swift_offset_") as td:
        root = Path(td); src = root / "Sources"; src.mkdir(); out = root / "out"; glue = root / "Tweak.m"
        target = root / "target"
        swift = src / "Target.swift"
        swift.write_text('''@inline(never) public func pick(_ x: Int) -> String {\n  if x == 0 { return "ZERO" }; return "NZ:\\(x)"\n}\n''')
        subprocess.run(["xcrun", "swiftc", "-target", "arm64-apple-macos13", str(swift), "-o", str(target)], check=True)
        nm = subprocess.check_output(["nm", str(target)], text=True)
        m = next((re.match(r"([0-9a-fA-F]+)\\s+\\S+\\s+.*pick", line) for line in nm.splitlines() if "pick" in line), None)
        if not m: raise RuntimeError("target Swift symbol not found")
        offset = "0x" + m.group(1)
        hook = src / "Hook.swift"
        hook.write_text(f'''@ColdHookOffset(binary: "target", offset: {offset})\npublic func replacement(_ x: Int) -> String {{ return "HOOKED" }}\n''')
        subprocess.run([sys.executable, str(PRE), str(src), str(out), str(glue)], check=True)
        generated = glue.read_text()
        expected = f'CH_DYN_ADDR("target", {offset}, replacement);'
        if expected not in generated:
            raise RuntimeError(f"missing generated offset glue: {expected}")
        print(f"OK: @ColdHookOffset -> {expected}")

if __name__ == "__main__":
    try: main()
    except Exception as e: print(f"FAIL: {e}"); sys.exit(1)
