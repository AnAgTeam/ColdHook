#!/usr/bin/env python3
"""Локальный macOS-харнесс ColdHook (M1, Replace).

Пайплайн: собрать target+hook dylib -> merge (MachOMerger) -> codesign ->
прогнать драйвер до и после хука. Доказывает merge-путь на символах без устройства.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from coldhook.toolchain import ensure_merger

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = ensure_merger()
BUILD = os.path.join(HERE, "build", "default")
ARCH = "arm64"
# Требования MachOMerger к сливаемым бинарям:
#  -fixup_chains       — мёрджер умеет только LC_DYLD_CHAINED_FIXUPS;
#  -add_split_seg_info — релокация данных идёт через LC_SEGMENT_SPLIT_INFO
#                        (эмитится только если в __DATA есть указатель под rebase).
# Старый флаг -no_auth_data из README выкинут: ld-prime его не знает,
# а для чистого arm64 auth-указателей нет в принципе.
LDFLAGS = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]

C_CYAN, C_RED, C_GREEN, C_RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(msg):
    print(f"{C_CYAN}== {msg}{C_RST}")


def fail(msg):
    print(f"{C_RED}FAIL: {msg}{C_RST}")
    sys.exit(1)


def run(cmd, timeout=None, **kw):
    """Запуск с выводом команды; возвращает CompletedProcess (без проверки кода).
    При таймауте возвращает объект с returncode=124 (как timeout(1)) — чтобы кривой
    merged-бинарь, заставивший dyld крутить цепочку фиксапов, не подвесил сессию."""
    print("  $ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        print(f"  !! таймаут {timeout}s — процесс убит")
        return subprocess.CompletedProcess(cmd, 124)


def check(cmd, what):
    if run(cmd).returncode != 0:
        fail(what)


def cc(*args):
    return ["xcrun", "clang", "-arch", ARCH, *args]


def main():
    if not os.access(MERGER, os.X_OK):
        fail(f"MachOMerger не собран: {MERGER}")

    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, f))

    target = os.path.join(BUILD, "libtarget.dylib")
    hook = os.path.join(BUILD, "libhook.dylib")
    merged = os.path.join(BUILD, "libtarget_hooked.dylib")
    driver = os.path.join(BUILD, "driver")

    say("1/5 компилирую libtarget.dylib (жертва)")
    check(cc("-dynamiclib", *LDFLAGS, "-install_name", "@rpath/libtarget.dylib",
             "-o", target, os.path.join(HERE, "target.c")), "сборка target")
    check(["codesign", "-f", "-s", "-", target], "codesign target")

    say("2/5 компилирую libhook.dylib (патч с магик-символами + ORIG-стабы)")
    check(cc("-dynamiclib", *LDFLAGS, "-install_name", "@rpath/libhook.dylib",
             "-o", hook, os.path.join(HERE, "hook.c"), os.path.join(HERE, "orig_stubs.S")),
          "сборка hook")

    say("3/5 merge: target + hook -> libtarget_hooked.dylib")
    check([MERGER, target, hook, merged], "merge упал")
    check(["codesign", "-f", "-s", "-", merged], "codesign merged")

    say("4/5 компилирую driver")
    check(cc("-o", driver, os.path.join(HERE, "driver.c")), "сборка driver")

    say("5/5 прогон")
    print("--- БЕЗ хука (ожидаем abort) ---")
    rc0 = run([driver, target], timeout=10).returncode
    print(f"  exit={rc0}")
    print("--- С хуком (ожидаем валидный домен) ---")
    rc1 = run([driver, merged], timeout=10).returncode
    print(f"  exit={rc1}")

    if rc1 == 0:
        print(f"{C_GREEN}OK: хукнутый dylib вернул значение без abort{C_RST}")
    else:
        fail(f"хукнутый прогон завершился ненулём ({rc1})")


if __name__ == "__main__":
    main()
