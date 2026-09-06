#!/usr/bin/env python3
"""Тест merge в ГЛАВНЫЙ БИНАРЬ (MH_EXECUTE) через оркестратор `coldhook merge`.

Исполняемый отличается от dylib: __PAGEZERO (vmaddr 0, 4ГБ), база 0x100000000, LC_MAIN.
Проверяем, что хук вливается, бинарь сохраняет исполняемость и реально запускается.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD = os.path.join(HERE, "build", "exe")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)


def run_exe(path):
    p = subprocess.run([path], capture_output=True, text=True, timeout=10)
    sys.stdout.write(p.stdout)
    if p.stderr.strip():
        sys.stdout.write(p.stderr)
    return p.returncode


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    prog = os.path.join(BUILD, "prog")
    hooked = os.path.join(BUILD, "prog.hooked")

    say("1/4 собираю главный бинарь prog (MH_EXECUTE)")
    if subprocess.run(["xcrun", "clang", "-arch", "arm64", *SPLIT, "-o", prog,
                       os.path.join(HERE, "prog.c")]).returncode != 0:
        fail("сборка prog")
    subprocess.run(["codesign", "-f", "-s", "-", prog])

    say("2/4 baseline (ожидаем trap на domain_for(99))")
    rc = run_exe(prog)
    print(f"   exit={rc}  {'(trap, как и ждали)' if rc != 0 else '(?!)'}")

    say("3/4 coldhook merge хука в исполняемый (--sign -)")
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, "-m", "coldhook", "merge", "--target", prog,
                        "--src", os.path.join(HERE, "hook.c"),
                        "--src", os.path.join(HERE, "orig_stubs.S"),
                        "--out", hooked, "--sign", "-", "--name", "exe"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    sys.stdout.write("\n".join("   " + l for l in r.stdout.splitlines() if "rpath" not in l) + "\n")
    if r.returncode != 0:
        sys.stdout.write(r.stderr)
        fail("coldhook merge упал")

    say("4/4 запуск пропатченного исполняемого")
    rc = run_exe(hooked)
    print(f"   exit={rc}")
    # domain_for(0) через ORIG -> prod; domain_for(99) -> fallback; без падения
    if rc == 0:
        print(f"{GR}OK: главный бинарь (MH_EXECUTE) хукнут, запускается, ORIG+детур работают{RST}")
    else:
        fail(f"пропатченный exe упал (exit={rc})")


if __name__ == "__main__":
    main()
