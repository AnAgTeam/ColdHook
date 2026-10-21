#!/usr/bin/env python3
"""By-offset харнесс ColdHook: хук цели по СЫРОМУ оффсету, без символа.

Доказывает адресный путь мёрджера (_COLDHOOK_ADDR_<hex>): находим vmaddr domain_for
через nm (имитация адреса из IDA), генерим хук с магик-символами по этому адресу,
мёрджим и проверяем, что детур+ORIG сработали — притом цель резолвилась ПО АДРЕСУ,
а не по имени (символ _COLDHOOK_ADDR_<hex> в symtab таргета отсутствует).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from coldhook.toolchain import ensure_merger

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = ensure_merger()
BUILD = os.path.join(HERE, "build", "offset")
LDFLAGS = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)
def cc(*a): return ["xcrun", "clang", "-arch", "arm64", *a]
def run(cmd, **k): return subprocess.run(cmd, **k)
def check(cmd, what):
    if run(cmd).returncode != 0: fail(what)


def symbol_vaddr(dylib, name):
    out = subprocess.run(["nm", dylib], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.match(r"([0-9a-fA-F]+)\s+\S+\s+" + re.escape(name) + r"$", line)
        if m:
            return int(m.group(1), 16)
    fail(f"символ {name} не найден в {dylib}")


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
    hook_c = os.path.join(BUILD, "hook_off.c")
    stub_s = os.path.join(BUILD, "orig_off.S")

    say("1/6 собираю target")
    check(cc("-dynamiclib", *LDFLAGS, "-install_name", "@rpath/libtarget.dylib",
             "-o", target, os.path.join(HERE, "target.c")), "сборка target")
    check(["codesign", "-f", "-s", "-", target], "codesign target")

    say("2/6 нахожу оффсет domain_for (как из IDA)")
    off = symbol_vaddr(target, "_domain_for")
    tag = f"COLDHOOK_ADDR_0x{off:x}"   # _domain_for -> хукаем по адресу
    print(f"   domain_for @ 0x{off:x}  ->  магик-символ {tag}")

    say("3/6 генерю хук по адресу")
    # Хук-функция и ORIG-трамплин адресуют цель ТОЛЬКО по оффсету (символа нет в имени).
    with open(hook_c, "w") as f:
        f.write(f"""#include <unistd.h>
extern const char *coldhook_orig_fix_domain(int env);
const char *fix_domain(int env);
void *const g_hook_self = (void *)fix_domain;
__attribute__((visibility("default")))
const char *fix_domain(int env) {{
    if (env == 99) return "https://hooked.by.offset";   // чиним провальный путь
    return coldhook_orig_fix_domain(env);                // известное -> в оригинал
}}
__asm__(".text\\n.p2align 2\\n"
        ".globl _COLDHOOK_ADDR_{off:x}\\n_COLDHOOK_ADDR_{off:x}:\\n    b _fix_domain\\n"
        ".globl _COLDHOOK_ORIG_ADDR_{off:x}\\n_COLDHOOK_ORIG_ADDR_{off:x}:\\n    brk #0\\n"
        ".globl _COLDHOOK_TRAMPOLINE_ADDR_{off:x}\\n_COLDHOOK_TRAMPOLINE_ADDR_{off:x}:\\n    brk #0\\n"
        ".globl _coldhook_orig_fix_domain\\n_coldhook_orig_fix_domain:\\n    b _COLDHOOK_ORIG_ADDR_{off:x}\\n");
""")
    with open(stub_s, "w") as f:
        f.write(f""".text
.p2align 2
.globl _MACHOMERGER_ORIG_{tag}
_MACHOMERGER_ORIG_{tag}:
    brk #0
.globl _MACHOMERGER_HOOKTRAMPOLINE_{tag}
_MACHOMERGER_HOOKTRAMPOLINE_{tag}:
    brk #0
""")

    say("4/6 собираю хук")
    check(cc("-dynamiclib", *LDFLAGS, "-install_name", "@rpath/libhook.dylib",
             "-o", hook, hook_c, stub_s), "сборка hook")

    say("5/6 merge по адресу + codesign")
    check([MERGER, target, hook, merged], "merge")
    check(["codesign", "-f", "-s", "-", merged], "codesign merged")

    say("6/6 прогон")
    check(cc("-o", driver, os.path.join(HERE, "driver.c")), "сборка driver")
    rc = run([driver, merged], timeout=10).returncode
    if rc == 0:
        print(f"{GR}OK: хук по ОФФСЕТУ сработал (детур+ORIG), цель резолвилась по адресу{RST}")
    else:
        fail(f"прогон вернул {rc}")


if __name__ == "__main__":
    main()
