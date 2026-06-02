#!/usr/bin/env python3
"""ColdHook-пре-пасс для Logos: переводит %hookf (хук C-функции) в СТАТИЧЕСКИЙ glue ColdHook,
а остальное (ObjC %hook/%orig/%new/%init, %ctor) отдаёт СТОКОВОМУ logos.pl.

Зачем: Logos разворачивает %hookf в рантайм MSHookFunction = инлайн-патч кодовых страниц = W^X,
которого в сайдлоаде нет. Мы вместо этого эмитим CH_HOOK_SYM(_GATED) — первую инструкцию цели
патчит мёрджер на этапе merge, без кодогена. ObjC-свизл остаётся рантаймом Logos (там W^X не нужен).

Как: находим %hookf-блоки и заменяем ПРЯМО В ТЕКСТЕ .x на сгенерированный C (replacement-функция +
CH_HOOK_SYM glue). Так logos.pl получает валидный .x уже без %hookf — он не кладёт MSHookFunction,
а наш C проносит насквозь (это не %-директива). %ctor чинится сам.

Поддержано:
  %hookf(ret, name)                      — by-name, без аргументов
  %hookf(ret, name, T a, U b, ...)       — by-name, с аргументами
  %hookf(ret, 0xADDR, ...)               — by-address (литерал) -> CH_HOOK_ADDR
  %orig / %orig(args)                     — вызов оригинала
  %group NAME ... %hookf ... %end         — gated-хук (CH_HOOK_SYM_GATED), включается на %init(NAME)

Использование как обёртка (drop-in замена logos.pl для theos):
  coldhook-logos <input.x> [extra logos args...]   -> processed source в stdout

Резолв «найти символ в рантайме» (MSFindSymbol-форма) статикой невозможен — не поддерживаем.
"""
import os
import re
import subprocess
import sys
import tempfile

LOGOS = os.environ.get("COLDHOOK_LOGOS") or os.path.join(
    os.environ.get("THEOS", os.path.expanduser("~/theos")), "bin", "logos.pl")


def _scan_block(text, i, opener, closer):
    """С позиции i (на opener) вернуть индекс ПОСЛЕ парного closer, уважая строки/символы."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            q = c; i += 1
            while i < n and text[i] != q:
                if text[i] == '\\': i += 1
                i += 1
            i += 1; continue
        if c == '/' and i + 1 < n and text[i+1] == '/':
            while i < n and text[i] != '\n': i += 1
            continue
        if c == '/' and i + 1 < n and text[i+1] == '*':
            i += 2
            while i + 1 < n and not (text[i] == '*' and text[i+1] == '/'): i += 1
            i += 2; continue
        if c == opener: depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0: return i + 1
        i += 1
    raise ValueError(f"не нашёл парный '{closer}'")


def _split_top_commas(s):
    """Разбить по запятым верхнего уровня (вне скобок)."""
    out, depth, cur = [], 0, ""
    for c in s:
        if c in "([{": depth += 1
        elif c in ")]}": depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += c
    if cur.strip(): out.append(cur.strip())
    return out


def _param_name(decl):
    """Имя параметра из C-декларации ('const char *path' -> 'path')."""
    m = re.findall(r"[A-Za-z_]\w*", decl)
    return m[-1] if m else ""


def _translate_orig(body, orig_call, argnames):
    """%orig(args) -> orig_call(args);  голый %orig -> orig_call(argnames)."""
    # %orig( ... )
    out, i, n = "", 0, len(body)
    while i < n:
        if body.startswith("%orig", i):
            j = i + 5
            while j < n and body[j] in " \t": j += 1
            if j < n and body[j] == "(":
                out += orig_call
                i = j
            else:
                out += f"{orig_call}({', '.join(argnames)})"
                i = j
            continue
        out += body[i]; i += 1
    return out


def _emit_hookf(ret, target, argdecls, body, gated, group):
    """Сгенерировать C-замену + ColdHook-glue для одного %hookf."""
    argnames = [_param_name(a) for a in argdecls]
    argtypes = [a.rsplit(argnames[k], 1)[0].strip() or a for k, a in enumerate(argdecls)] if argdecls else []
    is_addr = re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", target.strip())
    fid = "_chf_" + (re.sub(r"\W", "_", target) if not is_addr else f"addr_{int(target,0):x}")
    orig_call = f"coldhook_orig_{fid}"
    sig = ", ".join(argdecls) if argdecls else "void"
    tbody = _translate_orig(body, orig_call, argnames)

    out = []
    # .mm (ObjC++) даёт C++-линковку -> мангл; asm-glue зовёт C-имена. Оборачиваем декларации и
    # тело замены в extern "C", чтобы символы _chf_/coldhook_orig_/coldhook_disp_ были C-линковки.
    out.append('#ifdef __cplusplus\nextern "C" {\n#endif')
    # объявления ДО тела (тело зовёт coldhook_orig_<fid>)
    out.append(f"CH_DECLARE_ORIG({fid}, {ret}{(', ' + ', '.join(argtypes)) if argtypes else ''});")
    if gated:
        out.append(f"CH_DECLARE_GATE({fid});")
    out.append(f"{ret} {fid}({sig}) {tbody}")
    out.append('#ifdef __cplusplus\n}\n#endif')
    if is_addr:
        macro = "CH_HOOK_ADDR_GATED" if gated else "CH_HOOK_ADDR"
        out.append(f"{macro}({target}, {fid});")
    else:
        macro = "CH_HOOK_SYM_GATED" if gated else "CH_HOOK_SYM"
        out.append(f'{macro}("{target}", {fid});')
    return fid, "\n".join(out)


def prepass(text):
    """Вернуть (новый текст .x, список (group, fid) для gated-хуков)."""
    # карта позиций -> имя группы (для определения gated)
    gated_ranges = []
    for m in re.finditer(r"%group\s+(\w+)", text):
        start = m.end()
        end_m = re.search(r"%end", text[start:])
        end = start + end_m.start() if end_m else len(text)
        gated_ranges.append((start, end, m.group(1)))

    def group_at(pos):
        for s, e, g in gated_ranges:
            if s <= pos < e: return g
        return None

    gated_hooks = []
    result, i, n = [], 0, len(text)
    used_include = False
    while i < n:
        if text.startswith("%hookf", i):
            # заголовок (...)
            p = text.index("(", i)
            pend = _scan_block(text, p, "(", ")")
            header = text[p+1:pend-1]
            # тело { ... }
            b = pend
            while b < n and text[b] in " \t\r\n": b += 1
            if b >= n or text[b] != "{":
                raise ValueError("%hookf без тела { }")
            bend = _scan_block(text, b, "{", "}")
            body = text[b:bend]

            parts = _split_top_commas(header)
            ret, target, argdecls = parts[0], parts[1], parts[2:]
            grp = group_at(i)
            fid, c = _emit_hookf(ret, target, argdecls, body, gated=bool(grp), group=grp)
            if grp:
                gated_hooks.append((grp, fid))
            # вставляем include один раз
            if not used_include:
                result.append("#include <coldhook.h>\n"); used_include = True
            result.append("\n" + c + "\n")
            i = bend
            continue
        result.append(text[i]); i += 1

    out = "".join(result)
    # gated: на %init(Group) включаем гейты этой группы. %init(Group) logos разворачивает в
    # {...}-БЛОК (statement), поэтому оборачиваем в do{ enable; %init(Group); }while(0) — корректно
    # и внутри `if(...) %init(Group);`. %init(Group) внутри остаётся — его развернёт сток-logos.
    from collections import defaultdict
    by_group = defaultdict(list)
    for grp, fid in gated_hooks:
        by_group[grp].append(fid)
    for grp, fids in by_group.items():
        enables = " ".join(f"coldhook_disp_{f} = (void*)&{f};" for f in fids)
        out = re.sub(rf"%init\(\s*{re.escape(grp)}\s*\)",
                     lambda mm, e=enables, g=grp: f"do {{ {e} %init({g}); }} while (0)", out)
    return out


def main(argv):
    if not argv:
        print("usage: coldhook-logos <input.x> [logos args...]", file=sys.stderr); return 2
    src = argv[0]
    with open(src) as f:
        text = f.read()
    processed = prepass(text)
    # пишем во временный .x рядом (для корректных #line/относительных include logos)
    d = os.path.dirname(os.path.abspath(src))
    fd, tmp = tempfile.mkstemp(suffix=".x", dir=d, prefix=".coldhook_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(processed)
        r = subprocess.run(["perl", LOGOS, tmp, *argv[1:]], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr.replace(os.path.basename(tmp), os.path.basename(src)))
        return r.returncode
    finally:
        os.unlink(tmp)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
