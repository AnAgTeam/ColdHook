#ifndef COLDHOOK_H
#define COLDHOOK_H

// ColdHook — by-offset хуки прямо в коде (embedded-режим).
//
//   #include <coldhook.h>
//   COLDHOOK_ORIG(fix_domain, const char *, int);   // объявить оригинал (для detour)
//   const char *fix_domain(int env) {
//       if (env == 99) return "https://fallback";    // чиним провальный путь
//       return ORIG(fix_domain)(env);                 // остальное -> в оригинал
//   }
//   HOOK_ADDR(0xb99a8, fix_domain);                   // пропатчить адрес 0xb99a8 на fix_domain
//
// offset — ОРИГИНАЛЬНЫЙ vmaddr цели (как в IDA на исходном бинаре). Строку-модуль
// здесь НЕ указываем: в embedded одна либа собирается под один бинарь (таргет задаёт
// конфиг). Модуль появится в shared-режиме (одна либа на много бинарей).

// --- вызов оригинала из detour-хука -------------------------------------------------
#define ORIG(name) coldhook_orig_##name
#define COLDHOOK_ORIG(name, ret, ...) extern ret coldhook_orig_##name(__VA_ARGS__)

// --- регистрация хука по адресу ------------------------------------------------------
// Раскрывается в file-scope inline-asm, который генерит магик-символы для мёрджера:
//   _MACHOMERGER_HOOK_COLDHOOK_ADDR_<off>      : ветка на функцию-хук;
//   _MACHOMERGER_ORIG_COLDHOOK_ADDR_<off>      : слот сохранённой 1-й инструкции цели;
//   _MACHOMERGER_HOOKTRAMPOLINE_COLDHOOK_ADDR_<off>: слот `B цель+4` (СМЕЖНО с ORIG);
//   _coldhook_orig_<fn>                        : alias, его зовёт ORIG(fn).
// .no_dead_strip держит символы при -dead_strip; смежность ORIG/TRAMPOLINE сохраняется,
// т.к. они в одном asm-блоке и линкер не переставляет атомы без причины.
// data-anchor (указатель в __DATA) гарантирует LC_SEGMENT_SPLIT_INFO (требование мёрджера).
#define COLDHOOK__STUB(off, fn) \
  __asm__( \
    ".text\n.p2align 2\n" \
    ".globl _MACHOMERGER_HOOK_COLDHOOK_ADDR_" #off "\n" \
    ".no_dead_strip _MACHOMERGER_HOOK_COLDHOOK_ADDR_" #off "\n" \
    "_MACHOMERGER_HOOK_COLDHOOK_ADDR_" #off ":\n    b _" #fn "\n" \
    ".globl _MACHOMERGER_ORIG_COLDHOOK_ADDR_" #off "\n" \
    ".no_dead_strip _MACHOMERGER_ORIG_COLDHOOK_ADDR_" #off "\n" \
    "_MACHOMERGER_ORIG_COLDHOOK_ADDR_" #off ":\n    brk #0\n" \
    ".globl _MACHOMERGER_HOOKTRAMPOLINE_COLDHOOK_ADDR_" #off "\n" \
    ".no_dead_strip _MACHOMERGER_HOOKTRAMPOLINE_COLDHOOK_ADDR_" #off "\n" \
    "_MACHOMERGER_HOOKTRAMPOLINE_COLDHOOK_ADDR_" #off ":\n    brk #0\n" \
    ".globl _coldhook_orig_" #fn "\n" \
    "_coldhook_orig_" #fn ":\n    b _MACHOMERGER_ORIG_COLDHOOK_ADDR_" #off "\n" \
    ".section __DATA_CONST,__const\n.p2align 3\n" \
    "_coldhook_anchor_" #off ":\n    .quad _MACHOMERGER_HOOK_COLDHOOK_ADDR_" #off "\n" \
  )

// Публичный макрос: HOOK_ADDR(offset, функция). Всегда detour-способен (ORIG доступен);
// для полного replace просто не зови ORIG.
#define HOOK_ADDR(off, fn) COLDHOOK__STUB(off, fn)

#endif
