#!/usr/bin/env python3
"""Two shared providers may use the same private C handler name."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tests/macos/build/shared_scope"
MERGER = Path(os.environ.get("COLDHOOK_MERGER") or
              ROOT / "vendor/MachOMerger/.build/release/MachOMerger")
INCLUDE = ROOT / "coldhook/include"


def run(command, **kwargs):
    print("  $ " + " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def cc(*args):
    return ["xcrun", "clang", "-arch", "arm64", *args]


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    runtime = BUILD / "libcoldhook.dylib"
    run(cc("-dynamiclib", "-I", INCLUDE, "-install_name", "@loader_path/libcoldhook.dylib",
           ROOT / "coldhook/shared_runtime.c", "-o", runtime))

    merged_targets = []
    for tag in ("a", "b"):
        target_src = BUILD / f"target_{tag}.c"
        hook_src = BUILD / f"hook_{tag}.c"
        target = BUILD / f"lib{tag}.dylib"
        hook = BUILD / f"hook{tag}.dylib"
        merged = BUILD / f"lib{tag}.merged.dylib"
        target_src.write_text(
            f'const char *probe(int n){{return n == 0 ? "{tag.upper()}-ORIG" : "BAD";}}\n'
            'void *coldhook_writable_anchor = (void *)probe;\n')
        hook_src.write_text(
            '#include <coldhook.h>\n'
            'CH_DECLARE_ORIG(same_handler, const char *, int);\n'
            f'const char *same_handler(int n){{return CH_ORIG(same_handler)(n)[0] == \'{tag.upper()}\' '
            f'? "{tag.upper()}-HOOK" : "BAD-ORIG";}}\n'
            f'CH_DYN_SYM("lib{tag}.dylib", "probe", same_handler);\n')
        split = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
        run(cc("-dynamiclib", *split, "-Wl,-headerpad,0x4000", "-install_name",
               f"@loader_path/lib{tag}.dylib", target_src, "-o", target))
        run(cc("-dynamiclib", *split, "-I", INCLUDE, "-L", BUILD, "-lcoldhook",
               "-Wl,-not_for_dyld_shared_cache", "-install_name",
               f"@loader_path/hook{tag}.dylib", hook_src, "-o", hook))
        exported = {line.split()[-1] for line in subprocess.check_output(
            ["nm", "-gU", str(hook)], text=True).splitlines() if line.split()}
        suffix = f"SYM_lib{tag}.dylib__CH__probe__CH__same_handler"
        if exported != {f"_COLDHOOK_DYN_{suffix}", f"_COLDHOOK_ORIG_{suffix}"}:
            raise RuntimeError(f"unexpected hook{tag} exports: {sorted(exported)}")
        run([MERGER, target, hook, merged, "--mode", "shared"])
        run(["codesign", "-f", "-s", "-", merged])
        merged_targets.append(merged)

    driver_src = BUILD / "driver.c"
    driver = BUILD / "driver"
    driver_src.write_text(
        '#include <dlfcn.h>\n#include <stdio.h>\n'
        'int main(int c,char**v){for(int i=1;i<3;i++){void*h=dlopen(v[i],RTLD_NOW);'
        'if(!h){puts(dlerror());return 1;}const char*(*f)(int)=dlsym(h,"probe");'
        'printf("%s\\n",f(0));}return 0;}\n')
    run(cc(driver_src, "-o", driver))
    result = subprocess.run([driver, *merged_targets], capture_output=True, text=True, check=True)
    if result.stdout.splitlines() != ["A-HOOK", "B-HOOK"]:
        raise RuntimeError(f"scoped provider lookup failed: {result.stdout!r}")
    print("OK: duplicate private handler names resolve in provider dylib scope")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
