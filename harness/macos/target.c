// target.c — «жертва»: зеркалит паттерн SomeBank TypeA.makeUrl(for:).
// Возвращает домен для известного окружения, иначе намеренно падает.
// Компилируется в libtarget.dylib. Символ цели: _domain_for.
//
// ВАЖНО: бинарь должен быть БЕЗ импортов (требование MachOMerger: zero imports for A).
// Поэтому никакого libc — abort/fprintf заменены на __builtin_trap() (-> brk, без бинда).
const char *domain_for(int env);

// Указатель в __DATA -> нужен rebase -> линкер эмитит LC_SEGMENT_SPLIT_INFO,
// которого требует MachOMerger. (Заодно реалистичнее «настоящего» бинаря.)
void *const g_target_self = (void *)domain_for;

__attribute__((visibility("default")))
const char *domain_for(int env)
{
    switch (env) {
        case 0: return "https://prod.real.example";
        case 1: return "https://stage.real.example";
        default:
            // Неизвестное окружение — намеренный провал (как assertionFailure в SomeBank).
            // brk #1 — процесс падает по SIGILL/SIGTRAP, импорта не требует.
            __builtin_trap();
    }
}
