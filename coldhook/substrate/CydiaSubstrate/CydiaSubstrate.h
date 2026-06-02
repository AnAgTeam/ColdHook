#ifndef COLDHOOK_CYDIASUBSTRATE_H
#define COLDHOOK_CYDIASUBSTRATE_H

// Clean-room шим API Cydia Substrate для САЙДЛОАДА (без джейлбрейка/Substrate).
// Logos-генерённый код линкуется против этих символов; ColdHook даёт их статически:
//   - ObjC-свизл (%hook)  -> ObjC-runtime (method_setImplementation), без W^X;
//   - C-функции (%hookf)  -> СТАТИКА ColdHook (CH_HOOK_*) на этапе merge; рантайм MSHookFunction
//                            в сайдлоаде невозможен (инлайн-патч кода = W^X) -> no-op для линковки.
// Имена/сигнатуры повторяют публичный API (совместимость), реализация — своя (см. substrate.m).

#include <objc/runtime.h>
#include <objc/message.h>

#ifdef __cplusplus
extern "C" {
#endif

// ObjC-метод -> рантайм-свизл. В *_old кладётся прежний IMP (это %orig).
void MSHookMessageEx(Class _class, SEL _cmd, IMP _hook, IMP *_old);

// C-функция. В ColdHook её хук — статический (CH_HOOK_*), пре-пасс убирает вызов отсюда.
// Оставлено как no-op для совместимости линковки, если MSHookFunction где-то остался.
void MSHookFunction(void *_symbol, void *_hook, void **_old);

void *MSFindSymbol(void *_image, const char *_name);
void *MSGetImageByName(const char *_file);

#ifdef __cplusplus
}
#endif

#endif
