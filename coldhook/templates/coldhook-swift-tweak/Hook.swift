import Foundation

// @@PROJECTNAME@@ — Swift-хук на ColdHook (статический патч через merge, без джейлбрейка/W^X).
// Чистые Swift-методы (без @objc) Logos не берёт — нет селектора. ColdHook патчит по символу.
//
// Замена и оригинал — Swift-функции с ОДИНАКОВЫМ ABI, что у цели, через @_silgen_name (чистый
// Swift нельзя выразить @_cdecl: String и пр. — value-типы). Подставь свою сигнатуру и символ.
// Мангл цели:  nm <target-binary> | grep <fn>   ->  _$s...   (демангл: `swift demangle`)

// ОРИГИНАЛ: символ _coldhook_orig_ch_hook генерит CH_HOOK_SYM в glue.c.
@_silgen_name("coldhook_orig_ch_hook")
func ch_orig(_ arg: String) -> String

// ЗАМЕНА: на её символ _ch_hook ветвится пропатченная 1-я инструкция цели.
@_silgen_name("ch_hook")
public func ch_hook(_ arg: String) -> String {
    if arg == "trigger" {
        return "patched by @@PROJECTNAME@@"     // подмена
    }
    return ch_orig(arg)                          // остальное -> ОРИГИНАЛ
}
