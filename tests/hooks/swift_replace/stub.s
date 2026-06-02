// Магик-символ ColdHook для хука ПО ОФФСЕТУ: _MACHOMERGER_HOOK_COLDHOOK_ADDR_<vmaddr-hex>.
// Мёрджер находит этот символ, читает <hex> как адрес цели и подменяет ПЕРВУЮ инструкцию
// цели на `b <этот стаб>`. Стаб тейл-ветвится в Swift-замену (ABI сохраняется, кадра нет).
//
// ВНИМАНИЕ: 100004298 — vmaddr `url(for:)` в КОНКРЕТНОЙ сборке TestSwiftApp. Для своей сборки:
//   nm -n <binary> | grep -i 'url\|<символ>'   -> взять адрес (напр. 0x100004298)
// и заменить суффикс символа ниже на этот hex без 0x.
.text
.p2align 2
.globl _MACHOMERGER_HOOK_COLDHOOK_ADDR_100004298
_MACHOMERGER_HOOK_COLDHOOK_ADDR_100004298:
    b _ch_url_impl
