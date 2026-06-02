#import <Foundation/Foundation.h>

// @@PROJECTNAME@@ — твик на Logos с бэкендом ColdHook (статический хук через merge, без
// джейлбрейка/W^X). Пиши как обычный Logos-твик: ColdHook-пре-пасс переводит %hookf (хук
// C-функции) в статический патч на этапе merge, а %ctor/%group/%init и ObjC %hook отдаёт
// стоковому logos. См. README.

// Пример: detour C-функции по ИМЕНИ символа (из `nm <target-binary>`). Замени на свою цель.
// Цель можно задать и АДРЕСОМ-литералом: %hookf(ret, 0x100004488, args) -> CH_HOOK_ADDR
// (расширение ColdHook; такой твик не соберётся под стоковый Substrate). Адрес через
// %init(имя=адрес) НЕЛЬЗЯ — это рантайм-указатель MSHookFunction, не наш статический путь.
%hookf(const char *, example_function) {
    const char *result = %orig;                 // вызвать оригинал
    NSLog(@"[@@PROJECTNAME@@] orig returned: %s", result);
    return result;                              // верни своё, чтобы подменить
}

// Опционально — ГРУППА: хук становится РАНТАЙМ-ПЕРЕКЛЮЧАЕМЫМ (gated). Установлен статически,
// но неактивен, пока не вызовут %init(Feature). Удобно для тоглов из настроек.
// %group Feature
// %hookf(const char *, other_function) { return "patched"; }
// %end

%ctor {
    NSLog(@"[@@PROJECTNAME@@] loaded");
    // %init(Feature);   // включить группу Feature (если используешь)
}
