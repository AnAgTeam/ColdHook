#include <coldhook.h>

// Swift-замена (@_silgen_name("ch_url") в hook.swift). Тип не важен — нужна лишь ветка на символ.
extern void ch_url(void);

// СПОСОБ 1 (рекомендуется) — по ИМЕНИ символа. Мангл `url(for:)` из `nm`, без ведущего `_`:
//   nm <app>/TestSwiftApp | grep url  ->  _$s12TestSwiftApp3url3forS2S_tF
// Не зависит от адреса (offset плывёт между сборками). CH_HOOK_SYM навешивает HOOK + ORIG-слот
// + alias _coldhook_orig_ch_url (его и зовёт ch_url_orig из hook.swift).
CH_HOOK_SYM("$s12TestSwiftApp3url3forS2S_tF", ch_url);

// СПОСОБ 2 (альтернатива) — по АДРЕСУ (для стрипнутых бинарей без символов). vmaddr из IDA/nm;
// поменяется при пересборке таргета. Раскомментируй вместо CH_HOOK_SYM:
// CH_HOOK_ADDR(0x100004298, ch_url);
