#!/usr/bin/env python3
"""Путь B: embedded ObjC %hook через self-registration в %ctor.

Проблема: append переименовывает сегменты хука (__DATA_CONST -> __BDATA_CONST), а ObjC-runtime
сканирует __objc_selrefs только в __DATA/__DATA_CONST -> selref'ы хука НЕ уникуются -> @selector
в хуке держит указатель на свою копию cstring, а не канонический SEL -> class_getInstanceMethod
не находит метод -> свиззл не ставится.

Путь B: сгенерированный конструктор хука сам уникует свои selref'ы. Бутстрап через runtime:
  dladdr(сам себя) -> mach_header МЁРДЖНУТОГО образа -> getsectiondata("__BDATA_CONST"/"__BDATA",
  "__objc_selrefs") -> по каждому entry: *p = sel_registerName(*p). Берём именно __B*-сегмент
  (метадата хука), НЕ трогаем selref'ы таргета (они в честном read-only __DATA_CONST -> крэш).

Доказываем НЕОБХОДИМОСТЬ и ДОСТАТОЧНОСТЬ: один и тот же свиззл-хук мёрджим с бутстрапом и без.
  - без бутстрапа: class_getInstanceMethod(@selector(greet)) -> NULL -> свиззл FAILED -> "orig"
  - с бутстрапом:  selref уникнут -> свиззл ставится -> "HOOKED"
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
BUILD = os.path.join(HERE, "build_objc")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-900:]}")
    return r


def p(n): return os.path.join(BUILD, n)


# --- target: ObjC класс Greeter + C-обёртка, зовущая [g greet] через obj-c dispatch ---
TARGET_SRC = """#import <Foundation/Foundation.h>
@interface Greeter : NSObject
- (NSString *)greet;
@end
@implementation Greeter
- (NSString *)greet { return @"orig"; }
@end
const char *run_greet(void) {
    Greeter *g = [Greeter new];
    return [[g greet] UTF8String];   // обычный objc_msgSend -> подхватит свиззл
}
"""

# --- hook: новый IMP + свиззл Greeter.greet. @selector(greet) -> selref (вот что чинит Путь B) ---
# @@BOOTSTRAP@@ — место под Путь-B-конструктор (или пусто в контрольном прогоне).
HOOK_SRC = """#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <unistd.h>
@@BOOTSTRAP@@
static NSString *hooked_greet(id self, SEL _cmd) { (void)self; (void)_cmd; return @"HOOKED"; }
__attribute__((constructor)) static void install_hook(void) {
    Class c = objc_getClass("Greeter");
    Method m = class_getInstanceMethod(c, @selector(greet));   // нужен УНИКНУТЫЙ SEL
    if (m) { method_setImplementation(m, (IMP)hooked_greet); write(2, "[swizzled]\\n", 11); }
    else    { write(2, "[swizzle FAILED]\\n", 17); }
}
"""

# Путь B: бутстрап-конструктор. Должен идти ПЕРВЫМ (уникнуть selref'ы до install_hook).
BOOTSTRAP = """#include <dlfcn.h>
#include <stdio.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
__attribute__((constructor)) static void coldhook_objc_bootstrap(void) {
    Dl_info info;
    if (!dladdr((void *)coldhook_objc_bootstrap, &info)) return;
    const struct mach_header_64 *mh = (const struct mach_header_64 *)info.dli_fbase;
    unsigned long sz = 0;
    uint8_t *b = getsectiondata(mh, "__BDATA_CONST", "__objc_selrefs", &sz);  // переименованный __DATA_CONST
    if (!b) b = getsectiondata(mh, "__BDATA", "__objc_selrefs", &sz);          // или __DATA на старых toolchain
    if (b && sz) {
        SEL *q = (SEL *)b;
        for (unsigned long i = 0; i < sz / sizeof(SEL); i++)
            q[i] = sel_registerName((const char *)(void *)q[i]);
        char msg[56]; int n = snprintf(msg, sizeof msg, "[coldhook objc: uniqued %lu selrefs]\\n", sz / sizeof(SEL));
        write(2, msg, n);
    } else {
        write(2, "[coldhook objc: no __B selrefs found]\\n", 38);
    }
}
"""


def build_case(tag, bootstrap, want_swizzle, want_greet):
    target = p(f"libtarget_{tag}.dylib")
    hook = p(f"libhook_{tag}.dylib")
    merged = p(f"merged_{tag}.dylib")
    drv = p(f"drv_{tag}")

    with open(p(f"target_{tag}.m"), "w") as f:
        f.write(TARGET_SRC)
    sh(cc("-dynamiclib", "-fobjc-arc", "-framework", "Foundation", *SPLIT, "-Wl,-headerpad,0x4000",
          "-install_name", "@rpath/libtarget.dylib", "-o", target, p(f"target_{tag}.m")), "сборка target")
    sh(["codesign", "-f", "-s", "-", target], "codesign target")

    with open(p(f"hook_{tag}.m"), "w") as f:
        f.write(HOOK_SRC.replace("@@BOOTSTRAP@@", bootstrap))
    sh(cc("-dynamiclib", "-fobjc-arc", "-framework", "Foundation", *SPLIT,
          "-install_name", "@rpath/h.dylib", "-o", hook, p(f"hook_{tag}.m")), "сборка hook")

    # append-режим: сегменты B -> __B* (предпосылка Пути B). --allow-new-dylibs на случай, если
    # таргет не линкует libobjc/Foundation, а хук линкует.
    if subprocess.run([MERGER, target, hook, merged, "--mode", "append", "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail(f"[{tag}] merge упал")
    sh(["codesign", "-f", "-s", "-", merged], "codesign merged")

    with open(p(f"drv_{tag}.c"), "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(void)=dlsym(h,"run_greet");'
                'fprintf(stderr,"greet=%s\\n", fn?fn():"?");return 0;}\n')
    sh(cc("-o", drv, p(f"drv_{tag}.c")), "сборка drv")
    r = subprocess.run([drv, merged], capture_output=True, text=True, timeout=10)
    out = r.stdout + r.stderr
    sys.stdout.write("".join("   " + l + "\n" for l in out.splitlines()))

    sw_ok = want_swizzle in out
    gr_ok = f"greet={want_greet}" in out
    if not (sw_ok and gr_ok):
        fail(f"[{tag}] ждал свиззл='{want_swizzle}' и greet='{want_greet}', "
             f"got swizzle={sw_ok} greet={gr_ok}")
    print(f"{GR}   [{tag}] OK: {want_swizzle.strip()} + greet={want_greet}{RST}")


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    say("1/2 КОНТРОЛЬ: без бутстрапа selref'ы хука НЕ уникнуты -> свиззл должен ПРОВАЛИТЬСЯ")
    build_case("noboot", "", "[swizzle FAILED]", "orig")

    say("2/2 ПУТЬ B: бутстрап уникует selref'ы хука -> свиззл встаёт -> HOOKED")
    build_case("boot", BOOTSTRAP, "[swizzled]", "HOOKED")

    print(f"{GR}OK: Путь B доказан — selref-bootstrap НЕОБХОДИМ (контроль падает) и ДОСТАТОЧЕН{RST}")


if __name__ == "__main__":
    main()
