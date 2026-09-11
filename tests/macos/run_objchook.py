#!/usr/bin/env python3
"""E2E: Logos %hook (ObjC-свиззл) через ВСЮ цепочку ColdTheos.

Доказывает, что %hook работает из коробки: твик с %hook -> ColdHook-пре-пасс -> logos.pl ->
компиляция с substrate.m (шим MSHookMessageEx) + coldhook_objc.m (бутстрап) -> merge (append) в
ObjC-таргет -> загрузка -> свиззл реально применился.

Тело хука делает message-send ([%orig stringByAppendingString:@"!"]) -> задействует selref в ТЕЛЕ,
который merge переименовал в __BDATA_CONST. ObjC-runtime его не уникует -> нужен бутстрап.

Кейсы:
  A) с coldhook_objc.m:  свиззл + %orig + message-send в теле -> "orig!"
  B) контроль БЕЗ бутстрапа: тело шлёт по неуникнутому selref -> крэш/мимо (НЕ "orig!").
     (дефенсивный шим уникует только селектор РЕГИСТРАЦИИ -> свиззл встаёт, но тело падает)

Требует theos (logos.pl). Без него — SKIP.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.environ.get("COLDHOOK_MERGER") or os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
INCLUDE = os.path.join(ROOT, "coldhook", "include")
PREPASS = os.path.join(ROOT, "coldhook", "logos_prepass.py")
SUBINC = os.path.join(ROOT, "coldhook", "substrate")
SUBM = os.path.join(ROOT, "coldhook", "substrate", "substrate.m")
OBJM = os.path.join(ROOT, "coldhook", "substrate", "coldhook_objc.m")
BUILD = os.path.join(HERE, "build", "objchook")
THEOS = os.environ.get("THEOS", os.path.expanduser("~/theos"))
LOGOS = os.path.join(THEOS, "bin", "logos.pl")
THEOSINC = os.path.join(THEOS, "vendor", "include")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, YL, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-900:]}")
    return r


def p(n): return os.path.join(BUILD, n)

TARGET_SRC = """#import <Foundation/Foundation.h>
@interface Greeter : NSObject
- (NSString *)greet;
@end
@implementation Greeter
- (NSString *)greet { return @"orig"; }
@end
const char *run_greet(void) { return [[[Greeter new] greet] UTF8String]; }
"""

# %hook со свиззлом + %orig + message-send в теле (selref stringByAppendingString: -> бутстрап).
TWEAK_SRC = """#import <Foundation/Foundation.h>
%hook Greeter
- (NSString *)greet {
    NSString *o = %orig;                            // оригинал -> "orig"
    return [o stringByAppendingString:@"!"];        // selref В ТЕЛЕ -> нужен бутстрап
}
%end
"""


def build_case(tag, with_bootstrap):
    target = p(f"libtarget_{tag}.dylib")
    with open(p(f"target_{tag}.m"), "w") as f:
        f.write(TARGET_SRC)
    sh(cc("-dynamiclib", "-fobjc-arc", "-framework", "Foundation", *SPLIT, "-Wl,-headerpad,0x4000",
          "-install_name", "@rpath/libtarget.dylib", "-o", target, p(f"target_{tag}.m")), "сборка target")
    sh(["codesign", "-f", "-s", "-", target], "codesign target")

    xsrc = p(f"Tweak_{tag}.x")
    with open(xsrc, "w") as f:
        f.write(TWEAK_SRC)
    r = subprocess.run([sys.executable, PREPASS, xsrc], capture_output=True, text=True)
    if r.returncode != 0: fail(f"пре-пасс/logos ({tag}):\n{r.stderr[-900:]}")
    mm = r.stdout
    if "MSHookMessageEx" not in mm: fail(f"[{tag}] logos не сгенерил MSHookMessageEx (%hook не раскрылся)")
    mmf = p(f"Tweak_{tag}.mm")
    with open(mmf, "w") as f:
        f.write(mm)

    tweak = p(f"tweak_{tag}.dylib")
    files = [SUBM] + ([OBJM] if with_bootstrap else [])
    sh(cc("-I", INCLUDE, "-I", SUBINC, "-I", THEOSINC, "-fobjc-arc", "-framework", "Foundation",
          "-dynamiclib", mmf, *files, "-lc++", *SPLIT, "-Wl,-no_warn_inits",
          "-o", tweak, "-install_name", "@rpath/t.dylib"), "сборка твика")

    merged = p(f"merged_{tag}.dylib")
    if subprocess.run([MERGER, target, tweak, merged, "--mode", "append", "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail(f"[{tag}] merge упал")
    sh(["codesign", "-f", "-s", "-", merged], "codesign merged")

    drv = p(f"drv_{tag}")
    with open(p(f"drv_{tag}.c"), "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(void)=dlsym(h,"run_greet");'
                'fprintf(stdout,"greet=%s\\n", fn?fn():"?");return 0;}\n')
    sh(cc("-o", drv, p(f"drv_{tag}.c")), "сборка drv")
    r = subprocess.run([drv, merged], capture_output=True, text=True, timeout=10)
    out = (r.stdout + r.stderr)
    for l in out.splitlines():
        print("   " + l)
    return out, r.returncode


def main():
    if not os.path.exists(LOGOS):
        print(f"{YL}SKIP run_objchook: нет theos/logos.pl ({LOGOS}){RST}")
        return
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    say("A: %hook через ColdTheos С бутстрапом -> свиззл + %orig + тело работают")
    out, rc = build_case("boot", with_bootstrap=True)
    if not ("greet=orig!" in out and rc == 0):
        fail(f"[boot] ждал greet=orig! и rc=0, got rc={rc}")
    print(f"{GR}   [boot] OK: greet=orig! (свиззл + %orig + message-send в теле){RST}")

    say("B: контроль БЕЗ бутстрапа -> selref в теле не уникнут -> крэш/мимо")
    out, rc = build_case("noboot", with_bootstrap=False)
    if "greet=orig!" in out:
        fail("[noboot] свиззл с телом сработал БЕЗ бутстрапа — тест не доказывает необходимость")
    print(f"{GR}   [noboot] OK: без бутстрапа тело не отработало (rc={rc}){RST}")

    print(f"{GR}OK: Logos %hook работает через ColdTheos (свиззл+%orig+тело); бутстрап необходим{RST}")


if __name__ == "__main__":
    main()
