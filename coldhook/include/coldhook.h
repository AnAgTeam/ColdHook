#ifndef COLDHOOK_H
#define COLDHOOK_H

// ColdHook — by-offset хуки прямо в коде (embedded-режим).
//
//   #include <coldhook.h>
//   CH_DECLARE_ORIG(fix_domain, const char *, int);  // объявить оригинал (для detour)
//   const char *fix_domain(int env) {
//       if (env == 99) return "https://fallback";     // чиним провальный путь
//       return CH_ORIG(fix_domain)(env);              // остальное -> в оригинал
//   }
//   CH_HOOK_ADDR(0xb99a8, fix_domain);                // пропатчить адрес 0xb99a8 на fix_domain
//
// offset — ОРИГИНАЛЬНЫЙ vmaddr цели (как в IDA на исходном бинаре). Строку-модуль здесь
// НЕ указываем: в embedded одна либа собирается под один бинарь (таргет задаёт конфиг).
// Модуль появится в shared-режиме (одна либа на много бинарей).
//
// Имена с префиксом CH_ — чтобы не сталкиваться с чужими HOOK/ORIG (Substrate, Logos,
// vendored machomerger_hook.h). Если конфликтов нет и хочется краткости —
//   #define COLDHOOK_SHORT_NAMES
// перед include даст голые HOOK_ADDR / ORIG / DECLARE_ORIG.

// --- экспорт (обычно НЕ нужен) -------------------------------------------------------
// Для CH_HOOK_ADDR-хуков атрибут видимости не требуется: функция-хук должна быть лишь
// НЕ static (чтобы у неё был глобальный символ для glue-ветки `b _fn`); видимость на
// внутри-dylib ссылку не влияет. CH_EXPORT нужен ТОЛЬКО если ты собираешь с
// -fvisibility=hidden или функцию надо найти через dlsym. `used` ещё и спасает от dead-strip.
#define CH_EXPORT __attribute__((visibility("default"), used))

// --- вызов оригинала из detour-хука -------------------------------------------------
#define CH_ORIG(name) coldhook_orig_##name
#define CH_DECLARE_ORIG(name, ret, ...) extern ret coldhook_orig_##name(__VA_ARGS__)

// --- регистрация хука по адресу ------------------------------------------------------
// Раскрывается в file-scope inline-asm, который генерит магик-символы для мёрджера:
//   _MACHOMERGER_HOOK_COLDHOOK_ADDR_<off>      : ветка на функцию-хук;
//   _MACHOMERGER_ORIG_COLDHOOK_ADDR_<off>      : слот сохранённой 1-й инструкции цели;
//   _MACHOMERGER_HOOKTRAMPOLINE_COLDHOOK_ADDR_<off>: слот `B цель+4` (СМЕЖНО с ORIG);
//   _coldhook_orig_<fn>                        : alias, его зовёт CH_ORIG(fn).
// .no_dead_strip держит символы при -dead_strip; смежность ORIG/TRAMPOLINE сохраняется,
// т.к. они в одном asm-блоке и линкер не переставляет атомы без причины.
// data-anchor (указатель в __DATA_CONST) гарантирует LC_SEGMENT_SPLIT_INFO (требование
// мёрджера). __DATA_CONST, а не __DATA — мёрджер не умеет добавлять новый сегмент.
#define CH__STUB(off, fn) \
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

// Публичный макрос: CH_HOOK_ADDR(offset, функция). Всегда detour-способен (CH_ORIG
// доступен); для полного replace просто не зови CH_ORIG.
#define CH_HOOK_ADDR(off, fn) CH__STUB(off, fn)

// --- регистрация хука ПО ИМЕНИ СИМВОЛА -----------------------------------------------
// Для целей, у которых есть символ (в т.ч. Swift-мангл). sym — СТРОКОВЫЙ литерал имени БЕЗ
// ведущего подчёркивания, как в `nm <binary>` после `_`:
//   nm app | grep url   ->  _$s12MyApp3url3forS2S_tF   ->  sym = "$s12MyApp3url3forS2S_tF"
// Мёрджер резолвит символ в symtab таргета (defined, N_SECT) и патчит его первую инструкцию.
// ORIG работает так же, как у CH_HOOK_ADDR (PC-relative пролог переэнкодится мёрджером).
// Swift-хук: замена и оригинал — Swift-функции с тем же ABI через @_silgen_name:
//   @_silgen_name("ch_url") func chURL(_ d: String) -> String { ... ch_orig_url(d) }
//   @_silgen_name("coldhook_orig_ch_url") func ch_orig_url(_ d: String) -> String
//   // в .c рядом:  CH_HOOK_SYM("$s12MyApp3url3forS2S_tF", ch_url);
#define CH__STUB_SYM(sym, fn) \
  __asm__( \
    ".text\n.p2align 2\n" \
    ".globl _MACHOMERGER_HOOK_" sym "\n" \
    ".no_dead_strip _MACHOMERGER_HOOK_" sym "\n" \
    "_MACHOMERGER_HOOK_" sym ":\n    b _" #fn "\n" \
    ".globl _MACHOMERGER_ORIG_" sym "\n" \
    ".no_dead_strip _MACHOMERGER_ORIG_" sym "\n" \
    "_MACHOMERGER_ORIG_" sym ":\n    brk #0\n" \
    ".globl _MACHOMERGER_HOOKTRAMPOLINE_" sym "\n" \
    ".no_dead_strip _MACHOMERGER_HOOKTRAMPOLINE_" sym "\n" \
    "_MACHOMERGER_HOOKTRAMPOLINE_" sym ":\n    brk #0\n" \
    ".globl _coldhook_orig_" #fn "\n" \
    "_coldhook_orig_" #fn ":\n    b _MACHOMERGER_ORIG_" sym "\n" \
    ".section __DATA_CONST,__const\n.p2align 3\n" \
    "_coldhook_anchor_sym_" #fn ":\n    .quad _MACHOMERGER_HOOK_" sym "\n" \
  )
#define CH_HOOK_SYM(sym, fn) CH__STUB_SYM(sym, fn)

// --- опциональные короткие алиасы ----------------------------------------------------
#ifdef COLDHOOK_SHORT_NAMES
  #define HOOK_ADDR(off, fn)            CH_HOOK_ADDR(off, fn)
  #define HOOK_SYM(sym, fn)             CH_HOOK_SYM(sym, fn)
  #define ORIG(name)                    CH_ORIG(name)
  #define DECLARE_ORIG(name, ret, ...)  CH_DECLARE_ORIG(name, ret, __VA_ARGS__)
#endif

#endif
