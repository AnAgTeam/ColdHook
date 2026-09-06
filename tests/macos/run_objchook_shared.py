#!/usr/bin/env python3
"""Shared-mode Logos %hook: tweak stays a separate dylib, so selrefs remain valid."""
import os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
BUILD = HERE / "build" / "objchook_shared"
PRE = ROOT / "coldhook/logos_prepass.py"; INC = ROOT / "coldhook/include"
SUB = ROOT / "coldhook/substrate"; THEOS = Path(os.environ.get("THEOS", Path.home()/"theos"))
LOGOS = THEOS / "bin/logos.pl"; MERGER = ROOT / "vendor/MachOMerger/.build/release/MachOMerger"

def run(cmd, **kw): return subprocess.run([str(x) for x in cmd], **kw)

def main():
    if not LOGOS.exists(): print(f"SKIP: нет {LOGOS}"); return
    BUILD.mkdir(parents=True, exist_ok=True)
    for p in BUILD.iterdir():
        if p.is_file(): p.unlink()
    (BUILD/"runtime.c").write_text('')
    run(["xcrun","clang","-arch","arm64","-dynamiclib","-I",INC,"-install_name","@loader_path/libcoldhook.dylib",ROOT/"coldhook/shared_runtime.c","-o",BUILD/"libcoldhook.dylib"], check=True)
    (BUILD/"target.m").write_text('''#import <Foundation/Foundation.h>\n@interface Greeter:NSObject - (NSString *)greet; @end\n@implementation Greeter\n- (NSString *)greet { return @"orig"; }\n@end\nconst char *run_greet(void){ return [[[Greeter new] greet] UTF8String]; }\nconst char *coldhook_anchor_text(void){ return "anchor"; }\n''')
    run(["xcrun","clang","-arch","arm64","-dynamiclib","-fobjc-arc","-framework","Foundation","-Wl,-headerpad,0x4000","-install_name","@loader_path/libtarget.dylib",BUILD/"target.m","-o",BUILD/"libtarget.dylib"], check=True)
    (BUILD/"tweak.x").write_text('''#import <Foundation/Foundation.h>\n%hook Greeter\n- (NSString *)greet { return [%orig stringByAppendingString:@"!"]; }\n%end\n// Anchor only makes shared merger load this otherwise ordinary Logos dylib.\n%hookf_shared("libtarget.dylib", const char *, coldhook_anchor_text) { return %orig; }\n''')
    pre = run([sys.executable,PRE,BUILD/"tweak.x"], capture_output=True, text=True)
    if pre.returncode: raise RuntimeError(pre.stderr)
    if "CH_DYN_SYM" not in pre.stdout or "MSHookMessageEx" not in pre.stdout: raise RuntimeError("prepass did not emit shared anchor and Logos hook")
    (BUILD/"tweak.mm").write_text(pre.stdout)
    run(["xcrun","clang","-arch","arm64","-dynamiclib","-fobjc-arc","-framework","Foundation","-I",INC,"-I",SUB,"-I",THEOS/"vendor/include",BUILD/"tweak.mm",SUB/"substrate.m","-L",BUILD,"-lcoldhook","-Wl,-not_for_dyld_shared_cache","-Wl,-headerpad,0x4000","-install_name","@loader_path/tweak.dylib","-lc++","-o",BUILD/"tweak.dylib"], check=True)
    merged = BUILD/"libtarget.shared.dylib"
    run([MERGER,BUILD/"libtarget.dylib",BUILD/"tweak.dylib",merged,"--mode","shared"], check=True)
    run(["codesign","-f","-s","-",merged], check=True)
    (BUILD/"driver.c").write_text('#include <dlfcn.h>\n#include <stdio.h>\nint main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);if(!h)return 2;const char*(*f)(void)=dlsym(h,"run_greet");if(!f)return 3;puts(f());return 0;}\n')
    run(["xcrun","clang","-arch","arm64",BUILD/"driver.c","-o",BUILD/"driver"], check=True)
    p = run([BUILD/"driver",merged], capture_output=True, text=True)
    if p.returncode or p.stdout.strip() != "orig!": raise RuntimeError(p.stdout+p.stderr)
    print("OK: shared Logos %hook работает без coldhook_objc.m (selrefs остаются в tweak dylib)")

if __name__ == "__main__":
    try: main()
    except Exception as e: print(f"FAIL: {e}"); sys.exit(1)
