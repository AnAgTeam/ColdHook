#include <coldhook.h>

// Detour функции ПО АДРЕСУ — для СТРИПНУТЫХ целей, где символа в symtab нет. Адрес берём из
// дизассемблера (IDA/Ghidra/Hopper) или `nm`/`otool`: это ОРИГИНАЛЬНЫЙ vmaddr цели, как на
// исходном бинаре (мёрджер сам разрулит сдвиги при слиянии). Логика та же, что у by-name:
// валидный путь -> ОРИГИНАЛ (CH_ORIG), провальный -> фикс.
//
// Замена — обычная функция с прототипом цели. CH_HOOK_ADDR навешивает магик-символы по адресу
// (_COLDHOOK_ADDR_<off>): HOOK + ORIG-слот + alias _coldhook_orig_domain_fix. PC-relative первую
// инструкцию (cbz/cbnz/tbz/adr/b...) мёрджер переэнкодит под адрес ORIG-слота сам.

CH_DECLARE_ORIG(domain_fix, const char *, int);

const char *domain_fix(int env) {
    if (env == 99) return "https://fallback.coldhook";   // чиним провальный путь
    return CH_ORIG(domain_fix)(env);                     // остальное -> ОРИГИНАЛ
}

// Адрес цели (ОРИГИНАЛЬНЫЙ vmaddr, как в IDA). Поменяется при пересборке таргета — для
// стабильной привязки, если символ есть, предпочитай by-name (см. ../export_byname).
CH_HOOK_ADDR(0x100004488, domain_fix);
