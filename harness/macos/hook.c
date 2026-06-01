// hook.c — наш патч-бинарь, сливается в libtarget.dylib через MachOMerger.
// M1: чистый Replace — перенаправляем _domain_for на свою реализацию без возврата в оригинал.
// HOOK(domain_for) => символ _MACHOMERGER_HOOK_domain_for; мёрджер ставит на цель `B` на нас.
#include "machomerger_hook.h"

const char *HOOK(domain_for)(int env);

// Указатель в __DATA -> rebase -> LC_SEGMENT_SPLIT_INFO (требование MachOMerger).
void *const g_hook_self = (void *)HOOK(domain_for);

__attribute__((visibility("default")))
const char *HOOK(domain_for)(int env)
{
    // Что бы ни пришло — отдаём валидный домен, никаких abort.
    (void)env;
    return "https://hooked.coldhook.local";
}
