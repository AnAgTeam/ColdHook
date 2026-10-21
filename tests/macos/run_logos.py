#!/usr/bin/env python3
"""Logos-интеграция: %hookf (хук C-функции) → статика ColdHook, через ПРЕ-ПАСС + сток logos.pl.

Пишешь обычный Logos-твик; ColdHook-пре-пасс переводит %hookf в CH_HOOK_SYM(_GATED) (статический
патч на merge, без W^X/MSHookFunction), а %orig/%ctor/%group/%init отдаёт стоковому logos.pl.

Два кейса:
  A) ungrouped %hookf detour + %orig + %ctor (substrate не нужен — нет групп/ObjC).
  B) %group + %hookf: gated-хук, включается на %init(Group). substrate-шим нужен для компиляции
     (logos тянет CydiaSubstrate/CydiaSubstrate.h) — линкуем coldhook/substrate.

ObjC %hook через merge ПОКА не покрыт: в append-режиме сегменты B переименованы (__DATA->__BDATA),
а ObjC-runtime сканирует __objc_selrefs только в __DATA/__DATA_CONST -> selref'ы B не уникаются.
Это отдельная research-задача; %hookf (C) её не имеет.

Требует theos (logos.pl). Без него — SKIP.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from coldhook.toolchain import ensure_merger

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = ensure_merger()
INCLUDE = os.path.join(ROOT, "coldhook", "include")
PREPASS = os.path.join(ROOT, "coldhook", "logos_prepass.py")
SUBINC = os.path.join(ROOT, "coldhook", "substrate")
SUBM = os.path.join(ROOT, "coldhook", "substrate", "substrate.m")
BUILD = os.path.join(HERE, "build", "logos")
THEOS = os.environ.get("THEOS", os.path.expanduser("~/theos"))
LOGOS = os.path.join(THEOS, "bin", "logos.pl")
THEOSINC = os.path.join(THEOS, "vendor", "include")
CY, RD, GR, YL, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-900:]}")
    return r


def p(n): return os.path.join(BUILD, n)


def build_case(tag, tweak_src, extra_compile, must_have, expect_runs):
    """Собрать цель+твик через пре-пасс+logos, смёрджить, прогнать app в разных env."""
    core = p(f"core_{tag}.c")
    with open(core, "w") as f:
        f.write('const char *get_label_text(void){ return "Fail text"; }\n')
    lib = p(f"libcore_{tag}.dylib")
    sh(cc("-dynamiclib", core, "-o", lib,
          "-install_name", f"@loader_path/libcore_{tag}.dylib", "-Wl,-headerpad,0x4000"), "сборка либы")
    sh(["codesign", "-f", "-s", "-", lib], "codesign либы")

    xsrc = p(f"Tweak_{tag}.x")
    with open(xsrc, "w") as f:
        f.write(tweak_src)
    r = subprocess.run([sys.executable, PREPASS, xsrc], capture_output=True, text=True)
    if r.returncode != 0: fail(f"пре-пасс/logos ({tag}):\n{r.stderr[-900:]}")
    mm = r.stdout
    if "MSHookFunction" in mm: fail(f"[{tag}] MSHookFunction остался — %hookf не перехвачен")
    for tok in must_have:
        if tok not in mm: fail(f"[{tag}] нет '{tok}' в выводе пре-пасса")
    mmf = p(f"Tweak_{tag}.mm")
    with open(mmf, "w") as f:
        f.write(mm)

    tweak = p(f"tweak_{tag}.dylib")
    sh(cc("-I", INCLUDE, "-fobjc-arc", "-framework", "Foundation", "-dynamiclib", mmf, *extra_compile,
          "-o", tweak, "-install_name", f"@loader_path/tweak_{tag}.dylib",
          "-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info", "-Wl,-no_warn_inits"), "сборка твика")
    if subprocess.run([MERGER, lib, tweak, p(f"m_{tag}.dylib"), "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail(f"[{tag}] merge упал")
    os.replace(p(f"m_{tag}.dylib"), lib)
    sh(["codesign", "-f", "-s", "-", lib], "codesign merged")

    appc = p(f"app_{tag}.c")
    with open(appc, "w") as f:
        f.write('#include <stdio.h>\nextern const char *get_label_text(void);\n'
                'int main(void){ printf("label=%s\\n", get_label_text()); }\n')
    app = p(f"app_{tag}")
    sh(cc(appc, lib, "-o", app), "линковка exe")
    sh(["codesign", "-f", "-s", "-", app], "codesign exe")

    for env, want in expect_runs:
        e = {**os.environ, **env}
        r = subprocess.run([app], capture_output=True, text=True, timeout=10, env=e)
        out = (r.stdout + r.stderr).strip()
        ok = all(w in out for w in want) and r.returncode == 0
        print(f"   [{tag}] env={env or '-'} -> {out.splitlines()[-1] if out else ''}  [{'ok' if ok else 'BAD'}]")
        if not ok:
            fail(f"[{tag}] env={env}: ждал {want}, got:\n{out} rc={r.returncode}")


def main():
    if not os.path.exists(LOGOS):
        print(f"{YL}SKIP run_logos: нет theos/logos.pl ({LOGOS}){RST}")
        return
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    say("A: ungrouped %hookf detour + %orig + %ctor (без substrate)")
    build_case(
        "ung",
        '''#import <Foundation/Foundation.h>
%hookf(const char *, get_label_text) {
    const char *o = %orig;
    NSLog(@"[coldhook] orig was: %s", o);
    return "Hooked by ColdHook";
}
%ctor { NSLog(@"[coldhook] tweak loaded"); }
''',
        extra_compile=[],
        must_have=["CH_HOOK_SYM", "_chf_get_label_text"],
        expect_runs=[({}, ["label=Hooked by ColdHook"])],
    )

    say("B: %group + %hookf -> gated (включается на %init(Group)); substrate-шим для компиляции")
    build_case(
        "grp",
        '''#import <Foundation/Foundation.h>
%group Feature
%hookf(const char *, get_label_text) { return "Grouped-Hook"; }
%end
%ctor {
    if (getenv("CH_ON")) %init(Feature);
}
''',
        extra_compile=["-I", SUBINC, "-I", THEOSINC, SUBM, "-lc++"],
        must_have=["CH_HOOK_SYM_GATED", "coldhook_disp__chf_get_label_text"],
        expect_runs=[
            ({}, ["label=Fail text"]),               # группа не инициализирована -> оригинал
            ({"CH_ON": "1"}, ["label=Grouped-Hook"]),  # %init(Feature) -> гейт вкл
        ],
    )

    print(f"{GR}OK: Logos %hookf -> статика ColdHook (ungrouped + gated %group){RST}")


if __name__ == "__main__":
    main()
