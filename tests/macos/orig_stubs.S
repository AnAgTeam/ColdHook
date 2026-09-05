// orig_stubs.S — ORIG-трамплины для ColdHook (arm64).
//
// Для каждой хукнутой функции — два СМЕЖНЫХ 4-байтных слота:
//   _MACHOMERGER_ORIG_<sym>:           слот 0 — мёрджер кладёт сюда сохранённую
//                                      первую инструкцию оригинала;
//   _MACHOMERGER_HOOKTRAMPOLINE_<sym>: слот 1 — мёрджер кладёт сюда `B <sym>+4`.
// Вызов ORIG(<sym>) исполняет [1-я инструкция][B sym+4] => продолжает оригинал со 2-й.
//
// ВАЖНО: НЕ эмитим .subsections_via_symbols — иначе линкер атомизирует по символам и
// может дед-стрипнуть/переставить трамплин, разорвав смежность слотов. Без него весь
// .text-блок — единый атом: оба слота остаются рядом, ссылка на ORIG из C тянет весь блок.
//
// Плейсхолдер brk #0 (0xd4200000): если мёрджер не перезапишет слот — будет явный трап,
// а не тихая ошибка.

.text
.p2align 2

.globl _COLDHOOK_ORIG_SYM_domain_for
_COLDHOOK_ORIG_SYM_domain_for:
    brk     #0

.globl _COLDHOOK_TRAMPOLINE_SYM_domain_for
_COLDHOOK_TRAMPOLINE_SYM_domain_for:
    brk     #0
