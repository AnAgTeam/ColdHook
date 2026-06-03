# ColdHook

Статический «холодный» хук iOS-бинарей через **слияние** хук-кода в таргет (на базе
MachOMerger), без рантайм-кодогенерации и W^X-переходов. Хуки — **по символам**
(`CH_HOOK_SYM`), **по оффсету** (`CH_HOOK_ADDR` для стрипнутых) и **гейтируемые**
(`*_GATED`, рантайм-переключаемые). Есть **Logos-интеграция** (пиши твики, ставь статикой —
см. ниже) и Swift-хуки. Подробный план — `coldhook_plan.md`.

## Структура

```
coldhook/             Python-оркестратор (info | merge | patch | ipa)
coldhook/include/     coldhook.h — макросы хука (CH_HOOK_ADDR / CH_HOOK_SYM / CH_ORIG / _GATED)
coldhook/logos_prepass.py  Logos-пре-пасс: %hookf -> статика ColdHook, остальное -> сток logos.pl
coldhook/substrate/   clean-room шим Substrate-API (MSHookMessageEx -> свизл ObjC) + coldhook_objc.m (уникер selref'ов твика)
coldhook/templates/   NIC-шаблоны «ColdHook Tweak» (Logos) и «ColdHook Swift Tweak» (install-theos)
scripts/              build_install.py — сборка → merge → resign → установка на устройство
tests/macos/          запускаемые macOS-харнессы (arm64) — полигоны без устройства
tests/hooks/          готовые сэмплы хука (swift_replace, export_byname, hook_byaddr)
tests/TestApp/        ObjC тест-приложение (мишень)
tests/TestSwiftApp/   Swift тест-приложение (мишень)
docs/                 swift-dsl.md — дизайн будущего @Hook DSL
vendor/MachOMerger/   форк движка слияния (Dopamine 2.x, MIT) + правки ColdHook
vendor/dyldhook/      референс макросов HOOK()/ORIG()
coldhook_plan.md      подробный план; coldhook.toml — пример конфига; LICENSE — MIT
```

## Локальные харнессы (macOS arm64, без устройства)

```bash
# сборка движка (один раз)
cd vendor/MachOMerger && swift build -c release && cd -

python3 tests/macos/run.py           # merge + Replace + ORIG + импорты A/B (dylib)
python3 tests/macos/run_offset.py    # хук по сырому оффсету (магик-символ вручную)
python3 tests/macos/run_hookaddr.py  # by-offset через макрос CH_HOOK_ADDR + coldhook merge
python3 tests/macos/run_fat.py       # FAT (arm64+x86_64): патч arm64, x86_64 как есть
python3 tests/macos/run_newdylib.py  # хук тянет свой dylib (libz) -> --allow-new-dylibs
python3 tests/macos/run_exe.py        # merge в ГЛАВНЫЙ бинарь (MH_EXECUTE), запуск
python3 tests/macos/run_app.py       # полный .app: собрать -> coldhook ipa -> запустить
python3 tests/macos/run_ctor.py      # конструкторы (%ctor) И у таргета, И у хука -> оба
python3 tests/macos/run_sharedimport.py  # общий импорт (write) у таргета и хука -> bind
python3 tests/macos/run_nosplit.py   # append-режим: таргет БЕЗ split-info (exe + dylib)
python3 tests/macos/run_export.py    # хук ЭКСПОРТА по имени (CH_HOOK_SYM, C) + ORIG
python3 tests/macos/run_gated.py     # GATED-хук: статически установлен, рантайм-переключаемый
python3 tests/macos/run_logos.py     # Logos %hookf -> статика ColdHook (пре-пасс + сток logos.pl)
python3 tests/macos/run_objchook.py  # Logos ObjC %hook через ColdTheos (свизл + %orig + тело)
python3 tests/macos/run_swift.py     # Swift by-name хук + ORIG (PC-relative пролог)
```

### Реальные бинари без split-info (append-режим)

Приложения/фреймворки идут без `LC_SEGMENT_SPLIT_INFO`. Тогда мёрджер не двигает таргет
(оставляет на месте, его фиксапы/entry валидны), а сегменты хука **аппендит** после, переписывая
заголовок в существующем padding'е. Детект автоматический. Проверено end-to-end на устройстве:
Swift-хук вмёрджен в подписанное приложение, переподписан, краш убран. Сэмпл — `tests/hooks/swift_replace`.

### Хук Swift-методов (by-name / by-offset + ORIG)

Чистые Swift-методы (без `@objc`) Logos не берёт — у них нет селектора. ColdHook патчит статически:
- по адресу: `CH_HOOK_ADDR(0x..., fn)`;
- по имени символа (вкл. мангл): `CH_HOOK_SYM("$s12App3url...", fn)` (имя из `nm` без ведущего `_`).

Замена — Swift-функция с тем же ABI (`@_silgen_name`), `CH_ORIG(fn)` зовёт оригинал. Первая
инструкция-пролог может быть PC-relative (`cbz`/`cbnz`/`tbz` на guard'ах) — мёрджер переэнкодит
её под адрес ORIG-слота. `@objc dynamic`-методы можно хукать и обычным ObjC-путём (через `NSString`).

Шаблон под theos — `coldhook install-theos` → `nic.pl` → «ColdHook Swift Tweak» → `make` (без
пре-пасса/шима, чистый swiftc + glue.c). Готовый пример — `tests/hooks/swift_replace`.

### Хуки по оффсету в коде (`CH_HOOK_ADDR`)

Для стрипнутых бинарей — обычная функция + `CH_HOOK_ADDR(offset, fn)` (из `<coldhook.h>`);
оффсет = оригинальный vmaddr цели (как в IDA). Магик-символы/ORIG-трамплины генерит макрос.

```c
#include <coldhook.h>
CH_DECLARE_ORIG(fix_domain, const char *, int);   // объявить оригинал (для detour)
const char *fix_domain(int env) {                 // обычная функция, без атрибутов
    if (env == 99) return "https://fallback";     // чиним провал
    return CH_ORIG(fix_domain)(env);              // остальное -> в оригинал
}
CH_HOOK_ADDR(0xb99a8, fix_domain);
```

Префикс `CH_` — чтобы не сталкиваться с чужими `HOOK`/`ORIG` (Substrate/Logos/vendored
`machomerger_hook.h`). `#define COLDHOOK_SHORT_NAMES` до include даёт короткие алиасы
`HOOK_ADDR`/`ORIG`/`DECLARE_ORIG`. Атрибут видимости не нужен — функция-хук должна быть
лишь не-`static`; для `dlsym`/`-fvisibility=hidden` есть `CH_EXPORT`.

Конфиг для такого таргета — просто `binary` + `sources` (оффсеты живут в коде). Строка-модуль
`CH_HOOK_ADDR("Bin", off, fn)` зарезервирована под будущий shared-режим (одна либа на много бинарей).

Готовые сэмплы (copy-paste под свою цель): `tests/hooks/export_byname` (хук экспорта по имени) и
`tests/hooks/hook_byaddr` (хук по адресу) — оба C, с `ORIG` и probe-конструктором; Swift —
`tests/hooks/swift_replace`.

Паттерн цели: `domain_for(env)` отдаёт домен для известного окружения, иначе падает
в `__builtin_trap()` (модель `assertionFailure`). Хук чинит провальный путь, известное
делегирует оригиналу через `ORIG`.

### Гейтируемые хуки (статически установлен, рантайм-переключаемый)

`CH_HOOK_SYM_GATED(sym, fn)` / `CH_HOOK_ADDR_GATED(off, fn)` — хук впечён в бинарь, но первая
инструкция цели ведёт на тонкий thunk через указатель в писчем `__DATA`. Дефолт = ORIG (хук
ВЫКЛ, цель работает прозрачно); рантайм-флип включает — без W^X, атомарной записью указателя:

```c
CH_DECLARE_GATE(fix);
CH_HOOK_SYM_GATED("target_fn", fix);
__attribute__((constructor)) static void init(void) {
    if (setting_enabled()) CH_GATE_ENABLE(fix);   // иначе остаётся ORIG (выкл)
}
```

Под капотом групп Logos (`%init(Group)`) и тоглов твика из настроек. Сэмпл — `tests/macos/run_gated.py`.

## Logos-интеграция (ColdTheos): пиши твики, ставь статикой

Привычный theos-воркфлоу, но бэкенд — статический merge ColdHook (без джейлбрейка/W^X).
`%hookf` (хук C-функции) и `%ctor` едут статикой; `%group` даёт гейтируемый хук.

```bash
python3 -m coldhook install-theos     # один раз: NIC-шаблон «ColdHook Tweak» в $THEOS
nic.pl                                # выбери «ColdHook Tweak» -> проект с Tweak.x
make                                  # -> .theos/obj/.../<Name>.dylib  (пре-пасс внутри)
python3 -m coldhook merge --target <bin> --src <dylib> --out <patched>   # инжект отдельно
```

Пишешь только `Tweak.x` обычным Logos. На `make` ColdHook-пре-пасс (`coldhook/logos_prepass.py`)
переводит `%hookf` в статический glue (`.coldhook/Tweak.xm`), а остальное (ObjC, `%ctor`,
`%group`/`%init`) отдаёт **стоковому** `logos.pl` — тот уже не генерит рантайм `MSHookFunction`
(= инлайн-патч кода = W^X, которого в сайдлоаде нет).

| Конструкт Logos | Бэкенд ColdHook |
|---|---|
| `%hookf` | статика — `CH_HOOK_SYM`, патч 1-й инструкции на merge; `%orig` -> `CH_ORIG` |
| `%hookf` в `%group` | гейтируемый — включается рантаймом на `%init(Group)` |
| `%ctor` / `%orig` | как обычно (конструктор сливается через `__init_offsets`) |
| ObjC `%hook` | работает — свизл `method_setImplementation` (шим `MSHookMessageEx`); selref'ы твика уникует бутстрап `coldhook_objc.m` после merge |

ObjC `%hook` через merge: append переименовывает сегменты твика (`__DATA_CONST` → `__BDATA_CONST`),
из-за чего ObjC-runtime не уникует его selref'ы (`@selector` держит свою копию строки, а не
канонический `SEL`). Бутстрап-конструктор `coldhook/substrate/coldhook_objc.m` уникует их вручную
на загрузке — после этого свизл и message-send'ы в теле хука работают. Это покрывает свизл
существующих методов (99% `%hook`) и `%new` в существующем классе. Свой ObjC-класс/категория в
твике пока требует доп. шага (`objc_registerClassPair`). Прогон — `tests/macos/run_objchook.py`.

Цель `%hookf` — по имени (`%hookf(ret, symbol, args)`, канон, переносимо) или по адресу-литералу
(`%hookf(ret, 0xADDR, args)` → `CH_HOOK_ADDR`, расширение ColdHook, под стоковый Substrate не
соберётся). Адрес через `%init(имя = адрес)` **нельзя** — это рантайм-указатель `MSHookFunction`,
а ColdHook ставит хук статически на merge.

Граница: синтаксис/`nic`/`make`/ObjC-свизл — за theos; статическая установка — за ColdHook
(тонкая прослойка: пре-пасс + substrate-шим `coldhook/substrate/` + `install-theos`, не форк).
Пример — `tests/hooks/logos_tweak/`; запускаемый прогон (пре-пасс + сток-logos + merge) —
`tests/macos/run_logos.py`.

## Оркестратор (Python)

Интроспекция Mach-O → сборка хука под платформу таргета → merge → (опц.) resign.

```bash
python3 -m coldhook info   <binary>
python3 -m coldhook merge  --target <binary> --src hook.c --src orig_stubs.S --out <out>
python3 -m coldhook patch  -c coldhook.toml                    # пачкой, отдельные бинари
python3 -m coldhook ipa    <in.ipa|.app> -c cfg -o <out>       # merge в бандл in-place
```

Конфиг (`coldhook.toml`) — список `[[target]]` (binary → sources|dylib) + `[signing]`.
Проверяет арку/платформу/cryptid; FAT — патчит arm64/arm64e-слайсы, остальные оставляет.

Импорты хука B: новые символы из dylib, которые таргет **уже линкует**, дозаписываются
автоматически. Если хуку нужен dylib, которого в таргете НЕТ — по умолчанию ошибка;
`allow_new_dylibs = true` (в `[[target]]`) или `--allow-new-dylibs` (в `merge`) разрешает
дописать `LC_LOAD_DYLIB`. Доп. флаги линковки хука — `ldflags = ["-lz"]` / `--ldflags`.

**Подпись**: `merge`/`patch` подписывают (codesign/ldid), `ipa` — НЕТ по умолчанию
(`--sign-bundle` включает). iOS-установка требует подписи отдельно.

## Статус

- [x] M1: parse + merge + Replace-хук по символу + codesign + загрузка (локально, macOS)
- [x] Merge импортов таргета A (Step 1) + внешних импортов B (Step 2), dual-format (arm64 2/6, arm64e 1/12)
- [x] Detour-режим (`ORIG`/возврат в оригинал, single-instruction трамплин)
- [x] Хук по оффсету: магик-символ `COLDHOOK_ADDR_<hex>` + макрос `CH_HOOK_ADDR(off, fn)` в коде (+ `CH_ORIG`/`CH_DECLARE_ORIG`/`CH_EXPORT`, короткие алиасы за `COLDHOOK_SHORT_NAMES`)
- [x] Python-оркестратор: `info | merge | patch`
- [x] Патч бандла `ipa` (.ipa/.app, merge in-place, без подписи) + macOS .app полигон
- [ ] Подпись бандла под TrollStore/dev-серт (resign .app, порядок вложенности)
- [x] FAT-слайсинг (патч arm64/arm64e-слайсов, неподдерживаемые — как есть, сборка lipo)
- [x] Свои dylib у B (`--allow-new-dylibs`: вставка LC_LOAD_DYLIB + ремап dylib-ordinals)
- [x] Merge в главный бинарь (MH_EXECUTE): `__PAGEZERO` verbatim, база 0x100000000, `LC_MAIN`/`LC_LOAD_DYLINKER`, флаги заголовка
- [x] Конструкторы (`%ctor`/`__attribute__((constructor))`) у хука И таргета: слияние `__TEXT,__init_offsets` A+B в одну секцию (dyld4 не терпит две)
- [x] Общий внешний импорт таргета и хука (`write`, Foundation и т.п.): резолв в symtab A только по DEFINED-символам -> bind, а не rebase в мусор
- [x] Append-режим: хуки в РЕАЛЬНЫЕ бинари без `LC_SEGMENT_SPLIT_INFO` (A не двигаем, B аппендом); проверено на устройстве. Выбор `--mode auto\|append\|interleave`
- [x] Swift-хуки: by-name (мангл) + by-offset + ORIG с переэнкодом PC-relative пролога (`cbz`/`adrp`/…)
- [x] Гейтируемые хуки (`CH_HOOK_SYM_GATED`/`*_ADDR_GATED`): статически установлен, рантайм-переключаемый (thunk через указатель в `__DATA`, дефолт = ORIG)
- [x] Logos-интеграция (ColdTheos): `%hookf`/`%ctor`/`%group` статикой через пре-пасс + сток-logos; NIC-шаблон + `install-theos`; substrate-шим
- [x] Робастность мёрджера на debug/STABS-dylib (theos `make`): STAB не путается с реальными символами
- [x] ObjC `%hook` через merge (Путь B): бутстрап `coldhook_objc.m` уникует selref'ы твика из `__BDATA_CONST` после merge; append восстанавливает `SG_READ_ONLY` на const-сегментах A; свизл существующих методов + `%new`. Прогоны — `run_objc.py`, `run_objchook.py`
- [ ] ObjC: свой класс/категория в твике (`objc_registerClassPair`) / exports trie / multi-chain / FAT для arm64e на устройстве / Swift `@Hook`-фасад (`docs/swift-dsl.md`) / sig-prescan (`docs/sig-prescan.md`) / shared-режим (`docs/shared-mode.md`)

## Лицензии

Проект — **MIT** (см. `LICENSE`), покрывает собственный код ColdHook (`coldhook/`, `scripts/`,
`tests/`, `docs/`, файлы верхнего уровня).

Завендоренный код в `vendor/` — тоже MIT, но под своей лицензией (Dopamine, © 2023–2024 opa334;
движок MachOMerger — Linus Henze). См. `vendor/LICENSE-Dopamine.md` и `vendor/NOTICE.md`.
