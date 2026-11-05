// Реализация substrate-шима ColdHook (см. CydiaSubstrate/CydiaSubstrate.h).
// Линкуется в твик; даёт рантайм-свизл ObjC без джейлбрейка и без W^X.

#import "CydiaSubstrate/CydiaSubstrate.h"
#include <dlfcn.h>

// ObjC-метод -> method_setImplementation (чистый ObjC-runtime, работает в песочнице).
// Корректно ловит диспатч (подклассы/категории) — этим ObjC и оставляем за Logos-рантаймом.
void MSHookMessageEx(Class cls, SEL sel, IMP hook, IMP *old) {
    if (!cls) { if (old) *old = NULL; return; }
    // Дефенсивно уникуем селектор регистрации: если ObjC-бутстрап (coldhook_objc.m) ещё не
    // отработал (порядок конструкторов), sel может быть неуникнутым указателем на cstring ->
    // class_getInstanceMethod промахнётся. sel_registerName канонизирует (для уже-канонического
    // sel это no-op). selref'ы в ТЕЛЕ хука уникует бутстрап (к вызову хука он уже отработал).
    if (sel) sel = sel_registerName((const char *)(void *)sel);
    Method m = class_getInstanceMethod(cls, sel);
    if (!m)   { if (old) *old = NULL; return; }
    IMP prev = method_setImplementation(m, hook);
    if (old) *old = prev;
}

// C-функция: в ColdHook это СТАТИЧЕСКИЙ путь (пре-пасс переводит %hookf в CH_HOOK_*). Рантайм-
// инлайн-патч в сайдлоаде невозможен (W^X) -> no-op. Если сюда дошли, значит %hookf не прошёл
// через пре-пасс — хук просто не встанет (а не упадёт).
void MSHookFunction(void *symbol, void *hook, void **old) {
    (void)symbol; (void)hook;
    if (old) *old = NULL;
}

// Поиск символа в загруженном образе. MS ожидает имя с ведущим '_', dlsym — без.
void *MSFindSymbol(MSImageRef image, const char *name) {
    if (name && name[0] == '_') name++;
    return dlsym(image ? (void *)image : RTLD_DEFAULT, name);
}

// Образ по имени файла — только если уже загружен (RTLD_NOLOAD), как и оригинал.
MSImageRef MSGetImageByName(const char *file) {
    return (MSImageRef)dlopen(file, RTLD_NOLOAD | RTLD_NOW);
}
