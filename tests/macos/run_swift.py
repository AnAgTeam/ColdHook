#!/usr/bin/env python3
"""Swift by-name хук + ORIG (вызов оригинала), запускаемый на macOS.

Покрывает то, чего нет у Logos для ЧИСТЫХ Swift-методов (без @objc): цепляемся по
МАНГЛ-ИМЕНИ символа, заменяем функцию Swift-функцией с тем же ABI и зовём ОРИГИНАЛ.

Цель `pick(Int)->String`: первая инструкция — `cbz x0` (PC-relative guard на первом арге).
Это ключевой кейс для ORIG: одноинструкционный трамплин обязан ПЕРЕЭНКОДИТЬ сохранённую
первую инструкцию под адрес слота, иначе её относительный таргет уедет. Проверяем:
  pick(0)  -> ORIG, cbz БЕРЁТСЯ  -> "ZERO"      (переэнкод сработал)
  pick(5)  -> ORIG, cbz не берётся -> "NZ:5"
  pick(99) -> хук фиксит         -> "FIXED-99"

Таргет собран БЕЗ split-info (как реальное приложение) -> append-режим. Хук — Swift
(@_silgen_name даёт фиксированные C-символы при Swift-ABI) + C-glue с CH_HOOK_SYM.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from coldhook.toolchain import ensure_merger

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = ensure_merger()
INCLUDE = os.path.join(ROOT, "coldhook", "include")
BUILD = os.path.join(HERE, "build", "swift")
TGT = ["-O", "-target", "arm64-apple-macos13"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def sh(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: fail(f"{what}\n{r.stderr[-800:]}")
    return r


def main():
    if subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True).returncode != 0:
        fail("нет swiftc")
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    target = os.path.join(BUILD, "target")
    tsrc = os.path.join(BUILD, "target.swift")
    say("1/4 собираю Swift-таргет (без split-info, крашащий guard)")
    with open(tsrc, "w") as f:
        f.write('''import Foundation
@inline(never)
func pick(_ x: Int) -> String {
    if x == 0 { return "ZERO" }      // cbz/cbnz в первой инструкции
    return "NZ:\\(x)"
}
let e = CommandLine.arguments.count > 1 ? (Int(CommandLine.arguments[1]) ?? 0) : 0
FileHandle.standardError.write("pick=\\(pick(e))\\n".data(using: .utf8)!)
''')
    sh(["xcrun", "swiftc", *TGT, "-Xlinker", "-headerpad", "-Xlinker", "0x4000",
        tsrc, "-o", target], "сборка таргета")
    sh(["codesign", "-f", "-s", "-", target], "codesign таргета")
    if subprocess.run(["otool", "-l", target], capture_output=True, text=True).stdout.count("SPLIT_INFO"):
        fail("таргет неожиданно со split-info")

    # мангл-имя pick из nm (без ведущего _)
    nm = subprocess.run(["nm", target], capture_output=True, text=True).stdout
    m = [ln.split()[-1] for ln in nm.splitlines() if "4pick" in ln and re.search(r" t ", ln)]
    if not m:
        fail("не нашёл символ pick в nm")
    mangled = m[0][1:]  # strip leading _
    say(f"2/4 мангл цели: {mangled}")

    hsrc = os.path.join(BUILD, "hook.swift")
    csrc = os.path.join(BUILD, "glue.c")
    with open(hsrc, "w") as f:
        f.write('''@_silgen_name("coldhook_orig_ch_pick_impl")
func ch_orig_pick(_ x: Int) -> String
@_silgen_name("ch_pick_impl")
public func ch_pick(_ x: Int) -> String {
    if x == 99 { return "FIXED-99" }   // чиним
    return ch_orig_pick(x)              // остальное -> ОРИГИНАЛ (тут проверяется ORIG)
}
''')
    with open(csrc, "w") as f:
        f.write('#include <coldhook.h>\n'
                'extern void ch_pick_impl(void);\n'
                f'CH_HOOK_SYM("{mangled}", ch_pick_impl);\n')

    say("3/4 собираю Swift-хук (by-name + ORIG) и мёрджу (append)")
    glue = os.path.join(BUILD, "glue.o")
    sh(["xcrun", "clang", "-arch", "arm64", "-I", INCLUDE, "-c", csrc, "-o", glue], "сборка glue")
    hook = os.path.join(BUILD, "hook.dylib")
    sh(["xcrun", "swiftc", *TGT, "-emit-library", hsrc, glue, "-o", hook,
        "-Xlinker", "-install_name", "-Xlinker", "@rpath/hook.dylib",
        "-Xlinker", "-fixup_chains", "-Xlinker", "-add_split_seg_info"], "сборка хука")
    merged = os.path.join(BUILD, "merged")
    if subprocess.run([MERGER, target, hook, merged, "--allow-new-dylibs"],
                      capture_output=True).returncode != 0:
        fail("merge упал")
    sh(["codesign", "-f", "-s", "-", merged], "codesign merged")
    os.chmod(merged, 0o755)

    say("4/4 запуск: ORIG (cbz берётся / не берётся) + фикс")
    want = {"0": "ZERO", "5": "NZ:5", "99": "FIXED-99"}
    for arg, exp in want.items():
        r = subprocess.run([merged, arg], capture_output=True, text=True, timeout=10)
        out = (r.stdout + r.stderr).strip()
        mark = "ok" if (f"pick={exp}" in out and r.returncode == 0) else "BAD"
        print(f"   pick({arg}) -> {out}  [{mark}]")
        if mark == "BAD":
            fail(f"pick({arg}): ждал {exp}, got '{out}' rc={r.returncode}")
    print(f"{GR}OK: Swift by-name хук + ORIG (с переэнкодом PC-relative) работает{RST}")


if __name__ == "__main__":
    main()
