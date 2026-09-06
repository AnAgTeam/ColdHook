#!/usr/bin/env python3
"""Fail-loud: %init(funcname = expr) для %hookf-цели несовместим со статикой -> внятная ошибка.

%init(name = pointer_expr) в Logos = рантайм-адрес под MSHookFunction (вычисляется в конструкторе).
ColdHook ставит хук на этапе merge -> такое выражение оценить негде. Пре-пасс это детектит и падает
с понятным сообщением, а не молча генерит no-op хук.

Детект точечный: ругаемся ТОЛЬКО когда LHS '=' — имя %hookf-функции. %init(Class = objc_getClass(...))
для ObjC-класса легитимен (рантайм) -> НЕ трогаем (проверяем отсутствие ложного срабатывания).

theos не нужен: ошибка возникает в пре-пассе ДО вызова logos.pl.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PREPASS = os.path.join(ROOT, "coldhook", "logos_prepass.py")
BUILD = os.path.join(HERE, "build", "initaddr")
CY, RD, GR, RST = "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[0m"


def say(m): print(f"{CY}== {m}{RST}")
def fail(m): print(f"{RD}FAIL: {m}{RST}"); sys.exit(1)


def run_prepass(src_text):
    os.makedirs(BUILD, exist_ok=True)
    x = os.path.join(BUILD, "T.x")
    with open(x, "w") as f:
        f.write(src_text)
    return subprocess.run(["python3", PREPASS, "--strip-only", x], capture_output=True, text=True)


def main():
    say("1/2 %init(foo = runtime-expr), foo — это %hookf -> ДОЛЖНО упасть с сообщением")
    r = run_prepass(
        "#import <Foundation/Foundation.h>\n"
        "%hookf(int, foo, int x) { return %orig(x); }\n"
        '%ctor { %init(foo = MSFindSymbol(NULL, "_foo")); }\n'
    )
    if r.returncode == 0:
        fail("пре-пасс НЕ упал на %init(foo = ...)")
    if "%init(foo" not in r.stderr or "MSHookFunction" not in r.stderr:
        fail(f"нет внятного сообщения в stderr:\n{r.stderr}")
    print(f"{GR}   OK: упал, rc={r.returncode}, сообщение про %init(foo = ...){RST}")
    print("   " + r.stderr.strip().splitlines()[-1][:120])

    say("2/2 %init(Greeter = objc_getClass(...)) — ObjC-класс, НЕ %hookf -> ложного срабатывания нет")
    r = run_prepass(
        "#import <Foundation/Foundation.h>\n"
        "%hookf(int, bar) { return %orig; }\n"        # есть %hookf 'bar' (множество имён непусто)
        "%hook Greeter\n- (id)init { return %orig; }\n%end\n"
        '%ctor { %init(Greeter = objc_getClass("Greeter")); }\n'
    )
    if r.returncode != 0:
        fail(f"ложное срабатывание на ObjC-классе:\n{r.stderr}")
    if "%init(Greeter" not in r.stdout:
        fail("%init(Greeter = ...) должен пройти НАСКВОЗЬ к logos (его там нет в выводе)")
    print(f"{GR}   OK: rc=0, %init(Greeter = ...) прошёл к logos нетронутым{RST}")

    print(f"{GR}OK: fail-loud на %init(hookf = рантайм-addr); ObjC-класс не задет{RST}")


if __name__ == "__main__":
    main()
