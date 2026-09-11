#!/usr/bin/env python3
"""Append-режим: таргет БЕЗ LC_SEGMENT_SPLIT_INFO (как реальные приложения/фреймворки).

Реальные бинари не содержат split-info -> мёрджер не может их релоцировать. Append-режим
НЕ двигает таргет A (offset 0, фиксапы/entry валидны как есть), а сегменты хука B аппендит
после A, переписывая заголовок в пределах padding A. Детект — автоматический (A без split-info).

Проверяем оба типа таргета:
  - executable (через exec) — путь ядра строгий (важно: SG_READ_ONLY с сегментов B снимаем,
    иначе ядро отвергает второй несмежный read-only сегмент как EBADMACHO);
  - dylib/framework (через dlopen).

Хук B собираем СО split-info (его-то мы контролируем). -headerpad гарантирует запас заголовка,
как у реальных page-aligned приложений (у крошечных тест-бинарей секции иначе впритык).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.environ.get("COLDHOOK_MERGER") or os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
BUILD = os.path.join(HERE, "build", "nosplit")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
PAD = ["-Wl,-headerpad,0x4000"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    if subprocess.run(cmd, capture_output=True).returncode != 0: fail(what)


def build_hook(path):
    src = os.path.join(BUILD, "hook.c")
    with open(src, "w") as f:
        f.write("""#include "machomerger_hook.h"
const char *HOOK(get_name)(void);
void *const g = (void*)HOOK(get_name);
const char *HOOK(get_name)(void){ return "HOOKED"; }
""")
    sh(cc("-dynamiclib", *SPLIT, "-I", HERE, "-install_name", "@rpath/h.dylib", "-o", path, src), "сборка hook")


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))
    hook = os.path.join(BUILD, "libhook.dylib")
    build_hook(hook)

    # ---------- executable-таргет без split-info ----------
    say("1/2 EXECUTABLE без split-info -> append -> exec")
    esrc = os.path.join(BUILD, "exe.c")
    with open(esrc, "w") as f:
        f.write("""#include <stdio.h>
const char *get_name(void);
int main(void){ printf("name=%s\\n", get_name()); return 0; }
const char *get_name(void){ return "ORIG"; }
""")
    exe = os.path.join(BUILD, "exe_a")
    sh(cc(*PAD, "-o", exe, esrc), "сборка exe")           # БЕЗ split-info
    if subprocess.run(["otool", "-l", exe], capture_output=True, text=True).stdout.count("SPLIT_INFO"):
        fail("таргет неожиданно содержит split-info")
    em = os.path.join(BUILD, "exe_a.coldhook")
    if subprocess.run([MERGER, exe, hook, em], capture_output=True).returncode != 0:
        fail("merge exe упал")
    sh(["codesign", "-f", "-s", "-", em], "codesign exe")
    os.chmod(em, 0o755)
    r = subprocess.run([em], capture_output=True, text=True, timeout=10)
    out = r.stdout + r.stderr
    print("   " + out.strip())
    if "HOOKED" not in out or r.returncode != 0:
        fail(f"executable append не сработал (rc={r.returncode})")

    # ---------- dylib/framework-таргет без split-info ----------
    say("2/2 DYLIB без split-info -> append -> dlopen")
    dsrc = os.path.join(BUILD, "dyl.c")
    with open(dsrc, "w") as f:
        f.write("""const char *get_name(void);
__attribute__((visibility("default"))) const char *call_it(void){ return get_name(); }
const char *get_name(void){ return "ORIG"; }
""")
    dyl = os.path.join(BUILD, "libdyl.dylib")
    sh(cc("-dynamiclib", *PAD, "-install_name", "@rpath/libdyl.dylib", "-o", dyl, dsrc), "сборка dylib")
    dm = os.path.join(BUILD, "libdyl.coldhook.dylib")
    if subprocess.run([MERGER, dyl, hook, dm], capture_output=True).returncode != 0:
        fail("merge dylib упал")
    sh(["codesign", "-f", "-s", "-", dm], "codesign dylib")
    drv = os.path.join(BUILD, "drv")
    with open(os.path.join(BUILD, "drv.c"), "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(void)=dlsym(h,"call_it");'
                'fprintf(stderr,"call_it=%s\\n", fn?fn():"?");return 0;}\n')
    sh(cc("-o", drv, os.path.join(BUILD, "drv.c")), "сборка drv")
    r = subprocess.run([drv, dm], capture_output=True, text=True, timeout=10)
    out = r.stdout + r.stderr
    print("   " + out.strip())
    if "HOOKED" not in out:
        fail("dylib append не сработал")

    print(f"{GR}OK: append-режим работает для exe и dylib без split-info{RST}")


if __name__ == "__main__":
    main()
