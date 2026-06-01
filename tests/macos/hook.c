// hook.c — патч-бинарь, сливается в libtarget.dylib через MachOMerger.
// ORIG-режим: хук чинит ТОЛЬКО провальный путь (неизвестное окружение -> вместо trap
// дефолтный домен), а известные окружения делегирует оригиналу через ORIG() — это
// проверяет возврат-трамплин в оригинальную функцию.
#include "machomerger_hook.h"
#include <unistd.h>

const char *HOOK(domain_for)(int env);
// Трамплин в оригинал: [сохранённая 1-я инструкция][B domain_for+4] (см. orig_stubs.S).
extern const char *ORIG(domain_for)(int env);

// Указатель в __DATA -> rebase -> LC_SEGMENT_SPLIT_INFO (требование MachOMerger).
void *const g_hook_self = (void *)HOOK(domain_for);

// Экспорт для проверки внешнего импорта B (_getppid), который нет в импортах A.
__attribute__((visibility("default")))
int hook_ppid(void)
{
    return (int)getppid();
}

__attribute__((visibility("default")))
const char *HOOK(domain_for)(int env)
{
    if (env == 99) {
        // Неизвестное окружение: оригинал ушёл бы в assert/trap — отдаём дефолт.
        return "https://hooked.fallback.local";
    }
    // Известное окружение: возвращаемся в оригинал через ORIG.
    return ORIG(domain_for)(env);
}
