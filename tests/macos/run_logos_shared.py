#!/usr/bin/env python3
"""End-to-end %hookf_shared regression through the Logos prepass."""
import os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = HERE / "build" / "logos_shared"
PREPASS = ROOT / "coldhook/logos_prepass.py"
MERGER = ROOT / "vendor/MachOMerger/.build/release/MachOMerger"
INCLUDE = ROOT / "coldhook/include"
THEOS = Path(os.environ.get("THEOS", Path.home() / "theos"))
LOGOS = THEOS / "bin/logos.pl"

def run(cmd, **kw):
    return subprocess.run([str(x) for x in cmd], **kw)

def main():
    if not LOGOS.exists():
        print(f"SKIP: нет {LOGOS}"); return
    BUILD.mkdir(parents=True, exist_ok=True)
    for p in BUILD.iterdir():
        if p.is_file(): p.unlink()
    runtime = BUILD / "libcoldhook.dylib"
    target = BUILD / "libcore.dylib"
    hook = BUILD / "hook.dylib"
    merged = BUILD / "libcore.shared.dylib"
    tweak_x = BUILD / "Tweak.x"
    tweak_mm = BUILD / "Tweak.mm"
    driver_c = BUILD / "driver.c"
    driver = BUILD / "driver"
    run(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", "-I", INCLUDE,
         "-install_name", "@loader_path/libcoldhook.dylib", ROOT / "coldhook/shared_runtime.c", "-o", runtime], check=True)
    (BUILD / "core.c").write_text('const char *get_label_text(void);\nvoid *coldhook_anchor = (void *)get_label_text;\nconst char *get_label_text(void){ return "ORIG"; }\n')
    run(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", "-Wl,-headerpad,0x4000",
         "-install_name", "@loader_path/libcore.dylib", BUILD / "core.c", "-o", target], check=True)
    tweak_x.write_text('''%hookf_shared("libcore.dylib", const char *, get_label_text) {
    return "SHARED-HOOK";
}
''')
    pre = run([sys.executable, PREPASS, tweak_x], capture_output=True, text=True)
    if pre.returncode: raise RuntimeError(pre.stderr)
    if "CH_DYN_SYM" not in pre.stdout: raise RuntimeError("prepass did not emit CH_DYN_SYM")
    tweak_mm.write_text(pre.stdout)
    run(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", "-fobjc-arc", "-I", INCLUDE,
         "-L", BUILD, "-lcoldhook", "-Wl,-not_for_dyld_shared_cache", "-Wl,-headerpad,0x4000",
         "-install_name", "@loader_path/hook.dylib", tweak_mm, "-o", hook], check=True)
    run([MERGER, target, hook, merged, "--mode", "shared"], check=True)
    run(["codesign", "-f", "-s", "-", merged], check=True)
    driver_c.write_text('#include <dlfcn.h>\n#include <stdio.h>\nint main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW); if(!h)return 2; const char*(*f)(void)=dlsym(h,"get_label_text"); if(!f)return 3; puts(f()); return 0;}\n')
    run(["xcrun", "clang", "-arch", "arm64", driver_c, "-o", driver], check=True)
    p = run([driver, merged], capture_output=True, text=True)
    if p.returncode or "SHARED-HOOK" not in p.stdout: raise RuntimeError(p.stdout + p.stderr)
    print("OK: %hookf_shared -> CH_DYN_SYM -> shared runtime работает")

if __name__ == "__main__":
    try: main()
    except Exception as e: print(f"FAIL: {e}"); sys.exit(1)
