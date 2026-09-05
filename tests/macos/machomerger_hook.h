#ifndef __MACHOMERGER_HOOK_H
#define __MACHOMERGER_HOOK_H

// Магик-символы MachOMerger. Имя должно совпадать с символом цели БЕЗ ведущего
// подчёркивания: C-функция domain_for имеет символ _domain_for -> HOOK(domain_for).
#define HOOK(name) COLDHOOK_SYM_##name
#define ORIG(name) COLDHOOK_ORIG_SYM_##name

#endif
