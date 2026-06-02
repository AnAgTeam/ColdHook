import Foundation

// Замена Swift-функции с тем же ABI. Цель — `url(for domain: String) -> String`,
// которая в default уходит в preconditionFailure (краш). Возвращаем валидную строку.
//
// @_silgen_name даёт фиксированный C-символ `ch_url_impl`, СОХРАНЯЯ Swift-ABI String
// (его нельзя выразить через @_cdecl). На этот символ ветвится магик-стаб (stub.s).
@_silgen_name("ch_url_impl")
public func ch_url(_ domain: String) -> String {
    return "https://patched.coldhook"
}
