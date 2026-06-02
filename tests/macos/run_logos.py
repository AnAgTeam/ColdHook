#!/usr/bin/env python3
"""Logos-интеграция: %hookf (хук C-функции) → статика ColdHook, через ПРЕ-ПАСС + сток logos.pl.

Пишешь обычный Logos-твик; ColdHook-пре-пасс переводит %hookf в CH_HOOK_SYM (статический патч
на merge, без W^X/MSHookFunction), а %orig/%ctor отдаёт стоковому logos.pl. Здесь — ungrouped
случай (без групп/ObjC, поэтому substrate не нужен): %hookf-detour чинит get_label_text,
вызывая %orig, а %ctor логирует загрузку.

Требует theos (logos.pl). Без него — SKIP (не валит регрессию).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
INCLUDE = os.path.join(ROOT, "coldhook", "include")
PREPASS = os.path.join(ROOT, "coldhook", "logos_prepass.py")
BUILD = os.path.join(HERE, "build_logos")
THEOS = os.environ.get("THEOS", os.path.expanduser("~/theos"))
LOGOS = os.path.join(THEOS, "bin", "logos.pl")
CY, RD, GR, YL, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-900:]}")
    return r


def main():
    if not os.path.exists(LOGOS):
        print(f"{YL}SKIP run_logos: нет theos/logos.pl ({LOGOS}){RST}")
        return
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    def p(n): return os.path.join(BUILD, n)

    say("1/5 цель: dylib с экспортом get_label_text() -> 'Fail text' (без split-info)")
    with open(p("core.c"), "w") as f:
        f.write('const char *get_label_text(void){ return "Fail text"; }\n')
    lib = p("libcore.dylib")
    sh(cc("-dynamiclib", p("core.c"), "-o", lib,
          "-install_name", "@loader_path/libcore.dylib", "-Wl,-headerpad,0x4000"), "сборка либы")
    sh(["codesign", "-f", "-s", "-", lib], "codesign либы")

    say("2/5 Logos-твик (%hookf detour + %orig + %ctor)")
    with open(p("Tweak.x"), "w") as f:
        f.write('''#import <Foundation/Foundation.h>

%hookf(const char *, get_label_text) {
    const char *o = %orig;                       // оригинал
    NSLog(@"[coldhook] orig was: %s", o);
    return "Hooked by ColdHook";                 // подмена
}

%ctor {
    NSLog(@"[coldhook] tweak loaded");
}
''')

    say("3/5 ColdHook-пре-пасс -> сток logos.pl -> .mm")
    r = subprocess.run(["python3", PREPASS, p("Tweak.x")], capture_output=True, text=True)
    if r.returncode != 0: fail(f"пре-пасс/logos:\n{r.stderr[-900:]}")
    mm = r.stdout
    if "MSHookFunction" in mm: fail("MSHookFunction остался — %hookf не перехвачен пре-пассом")
    if "CH_HOOK_SYM" not in mm: fail("нет CH_HOOK_SYM — пре-пасс не сгенерил статический glue")
    with open(p("Tweak.mm"), "w") as f:
        f.write(mm)

    say("4/5 компиляция твика + merge (append)")
    tweak = p("tweak.dylib")
    sh(cc("-I", INCLUDE, "-fobjc-arc", "-framework", "Foundation", "-dynamiclib", p("Tweak.mm"),
          "-o", tweak, "-install_name", "@loader_path/tweak.dylib",
          "-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info", "-Wl,-no_warn_inits"), "сборка твика")
    if subprocess.run([MERGER, lib, tweak, p("merged.dylib"), "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail("merge упал")
    os.replace(p("merged.dylib"), lib)
    sh(["codesign", "-f", "-s", "-", lib], "codesign merged")

    say("5/5 запуск")
    with open(p("app.c"), "w") as f:
        f.write('#include <stdio.h>\nextern const char *get_label_text(void);\n'
                'int main(void){ printf("label=%s\\n", get_label_text()); }\n')
    app = p("app")
    sh(cc(p("app.c"), lib, "-o", app), "линковка exe")
    sh(["codesign", "-f", "-s", "-", app], "codesign exe")
    r = subprocess.run([app], capture_output=True, text=True, timeout=10)
    out = (r.stdout + r.stderr).strip()
    print("   " + out.replace("\n", "\n   "))
    ok = ("label=Hooked by ColdHook" in out and "orig was: Fail text" in out
          and "tweak loaded" in out and r.returncode == 0)
    if not ok:
        fail(f"ждал замену + %orig + %ctor, got:\n{out} rc={r.returncode}")
    print(f"{GR}OK: Logos %hookf -> статика ColdHook (пре-пасс + сток logos.pl){RST}")


if __name__ == "__main__":
    main()
