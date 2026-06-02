#!/usr/bin/env python3
"""GATED-хук: статически установлен, но рантайм-переключаемый (CH_HOOK_SYM_GATED) + ORIG.

Фундамент под Logos-группы (`%init(Group)`) и рантайм вкл/выкл хука без W^X. Первую инструкцию
цели мёрджер патчит на ТОНКИЙ THUNK, прыгающий через указатель `coldhook_disp_g` в писчем __DATA.
Дефолт указателя = ORIG => хук ВЫКЛЮЧЕН (цель работает прозрачно). Конструктор по env флипает на
замену. Проверяем В ОДНОМ бинаре оба состояния:
  без CH_GROUP   -> disp=ORIG  -> greeting(99)=hi:99   (хук стоит, но прозрачен)
  CH_GROUP=1     -> disp=замена -> greeting(99)=FIXED-99 (включён)

Цель — dylib с экспортом, без split-info (append-режим). Указатель ложится в __BDATA (писчий) —
ключевая проверка, что рантайм-запись не словит SIGBUS.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
INCLUDE = os.path.join(ROOT, "coldhook", "include")
BUILD = os.path.join(HERE, "build_gated")
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

    def p(n): return os.path.join(BUILD, n)

    say("1/4 цель: dylib с экспортом greeting() (без split-info)")
    with open(p("greet.c"), "w") as f:
        f.write('const char *greeting(int n){ if(n==0) return "ZERO"; '
                'static char b[16]; __builtin_snprintf(b,16,"hi:%d",n); return b; }\n')
    lib = p("libgreet.dylib")
    sh(cc("-dynamiclib", p("greet.c"), "-o", lib,
          "-install_name", "@loader_path/libgreet.dylib", "-Wl,-headerpad,0x4000"), "сборка либы")
    sh(["codesign", "-f", "-s", "-", lib], "codesign либы")

    say("2/4 хук: CH_HOOK_SYM_GATED + конструктор-флип по env")
    with open(p("hook.c"), "w") as f:
        f.write('''#include <coldhook.h>
#include <stdlib.h>
CH_DECLARE_ORIG(g, const char *, int);
CH_DECLARE_GATE(g);
__attribute__((used))
const char *g(int n){ if(n==99) return "FIXED-99"; return CH_ORIG(g)(n); }
CH_HOOK_SYM_GATED("greeting", g);
__attribute__((constructor)) static void init(void){
    if (getenv("CH_GROUP")) CH_GATE_ENABLE(g);   // %init(Group) ВКЛ; иначе остаётся ORIG (ВЫКЛ)
}
''')
    hook = p("hook.dylib")
    sh(cc("-I", INCLUDE, "-dynamiclib", p("hook.c"), "-o", hook,
          "-install_name", "@loader_path/hook.dylib",
          "-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info", "-Wl,-no_warn_inits"), "сборка хука")

    say("3/4 merge (append) + главный exe")
    if subprocess.run([MERGER, lib, hook, p("merged.dylib"), "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail("merge упал")
    os.replace(p("merged.dylib"), lib)
    sh(["codesign", "-f", "-s", "-", lib], "codesign merged")
    with open(p("app.c"), "w") as f:
        f.write('#include <stdio.h>\n#include <stdlib.h>\nextern const char *greeting(int);\n'
                'int main(int c,char**v){ printf("greeting=%s\\n", greeting(c>1?atoi(v[1]):0)); }\n')
    app = p("app")
    sh(cc(p("app.c"), lib, "-o", app), "линковка exe")
    sh(["codesign", "-f", "-s", "-", app], "codesign exe")

    say("4/4 запуск: OFF (прозрачно как оригинал) vs ON (замена)")
    cases = [
        ({},               {"0": "ZERO", "5": "hi:5", "99": "hi:99"},     "OFF"),
        ({"CH_GROUP": "1"}, {"0": "ZERO", "5": "hi:5", "99": "FIXED-99"}, "ON"),
    ]
    for env, want, label in cases:
        e = {**os.environ, **env}
        for arg, exp in want.items():
            r = subprocess.run([app, arg], capture_output=True, text=True, timeout=10, env=e)
            out = (r.stdout + r.stderr).strip()
            ok = (f"greeting={exp}" in out and r.returncode == 0)
            print(f"   [{label}] greeting({arg}) -> {out}  [{'ok' if ok else 'BAD'}]")
            if not ok:
                fail(f"[{label}] greeting({arg}): ждал {exp}, got '{out}' rc={r.returncode}")
    print(f"{GR}OK: gated-хук — статически установлен, рантайм-переключаемый (дефолт OFF=ORIG){RST}")


if __name__ == "__main__":
    main()
