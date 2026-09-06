#!/usr/bin/env python3
"""FAT-тест ColdHook: толстый (arm64 + x86_64) бинарь.

Мёрджер умеет только arm64/arm64e. Проверяем, что оркестратор патчит arm64-слайс,
оставляет x86_64 как есть и собирает обратно в FAT. arm64-слайс реально запускаем на
Apple Silicon через driver.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD = os.path.join(HERE, "build", "fat")
SPLIT = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def sh(cmd, what):
    if subprocess.run(cmd).returncode != 0: fail(what)


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    arm = os.path.join(BUILD, "slice_arm64.dylib")
    x86 = os.path.join(BUILD, "slice_x86_64.dylib")
    fat = os.path.join(BUILD, "libtarget.dylib")
    merged = os.path.join(BUILD, "libtarget.coldhook.dylib")
    driver = os.path.join(BUILD, "driver")
    tgt = os.path.join(HERE, "target.c")

    say("1/4 собираю слайсы arm64 (+split-info) и x86_64, склеиваю в FAT")
    sh(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", *SPLIT,
        "-install_name", "@rpath/libtarget.dylib", "-o", arm, tgt], "сборка arm64")
    sh(["xcrun", "clang", "-arch", "x86_64", "-dynamiclib",
        "-install_name", "@rpath/libtarget.dylib", "-o", x86, tgt], "сборка x86_64")
    sh(["lipo", "-create", arm, x86, "-output", fat], "lipo create")
    print("   FAT archs:", subprocess.run(["lipo", "-archs", fat],
          capture_output=True, text=True).stdout.strip())

    say("2/4 coldhook merge на FAT")
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, "-m", "coldhook", "merge", "--target", fat,
                        "--src", os.path.join(HERE, "hook.c"),
                        "--src", os.path.join(HERE, "orig_stubs.S"),
                        "--out", merged, "--sign", "-", "--name", "fat"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    sys.stdout.write("\n".join("   " + l for l in r.stdout.splitlines() if "rpath" not in l) + "\n")
    if r.returncode != 0:
        sys.stdout.write(r.stderr)
        fail("coldhook merge упал")

    say("3/4 проверяю, что выход FAT и x86_64 цел")
    out_archs = subprocess.run(["lipo", "-archs", merged],
                               capture_output=True, text=True).stdout.split()
    print("   merged archs:", " ".join(out_archs))
    if "arm64" not in out_archs or "x86_64" not in out_archs:
        fail(f"в выходе нет обоих слайсов: {out_archs}")

    say("4/4 запускаю arm64-слайс (хук должен сработать)")
    sh(["xcrun", "clang", "-arch", "arm64", "-o", driver, os.path.join(HERE, "driver.c")],
       "сборка driver")
    rc = subprocess.run([driver, merged], timeout=10).returncode
    if rc == 0:
        print(f"{GR}OK: FAT пропатчен — arm64-слайс хукнут, x86_64 на месте{RST}")
    else:
        fail(f"прогон вернул {rc}")


if __name__ == "__main__":
    main()
