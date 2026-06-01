// hook.c — наш патч-бинарь, сливается в libtarget.dylib через MachOMerger.
// M1: чистый Replace. Step 2: хук реально зовёт ВНЕШНЮЮ функцию (_getppid из libSystem),
// которой нет в импортах A — проверка merge внешних импортов B (ремап dylib-ordinal на A).
// HOOK(domain_for) => символ _MACHOMERGER_HOOK_domain_for; мёрджер ставит на цель `B` на нас.
#include "machomerger_hook.h"
#include <unistd.h>

const char *HOOK(domain_for)(int env);

// Указатель в __DATA -> rebase -> LC_SEGMENT_SPLIT_INFO (требование MachOMerger).
void *const g_hook_self = (void *)HOOK(domain_for);

// Экспорт для проверки: возвращает getppid() из хук-кода (внешний импорт B _getppid).
// Драйвер сравнит со своим getppid() — должны совпасть, значит бинд резолвится верно.
__attribute__((visibility("default")))
int hook_ppid(void)
{
    return (int)getppid();
}

__attribute__((visibility("default")))
const char *HOOK(domain_for)(int env)
{
    (void)env;
    // getppid() — внешний импорт B (_getppid), отсутствует в импортах A.
    // Если merge внешних импортов сломан — здесь будет краш на резолве бинда.
    if (getppid() > 0) {
        return "https://hooked.coldhook.local";
    }
    return "https://0.invalid";
}
