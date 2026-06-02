#include <coldhook.h>

// Detour ЭКСПОРТИРОВАННОЙ функции по ИМЕНИ символа (`domain_for(int) -> const char *`).
// Кейс «хук публичного API библиотеки/бинаря»: у цели есть символ в symtab, цепляемся по нему —
// адрес не нужен и не плывёт между сборками. Для валидного env зовём ОРИГИНАЛ (CH_ORIG),
// провальный путь (где оригинал уходил в trap) чиним фолбэком — это detour, а не голый replace.
//
// Замена — ОБЫЧНАЯ функция с тем же прототипом, что у цели. CH_HOOK_SYM навешивает магик-символы
// мёрджера (HOOK + ORIG-слот + alias _coldhook_orig_domain_fix). PC-relative пролог (cbz/cbnz/...)
// мёрджер переэнкодит под адрес ORIG-слота сам.

CH_DECLARE_ORIG(domain_fix, const char *, int);          // объявить оригинал (для detour)

const char *domain_fix(int env) {
    if (env == 99) return "https://fallback.coldhook";   // чиним провальный путь
    return CH_ORIG(domain_fix)(env);                     // остальное -> ОРИГИНАЛ экспорта
}

// Символ — как в `nm <binary> | grep domain_for`, БЕЗ ведущего подчёркивания
// (`_domain_for` -> "domain_for"). Мёрджер резолвит его в symtab цели (defined, N_SECT).
CH_HOOK_SYM("domain_for", domain_fix);
