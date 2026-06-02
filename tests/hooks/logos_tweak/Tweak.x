#import <Foundation/Foundation.h>

// Пример Logos-твика с бэкендом ColdHook (статический хук через merge, без джейлбрейка/W^X).
// Пишется как обычный Logos; ColdHook-пре-пасс переводит %hookf в статический патч на этапе
// merge (без рантайм-MSHookFunction = инлайн-патч кода = W^X, которого в сайдлоаде нет).
//
// Сборка/инжект и что во что превращается — см. README.md. Запускаемый аналог (на macOS,
// прогоняет пре-пасс + сток-logos + merge): tests/macos/run_logos.py.

// --- %hookf: detour C-функции по ИМЕНИ символа (из `nm <target> | grep`, без ведущего _) ---
%hookf(const char *, get_label_text) {
    const char *o = %orig;                       // вызвать ОРИГИНАЛ
    NSLog(@"[coldhook] get_label_text orig=%s", o);
    return "Hooked by ColdHook";                 // подмена
}

// --- %hookf В ГРУППЕ: gated — установлен статически, но РАНТАЙМ-ПЕРЕКЛЮЧАЕМЫЙ ---
// До %init(Feature) цель работает как оригинал; после — активен. Удобно для тоглов.
%group Feature
%hookf(int, feature_flag) { return 1; }          // включить фичу, когда группа активна
%end

%ctor {
    NSLog(@"[coldhook] tweak loaded");
    if (getenv("ENABLE_FEATURE")) %init(Feature);  // включить gated-группу по условию
}
