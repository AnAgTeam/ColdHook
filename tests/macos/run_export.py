#!/usr/bin/env python3
"""Хук ЭКСПОРТИРОВАННОЙ функции по имени (CH_HOOK_SYM) + ORIG, запускаемый на macOS.

Сценарий «хук публичного API библиотеки»: цель — dylib, экспортирующая `greeting(int)`;
мёрджим хук ПРЯМО В ЛИБУ, патчим её экспорт по символу. Это by-name через ПУБЛИЧНЫЙ
макрос coldhook.h (в отличие от Swift-only run_swift.py) на чистом C.

`greeting`: первая инструкция — `cbz w0` (guard на `n == 0`), поэтому ORIG-слот обязан
ПЕРЕЭНКОДИТЬ сохранённую инструкцию под адрес слота. Проверяем:
  greeting(0)  -> ORIG, cbz берётся    -> "ZERO"
  greeting(5)  -> ORIG, cbz не берётся -> "hi:5"
  greeting(99) -> хук фиксит           -> "FIXED-99"

Либа собрана БЕЗ split-info (как реальная) -> append-режим. Главный exe линкуется с
пропатченной либой (тот же install_name) и зовёт экспорт.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
INCLUDE = os.path.join(ROOT, "coldhook", "include")
BUILD = os.path.join(HERE, "build_export")
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-800:]}")
    return r


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    def p(name): return os.path.join(BUILD, name)

    say("1/4 собираю dylib-цель, экспортирующую greeting() (без split-info)")
    with open(p("greet.c"), "w") as f:
        f.write('''const char *greeting(int n) {
    if (n == 0) return "ZERO";        // cbz w0 -> проверяет переэнкод ORIG
    static char buf[32]; __builtin_snprintf(buf, sizeof buf, "hi:%d", n); return buf;
}
''')
    lib = p("libgreet.dylib")
    sh(cc("-dynamiclib", p("greet.c"), "-o", lib,
          "-install_name", "@rpath/libgreet.dylib", "-Wl,-headerpad,0x4000"), "сборка либы")
    sh(["codesign", "-f", "-s", "-", lib], "codesign либы")
    if subprocess.run(["otool", "-l", lib], capture_output=True, text=True).stdout.count("SPLIT_INFO"):
        fail("либа неожиданно со split-info")

    say("2/4 собираю хук (CH_HOOK_SYM по экспорту + ORIG)")
    with open(p("hook.c"), "w") as f:
        f.write('''#include <coldhook.h>
CH_DECLARE_ORIG(ch_greeting, const char *, int);
const char *ch_greeting(int n) {
    if (n == 99) return "FIXED-99";          // чиним
    return CH_ORIG(ch_greeting)(n);          // остальное -> ОРИГИНАЛ экспорта
}
CH_HOOK_SYM("greeting", ch_greeting);
''')
    hook = p("hook.dylib")
    sh(cc("-I", INCLUDE, "-dynamiclib", p("hook.c"), "-o", hook,
          "-install_name", "@rpath/hook.dylib",
          "-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"), "сборка хука")

    say("3/4 мёржу хук в либу (append) и линкую главный exe")
    if subprocess.run([MERGER, lib, hook, p("libgreet_hooked.dylib"), "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail("merge упал")
    os.replace(p("libgreet_hooked.dylib"), lib)   # подменяем пропатченной (тот же install_name)
    sh(["codesign", "-f", "-s", "-", lib], "codesign merged либы")
    with open(p("app.c"), "w") as f:
        f.write('''#include <stdio.h>
#include <stdlib.h>
extern const char *greeting(int);
int main(int c, char **v) { printf("greeting=%s\\n", greeting(c > 1 ? atoi(v[1]) : 0)); }
''')
    app = p("app")
    sh(cc(p("app.c"), "-o", app, "-L", BUILD, "-lgreet", "-Wl,-rpath," + BUILD), "линковка exe")
    sh(["codesign", "-f", "-s", "-", app], "codesign exe")

    say("4/4 запуск: ORIG (cbz берётся / не берётся) + фикс экспорта")
    want = {"0": "ZERO", "5": "hi:5", "99": "FIXED-99"}
    for arg, exp in want.items():
        r = subprocess.run([app, arg], capture_output=True, text=True, timeout=10)
        out = (r.stdout + r.stderr).strip()
        mark = "ok" if (f"greeting={exp}" in out and r.returncode == 0) else "BAD"
        print(f"   greeting({arg}) -> {out}  [{mark}]")
        if mark == "BAD":
            fail(f"greeting({arg}): ждал {exp}, got '{out}' rc={r.returncode}")
    print(f"{GR}OK: by-name хук экспорта (CH_HOOK_SYM) + ORIG работает{RST}")


if __name__ == "__main__":
    main()
