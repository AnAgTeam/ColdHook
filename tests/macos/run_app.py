#!/usr/bin/env python3
"""macOS .app тест-полигон ColdHook (самотестируемый через консоль).

Собирает TestApp.app со встроенным libcore.dylib (таргет), прогоняет baseline
(domain_for(99) -> trap), патчит бандл через `coldhook ipa` (БЕЗ подписи), затем
adhoc-подписывает пропатченный бандл ТОЛЬКО для запуска и проверяет, что хук сработал.

Структура идентична iOS-IPA (.app + бинарь по относительному пути), только тут я могу
реально запустить результат.
"""
import os
import plistlib
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD = os.path.join(HERE, "build", "app")
LDFLAGS = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, YL, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def check(cmd, what, **k):
    if subprocess.run(cmd, **k).returncode != 0: fail(what)


def make_app(app: str):
    """Собрать TestApp.app: Contents/{MacOS/TestApp, Frameworks/libcore.dylib, Info.plist}."""
    macos = os.path.join(app, "Contents", "MacOS")
    fw = os.path.join(app, "Contents", "Frameworks")
    os.makedirs(macos, exist_ok=True)
    os.makedirs(fw, exist_ok=True)

    core = os.path.join(fw, "libcore.dylib")
    check(cc("-dynamiclib", *LDFLAGS, "-install_name", "@rpath/libcore.dylib",
             "-o", core, os.path.join(HERE, "target.c")), "сборка libcore")

    exe = os.path.join(macos, "TestApp")
    check(cc("-o", exe, os.path.join(HERE, "app_main.c"),
             "-L", fw, "-lcore", "-rpath", "@executable_path/../Frameworks"),
          "сборка TestApp")

    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({
            "CFBundleExecutable": "TestApp",
            "CFBundleIdentifier": "com.coldhook.testapp",
            "CFBundleName": "TestApp",
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1.0",
        }, f)
    return exe, core


def sign_app(app: str):
    """adhoc-подпись фреймворка и экзешника (вложенное -> потом сам бандл)."""
    for p in [os.path.join(app, "Contents", "Frameworks", "libcore.dylib"),
              os.path.join(app, "Contents", "MacOS", "TestApp")]:
        check(["codesign", "-f", "-s", "-", p], f"codesign {os.path.basename(p)}")


def run_exe(app: str):
    exe = os.path.join(app, "Contents", "MacOS", "TestApp")
    p = subprocess.run([exe], capture_output=True, text=True, timeout=10)
    sys.stdout.write(p.stdout)
    if p.stderr.strip():
        sys.stdout.write(p.stderr)
    return p.returncode


def main():
    os.makedirs(BUILD, exist_ok=True)
    app = os.path.join(BUILD, "TestApp.app")
    patched = os.path.join(BUILD, "TestApp_patched.app")
    cfg = os.path.join(BUILD, "coldhook-app.toml")
    for p in (app, patched):
        if os.path.exists(p):
            subprocess.run(["rm", "-rf", p])

    say("1/5 собираю TestApp.app")
    make_app(app)
    sign_app(app)

    say("2/5 baseline (ожидаем trap на domain_for(99))")
    rc = run_exe(app)
    print(f"   exit={rc}  {'(trap, как и ждали)' if rc != 0 else YL + '(не упал?!)' + RST}")

    say("3/5 пишу конфиг и патчу бандл через `coldhook ipa` (без подписи)")
    with open(cfg, "w") as f:
        f.write(
            "[[target]]\n"
            'name = "core"\n'
            'binary = "Contents/Frameworks/libcore.dylib"\n'
            f'sources = ["{os.path.join(HERE, "hook.c")}", "{os.path.join(HERE, "orig_stubs.S")}"]\n'
        )
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, "-m", "coldhook", "ipa", app, "-c", cfg,
                        "-o", patched], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    sys.stdout.write("\n".join("   " + l for l in r.stdout.splitlines() if "rpath" not in l))
    print()
    if r.returncode != 0:
        sys.stdout.write(r.stderr)
        fail("coldhook ipa упал")

    say("4/5 adhoc-подпись пропатченного бандла (только чтобы запустить)")
    sign_app(patched)

    say("5/5 запуск пропатченного TestApp")
    rc = run_exe(patched)
    print(f"   exit={rc}")
    if rc == 0:
        print(f"{GR}OK: пропатченный .app отработал без trap — хук в бандле сработал{RST}")
    else:
        fail(f"пропатченный апп упал (exit={rc})")


if __name__ == "__main__":
    main()
