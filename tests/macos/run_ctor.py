#!/usr/bin/env python3
"""Тест конструкторов (%ctor): __attribute__((constructor)) в хуке отрабатывает на загрузке.

Современный toolchain кладёт инициализаторы в __TEXT,__init_offsets (32-битные offset'ы от
базы образа). Мёрджер мёрджит секцию, split-info IMG_OFF_32 чинит offset. Проверяем
реалистичный кейс: конструктор И у таргета, И у хука -> оба запускаются после merge.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
BUILD = os.path.join(HERE, "build", "ctor")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    if subprocess.run(cmd, capture_output=True).returncode != 0: fail(what)


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    target = os.path.join(BUILD, "libtarget.dylib")
    hook = os.path.join(BUILD, "libhook.dylib")
    merged = os.path.join(BUILD, "libtarget.coldhook.dylib")
    drv = os.path.join(BUILD, "drv")
    tsrc = os.path.join(BUILD, "target_ct.c")
    hsrc = os.path.join(BUILD, "hook_ct.c")

    say("1/4 собираю target c КОНСТРУКТОРОМ")
    with open(tsrc, "w") as f:
        f.write("""#include <unistd.h>
const char *domain_for(int env);
void *const g_self = (void*)domain_for;
__attribute__((constructor)) static void tctor(void){ write(2, "[target ctor]\\n", 14); }
const char *domain_for(int env){ if(env==0) return "https://prod.real.example"; __builtin_trap(); }
""")
    sh(cc("-dynamiclib", *SPLIT, "-install_name", "@rpath/libtarget.dylib", "-o", target, tsrc), "сборка target")
    sh(["codesign", "-f", "-s", "-", target], "codesign target")

    say("2/4 собираю hook c КОНСТРУКТОРОМ")
    with open(hsrc, "w") as f:
        f.write("""#include "machomerger_hook.h"
#include <unistd.h>
const char *HOOK(domain_for)(int env);
void *const g = (void*)HOOK(domain_for);
__attribute__((constructor)) static void hctor(void){ write(2, "[hook ctor]\\n", 12); }
const char *HOOK(domain_for)(int env){ (void)env; return "https://HOOKED"; }
""")
    sh(cc("-dynamiclib", *SPLIT, "-I", HERE, "-install_name", "@rpath/h.dylib", "-o", hook, hsrc), "сборка hook")

    say("3/4 merge")
    if subprocess.run([MERGER, target, hook, merged], capture_output=True).returncode != 0:
        fail("merge упал")
    sh(["codesign", "-f", "-s", "-", merged], "codesign merged")

    say("4/4 dlopen merged — оба конструктора должны отработать")
    with open(os.path.join(BUILD, "drv.c"), "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(int)=dlsym(h,"domain_for");'
                'fprintf(stderr,"domain_for=%s\\n", fn?fn(0):"?");return 0;}\n')
    sh(cc("-o", drv, os.path.join(BUILD, "drv.c")), "сборка drv")
    r = subprocess.run([drv, merged], capture_output=True, text=True, timeout=10)
    out = r.stdout + r.stderr
    sys.stdout.write("".join("   " + l + "\n" for l in out.splitlines()))

    ok = ("[target ctor]" in out and "[hook ctor]" in out and "HOOKED" in out)
    if ok:
        print(f"{GR}OK: оба конструктора отработали + хук активен{RST}")
    else:
        fail("не отработал какой-то конструктор или хук "
             f"(target_ctor={'[target ctor]' in out}, hook_ctor={'[hook ctor]' in out}, "
             f"hooked={'HOOKED' in out})")


if __name__ == "__main__":
    main()
