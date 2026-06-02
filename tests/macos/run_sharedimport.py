#!/usr/bin/env python3
"""Регресс: таргет A и хук B импортируют ОДИН И ТОТ ЖЕ символ (write).

Раньше внешний импорт B, совпадающий по имени с импортом таргета A, ошибочно резолвился
в undefined-символ A (его же импорт) и эмитился как rebase в мусор -> br в невалид.
Фикс: resolveInternal матчит в symtab A только DEFINED-символы (N_SECT). Тут и A, и B
зовут write -> у обоих должен забиндиться libSystem write, хук активен.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
BUILD = os.path.join(HERE, "build_shared")
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
    tsrc = os.path.join(BUILD, "target.c")
    hsrc = os.path.join(BUILD, "hook.c")

    say("1/4 собираю target (зовёт write — общий импорт)")
    with open(tsrc, "w") as f:
        f.write("""#include <unistd.h>
const char *pick(void);
void *const g_self = (void*)pick;
const char *pick(void){ write(2, "[A write]\\n", 10); return "ORIG"; }
""")
    sh(cc("-dynamiclib", *SPLIT, "-install_name", "@rpath/libtarget.dylib", "-o", target, tsrc), "сборка target")
    sh(["codesign", "-f", "-s", "-", target], "codesign target")

    say("2/4 собираю hook (тоже зовёт write — тот же импорт, что у A)")
    with open(hsrc, "w") as f:
        f.write("""#include "machomerger_hook.h"
#include <unistd.h>
const char *HOOK(pick)(void);
void *const g = (void*)HOOK(pick);
const char *HOOK(pick)(void){ write(2, "[B write]\\n", 10); return "HOOKED"; }
""")
    sh(cc("-dynamiclib", *SPLIT, "-I", HERE, "-install_name", "@rpath/h.dylib", "-o", hook, hsrc), "сборка hook")

    say("3/4 merge")
    if subprocess.run([MERGER, target, hook, merged], capture_output=True).returncode != 0:
        fail("merge упал")
    sh(["codesign", "-f", "-s", "-", merged], "codesign merged")

    say("4/4 dlopen + вызов pick — write у B должен забиндиться, хук активен")
    with open(os.path.join(BUILD, "drv.c"), "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(void)=dlsym(h,"pick");'
                'fprintf(stderr,"pick=%s\\n", fn?fn():"?");return 0;}\n')
    sh(cc("-o", drv, os.path.join(BUILD, "drv.c")), "сборка drv")
    r = subprocess.run([drv, merged], capture_output=True, text=True, timeout=10)
    out = r.stdout + r.stderr
    sys.stdout.write("".join("   " + l + "\n" for l in out.splitlines()))

    if "[B write]" in out and "HOOKED" in out:
        print(f"{GR}OK: общий импорт write забиндился у B, хук активен{RST}")
    else:
        fail(f"общий импорт сломан (B_write={'[B write]' in out}, hooked={'HOOKED' in out})")


if __name__ == "__main__":
    main()
