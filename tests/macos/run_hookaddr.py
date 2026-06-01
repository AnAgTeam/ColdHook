#!/usr/bin/env python3
"""Тест by-offset через макрос HOOK_ADDR (coldhook.h) + оркестратор `coldhook merge`.

Юзер пишет ОБЫЧНУЮ функцию + HOOK_ADDR(offset, fn); inline-asm glue из coldhook.h
генерит магик-символы. Здесь оффсет берём из nm (имитация IDA), хук компилит и мёрджит
сам `coldhook merge`. Проверяем детур+ORIG по адресу.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
BUILD = os.path.join(HERE, "build_hookaddr")
LDFLAGS = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        p = os.path.join(BUILD, f)
        os.remove(p) if os.path.isfile(p) else subprocess.run(["rm", "-rf", p])

    target = os.path.join(BUILD, "libtarget.dylib")
    merged = os.path.join(BUILD, "libtarget.coldhook.dylib")
    hook_c = os.path.join(BUILD, "hook_macro.c")
    driver = os.path.join(BUILD, "driver")

    say("1/4 собираю target + нахожу оффсет domain_for")
    if subprocess.run(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", *LDFLAGS,
                       "-install_name", "@rpath/libtarget.dylib", "-o", target,
                       os.path.join(HERE, "target.c")]).returncode != 0:
        fail("сборка target")
    subprocess.run(["codesign", "-f", "-s", "-", target])
    nm = subprocess.run(["nm", target], capture_output=True, text=True).stdout
    off = next((int(m.group(1), 16) for line in nm.splitlines()
                if (m := re.match(r"([0-9a-fA-F]+)\s+\S+\s+_domain_for$", line))), None)
    if off is None:
        fail("не нашёл domain_for")
    print(f"   domain_for @ 0x{off:x}")

    say("2/4 пишу хук с HOOK_ADDR (как юзер)")
    with open(hook_c, "w") as f:
        f.write(f"""#include <coldhook.h>
#include <unistd.h>
CH_DECLARE_ORIG(fix_domain, const char *, int);

// hook_ppid дёргается из driver через dlsym -> ему нужен экспорт (CH_EXPORT).
CH_EXPORT int hook_ppid(void) {{ return (int)getppid(); }}   // внешний импорт B (регрессия)

// fix_domain — БЕЗ всякого атрибута видимости: для CH_HOOK_ADDR достаточно не-static.
const char *fix_domain(int env) {{
    if (env == 99) return "https://hooked.via.macro";  // чиним провал
    return CH_ORIG(fix_domain)(env);                    // известное -> в оригинал
}}

CH_HOOK_ADDR(0x{off:x}, fix_domain);
""")

    say("3/4 coldhook merge (компилит хук с -I coldhook.h, мёрджит)")
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, "-m", "coldhook", "merge",
                        "--target", target, "--src", hook_c,
                        "--out", merged, "--sign", "-", "--name", "macro"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    sys.stdout.write("\n".join("   " + l for l in r.stdout.splitlines() if "rpath" not in l) + "\n")
    if r.returncode != 0:
        sys.stdout.write(r.stderr)
        fail("coldhook merge упал")

    say("4/4 прогон")
    if subprocess.run(["xcrun", "clang", "-arch", "arm64", "-o", driver,
                       os.path.join(HERE, "driver.c")]).returncode != 0:
        fail("сборка driver")
    rc = subprocess.run([driver, merged], timeout=10).returncode
    if rc == 0:
        print(f"{GR}OK: HOOK_ADDR(оффсет) сработал — детур+ORIG по адресу через макрос{RST}")
    else:
        fail(f"прогон вернул {rc}")


if __name__ == "__main__":
    main()
