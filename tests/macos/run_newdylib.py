#!/usr/bin/env python3
"""Тест опции --allow-new-dylibs: хук тянет dylib, которого НЕТ в таргете.

Таргет линкует только libSystem. Хук зовёт zlibVersion() из libz (/usr/lib/libz.1.dylib),
которого таргет не линкует. Без флага merge должен дать чёткую ошибку; с флагом — дописать
LC_LOAD_DYLIB на libz, и хук реально дёргает libz в слитом образе.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
BUILD = os.path.join(HERE, "build", "newdylib")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    if subprocess.run(cmd).returncode != 0: fail(what)


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    target = os.path.join(BUILD, "libtarget.dylib")
    hook = os.path.join(BUILD, "libhook.dylib")
    hook_c = os.path.join(BUILD, "hook_z.c")
    m_off = os.path.join(BUILD, "merged_off.dylib")   # без флага
    m_on = os.path.join(BUILD, "merged_on.dylib")     # с флагом
    driver = os.path.join(BUILD, "driver")

    say("1/5 собираю target (только libSystem)")
    sh(cc("-dynamiclib", *SPLIT, "-install_name", "@rpath/libtarget.dylib",
          "-o", target, os.path.join(HERE, "target.c")), "сборка target")

    say("2/5 собираю хук, зовущий zlibVersion (линкуется -lz)")
    with open(hook_c, "w") as f:
        f.write("""#include "machomerger_hook.h"
#include <zlib.h>
const char *HOOK(domain_for)(int env);
extern const char *ORIG(domain_for)(int);
void *const g_hook_self = (void *)HOOK(domain_for);
const char *HOOK(domain_for)(int env) {
    if (env == 99) return zlibVersion();   // _zlibVersion из libz (нет в таргете)
    return ORIG(domain_for)(env);
}
""")
    sh(cc("-dynamiclib", *SPLIT, "-I", HERE, "-install_name", "@rpath/libhook.dylib",
          "-o", hook, hook_c, os.path.join(HERE, "orig_stubs.S"), "-lz"), "сборка hook")
    deps = subprocess.run(["otool", "-L", hook], capture_output=True, text=True).stdout
    print("   хук зависит от libz?", "libz" in deps)

    say("3/5 merge БЕЗ флага -> ожидаем чёткую ошибку")
    r = subprocess.run([MERGER, target, hook, m_off], capture_output=True, text=True)
    msg = (r.stdout + r.stderr).strip()
    print("   код:", r.returncode, "| вывод:", msg.splitlines()[-1] if msg else "")
    if r.returncode == 0 or "allow-new-dylibs" not in msg:
        fail("ожидал ошибку про --allow-new-dylibs")
    print(f"{GR}   ок — отказал с понятным сообщением{RST}")

    say("4/5 merge С --allow-new-dylibs -> успех")
    r = subprocess.run([MERGER, target, hook, m_on, "--allow-new-dylibs"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout + r.stderr); fail("merge с флагом упал")
    sh(["codesign", "-f", "-s", "-", m_on], "codesign")
    out_deps = subprocess.run(["otool", "-L", m_on], capture_output=True, text=True).stdout
    print("   в merged появился libz?", "libz" in out_deps)
    if "libz" not in out_deps:
        fail("LC_LOAD_DYLIB на libz не дописан")

    say("5/5 запуск: хук дёргает zlibVersion из libz")
    sh(cc("-o", driver, os.path.join(HERE, "driver.c")), "сборка driver")
    r = subprocess.run([driver, m_on], capture_output=True, text=True, timeout=10)
    sys.stdout.write(r.stdout)
    # domain_for(99) теперь = версия zlib (напр. "1.2.12") -> libz реально вызвался
    if r.returncode == 0 and "domain_for(99) = 1." in r.stdout:
        print(f"{GR}OK: B со своим dylib (libz) — merge дописал LC_LOAD_DYLIB, хук работает{RST}")
    else:
        fail(f"прогон не дал ожидаемого (rc={r.returncode})")


if __name__ == "__main__":
    main()
