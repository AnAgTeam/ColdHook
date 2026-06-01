// target.c — «жертва»: зеркалит паттерн SomeBank TypeA.makeUrl(for:).
// Возвращает домен для известного окружения, иначе намеренно падает.
// Компилируется в libtarget.dylib. Символ цели: _domain_for.
//
// В отличие от import-free версии M1, тут есть РЕАЛЬНЫЙ импорт (_getpid из libSystem),
// чтобы importsCountA > 0 — для проверки merge импортов таргета A.
#include <unistd.h>

const char *domain_for(int env);

// Указатель в __DATA -> rebase -> LC_SEGMENT_SPLIT_INFO (требование MachOMerger).
void *const g_target_self = (void *)domain_for;

// НЕ хукается. Реально дёргает импорт A (_getpid) — проверка, что бинд A
// корректно перенесён и резолвится в слитом бинаре (исполнением, не только статикой).
__attribute__((visibility("default")))
int target_health(void)
{
    return (int)getpid();
}

__attribute__((visibility("default")))
const char *domain_for(int env)
{
    // getpid() — настоящий внешний бинд (_getpid), не сворачивается в builtin.
    int live = (getpid() > 0);
    switch (env) {
        case 0: return live ? "https://prod.real.example"  : "https://0.invalid";
        case 1: return live ? "https://stage.real.example" : "https://0.invalid";
        default:
            // Неизвестное окружение — намеренный провал (как assertionFailure в SomeBank).
            __builtin_trap();
    }
}
