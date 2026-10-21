#!/usr/bin/env python3
"""End-to-end regression for shared @ColdHookOffset with a Swift-ABI ORIG call."""
from coldhook.toolchain import ensure_merger
import os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / "coldhook/templates/coldhook-swift-shared/coldhook_swift_preprocess.py"

def main():
    with tempfile.TemporaryDirectory(prefix="coldhook_swift_offset_") as td:
        root = Path(td); src = root / "Sources"; src.mkdir(); out = root / "out"; glue = root / "Tweak.m"
        env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(root / "ModuleCache"),
                   SWIFT_MODULECACHE_PATH=str(root / "ModuleCache"))
        target = root / "target"
        swift = root / "Target.swift"
        swift.write_text('''import Foundation
@inline(never) public func pick(_ x: Int) -> String {
  if x == 0 { return "ZERO" }; return "NZ:\\(x)"
}
let x = CommandLine.arguments.count > 1 ? Int(CommandLine.arguments[1])! : 0
print(pick(x))
''')
        subprocess.run(["xcrun", "swiftc", "-O", "-target", "arm64-apple-macos13",
                        "-Xlinker", "-headerpad", "-Xlinker", "0x4000",
                        "-Xlinker", "-fixup_chains", "-Xlinker", "-add_split_seg_info",
                        str(swift), "-o", str(target)], check=True, env=env)
        nm = subprocess.check_output(["nm", str(target)], text=True)
        m = next((re.match(r"([0-9a-fA-F]+)\s+\S+\s+.*pick", line) for line in nm.splitlines() if "pick" in line), None)
        if not m: raise RuntimeError("target Swift symbol not found")
        offset = "0x" + m.group(1)
        hook = src / "Hook.swift"
        hook.write_text(f'''@ColdHookOffset(binary: "target", offset: {offset})
public func replacement(_ x: Int) -> String {{
  if x == 99 {{ return "HOOKED" }}
  return orig_replacement(x)
}}
''')
        subprocess.run([sys.executable, str(PRE), str(src), str(out), str(glue)], check=True)
        generated = glue.read_text()
        expected = f'CH_DYN_ADDR("target", {offset}, replacement);'
        if expected not in generated:
            raise RuntimeError(f"missing generated offset glue: {expected}")
        rewritten = (out / "Hook.swift").read_text()
        if '@_silgen_name("orig_replacement")' not in rewritten:
            raise RuntimeError("missing generated Swift orig declaration")

        runtime = root / "libcoldhook.dylib"
        hook_dylib = root / "hook.dylib"
        glue_obj = root / "glue.o"
        merged = root / "merged"
        include = ROOT / "coldhook/include"
        merger = Path(ensure_merger())
        subprocess.run(["xcrun", "clang", "-arch", "arm64", "-target", "arm64-apple-macos13", "-dynamiclib",
                        "-I", str(include), "-install_name", "@loader_path/libcoldhook.dylib",
                        str(ROOT / "coldhook/shared_runtime.c"), "-o", str(runtime)], check=True, env=env)
        subprocess.run(["xcrun", "clang", "-arch", "arm64", "-target", "arm64-apple-macos13", "-I", str(include),
                        "-c", str(glue), "-o", str(glue_obj)], check=True, env=env)
        subprocess.run(["xcrun", "swiftc", "-O", "-target", "arm64-apple-macos13",
                        "-emit-library", str(out / "Hook.swift"), str(glue_obj),
                        "-L", str(root), "-lcoldhook", "-Xlinker", "-fixup_chains",
                        "-Xlinker", "-add_split_seg_info", "-Xlinker", "-not_for_dyld_shared_cache",
                        "-Xlinker", "-exported_symbols_list", "-Xlinker", str(glue.with_suffix('.exports')),
                        "-Xlinker", "-install_name",
                        "-Xlinker", "@loader_path/hook.dylib", "-o", str(hook_dylib)],
                       check=True, env=env)
        exports = subprocess.check_output(["nm", "-gU", str(hook_dylib)], text=True).splitlines()
        exported_names = {line.split()[-1] for line in exports if line.split()}
        expected_exports = {
            f"_COLDHOOK_DYN_ADDR_target__CH__COLDHOOK_ADDR_{offset}__CH__replacement",
            f"_COLDHOOK_ORIG_ADDR_target__CH__COLDHOOK_ADDR_{offset}__CH__replacement",
        }
        if exported_names != expected_exports:
            raise RuntimeError(f"unexpected Swift hook exports: {sorted(exported_names)}")
        subprocess.run([str(merger), str(target), str(hook_dylib), str(merged),
                        "--mode", "shared"], check=True, env=env)
        for binary in (runtime, hook_dylib, merged):
            subprocess.run(["codesign", "-f", "-s", "-", str(binary)], check=True, env=env)
        merged.chmod(0o755)
        for arg, expected_text in (("5", "NZ:5"), ("99", "HOOKED")):
            result = subprocess.run([str(merged), arg], capture_output=True, text=True,
                                    check=True, env=env)
            if expected_text not in result.stdout:
                raise RuntimeError(f"replacement({arg}) returned {result.stdout!r}")
        print("OK: @ColdHookOffset + private Swift orig thunk + two-symbol export contract")

if __name__ == "__main__":
    try: main()
    except Exception as e: print(f"FAIL: {e}"); sys.exit(1)
