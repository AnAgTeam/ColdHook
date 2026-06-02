# logos_tweak — Logos-твик с бэкендом ColdHook (пример)

Пишешь обычный Logos, собираешь, инжектишь — но **статикой через merge**, без джейлбрейка и W^X.
`%hookf` (хук C-функции) и `%ctor` едут статикой ColdHook; `%group` даёт **рантайм-переключаемый**
(gated) хук. См. `Tweak.x`.

Запускаемое доказательство (без устройства): `tests/macos/run_logos.py` — прогоняет пре-пасс +
сток-logos + merge + запуск (ungrouped detour с `%orig` и gated `%group`).

## Что во что превращается

| Конструкт | Бэкенд |
|---|---|
| `%hookf` | **статика ColdHook** — `CH_HOOK_SYM`, патч 1-й инструкции цели на merge; `%orig` -> `CH_ORIG` |
| `%hookf` в `%group` | **gated** — патч на thunk через указатель в `__DATA`; `%init(Group)` включает рантаймом |
| `%ctor` / `%orig` | как обычно (конструктор сливается через `__init_offsets`) |
| ObjC `%hook` | компилится (шим `MSHookMessageEx`), но через merge ПОКА не активируется — приедет с shared-режимом |

Пре-пасс (`coldhook/logos_prepass.py`) вырезает `%hookf` -> статический glue, остальное (ObjC,
`%ctor`, `%group`/`%init`) отдаёт стоковому `logos.pl`. Тот уже не генерит рантайм `MSHookFunction`.

## Цель `%hookf`: по имени или по адресу

```objc
%hookf(const char *, get_label_text, ...)   // по ИМЕНИ символа (nm <target>, без ведущего _)
%hookf(const char *, 0x100004488, ...)      // по АДРЕСУ-литералу (для стрипнутых)
```
- **by-name** — канонический Logos; такой твик собирается и под джейл/Substrate, и под ColdHook.
- **by-address (`0x…`)** — РАСШИРЕНИЕ ColdHook (в каноне Logos второй слот = имя символа). Удобно
  для стрипнутых целей, но твик с адресом **НЕ соберётся под стоковый theos/Substrate** — только ColdHook.

> ⚠️ **Адрес НЕЛЬЗЯ указывать через `%init(имя = адрес)`.** В Logos это рантайм-биндинг под
> `MSHookFunction` (значение указателя в момент выполнения конструктора), а ColdHook патчит
> статически на merge — рантайм-адрес из `%init` приходит слишком поздно. Пре-пасс `%init`-биндинги
> для адресов НЕ читает. Нужен адрес — пиши его прямо в `%hookf` (форма `0x…` выше).

## Через theos (рекомендуется)

```bash
python3 -m coldhook install-theos     # один раз: ставит NIC-шаблон «ColdHook Tweak»
nic.pl                                # выбери «ColdHook Tweak», получишь проект с этим Tweak.x
make                                  # -> .theos/obj/debug/arm64/<Name>.dylib  (пре-пасс внутри)
```

## Вручную (без theos)

```bash
CH=../../..                            # корень репозитория ColdHook
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
# 1) пре-пасс + сток-logos -> ObjC++:
python3 $CH/coldhook/logos_prepass.py Tweak.x > Tweak.mm
# 2) компиляция твика (+ substrate-шим для ObjC/групп):
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" -fobjc-arc \
  -I $CH/coldhook/include -I $CH/coldhook/substrate -framework Foundation -lc++ \
  -dynamiclib Tweak.mm $CH/coldhook/substrate/substrate.m -o ch.dylib \
  -Xlinker -install_name -Xlinker @rpath/ch.dylib \
  -Xlinker -fixup_chains -Xlinker -add_split_seg_info -Wl,-no_warn_inits
```

## Инжект в цель (отдельный шаг)

```bash
python3 -m coldhook merge --target <target-binary> --src ch.dylib --out <patched>
# или собрать+merge+resign+поставить на устройство:
python3 $CH/scripts/build_install.py --hook ch.dylib
```

Цель `%hookf` — имя символа как в `nm <target> | grep <fn>` (без ведущего `_`).
