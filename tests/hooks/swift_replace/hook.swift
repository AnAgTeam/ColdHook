import Foundation

// Хук чистого Swift-метода `url(for domain: String) -> String` (мишень №2 в TestSwiftApp):
// для известного домена "application" зовём ОРИГИНАЛ (CH_ORIG), а для остального — где
// оригинал уходит в preconditionFailure (краш) — возвращаем фолбэк. Это detour, не просто
// replace: половина смысла твика в вызове оригинала.
//
// Замена и оригинал — Swift-функции с ОДИНАКОВЫМ ABI (`(String) -> String`). @_silgen_name
// даёт фиксированные C-символы при сохранённом Swift-ABI (его нельзя выразить через @_cdecl —
// Swift String это value-тип, не NSString). Магик-символы навешивает glue.c.

// оригинал: символ _coldhook_orig_ch_url, который генерит CH_HOOK_SYM (см. glue.c)
@_silgen_name("coldhook_orig_ch_url")
func ch_url_orig(_ domain: String) -> String

// замена: на её символ _ch_url ветвится пропатченная первая инструкция цели
@_silgen_name("ch_url")
public func ch_url_impl(_ domain: String) -> String {
    if domain == "application" {
        return ch_url_orig(domain)        // валидный путь -> ОРИГИНАЛ
    }
    return "https://fallback.coldhook"    // вместо краша на неизвестном домене
}
