#include <coldhook.h>

// Привязка Swift-замены к цели. Тип ch_hook не важен — нужна лишь ветка на её символ.
extern void ch_hook(void);

// СПОСОБ 1 (рекомендуется) — по ИМЕНИ символа (Swift-мангл). Имя из `nm <target> | grep`,
// БЕЗ ведущего '_'. CH_HOOK_SYM навешивает магик-символы мёрджера + alias _coldhook_orig_ch_hook
// (его зовёт ch_orig из Hook.swift). PC-relative пролог (cbz/adrp/...) мёрджер переэнкодит сам.
CH_HOOK_SYM("$s12YourModule6target3argS2S_tF", ch_hook);

// СПОСОБ 2 (альтернатива) — по АДРЕСУ (стрипнутая цель, vmaddr из IDA/nm). Поменяется при
// пересборке таргета. Раскомментируй вместо CH_HOOK_SYM:
// CH_HOOK_ADDR(0x100004298, ch_hook);
