# ColdHook Shared Mode — архитектура и актуальные задачи

Цель: одна хук-либа на **несколько бинарей** процесса (main + фреймворки), загружается как
обычный dylib. Существующие сегменты target не переименовываются; для metadata/stub добавляются
синтетические `__COLDHOOK_TEXT` и `__COLDHOOK_DATA`. Это позволяет держать тело хука один раз,
а не дублировать в каждый таргет.

Реализовано: shared table/bootstrap, selector filtering, append-стратегия, `%hookf_shared`,
shared gated-группы, ORIG slots, Logos/NIC-шаблоны и runtime linker stub. Обычный ObjC `%hook`
обслуживается Logos/Substrate shim в embedded-шаблоне, а не shared backend.

## Следующие этапы

- объединение таблиц при применении нескольких shared hook dylib;
- provider-aware resolution вместо глобального `RTLD_DEFAULT` при совпадающих handler-именах;
- Swift DSL/build plugin для автоматической генерации glue и поиска mangled symbol.

## Embedded vs Shared

| | embedded | shared (реализовано) |
|---|---|---|
| хук-код | смёрджен В таргет, сегменты → `__BTEXT/__BDATA` | ОДИН раз в обычном dylib, сегменты нормальные |
| загрузка | вместе с таргетом (он же и есть) | отдельный `LC_LOAD_DYLIB` в каждый обработанный image |
| привязка | merge-time, один образ | два образа, слайдятся **раздельно** (ASLR) |
| ObjC `%hook` | работает через Logos/Substrate shim | не является функцией shared backend |
| гейты/группы | работают | даже чище (нормальный writable `__DATA` + конструктор dylib) |

Главное следствие: target и hook-lib двигаются независимо. Отсюда две трудности — обе решаются
переиспользованием уже готового.

## Универсальный bootstrap и таблица связки

Вместо добавления отдельного dyld-import для каждого handler можно использовать один и тот же
bootstrap-код во всех версиях `libcoldhook.dylib`. MachOMerger при патчинге target синтезирует
только stub-код и metadata; bootstrap не перекомпилируется при добавлении или удалении хуков.

В target добавляются синтетические сегменты `__COLDHOOK_TEXT,__coldhook_stub` и
`__COLDHOOK_DATA,__coldhook`. Таблица, slots и строки metadata находятся в одной writable
секции `__COLDHOOK_DATA,__coldhook`. Формат секции самоописываемый и версионируемый:

```c
struct ColdHookTable {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint16_t record_size;
    uint16_t flags;
    uint32_t count;
    uint32_t records_offset;
    uint32_t strings_offset;
    uint32_t strings_size;
};

struct ColdHookRecord {
    uint64_t hook_id;
    uint32_t handler_slot_offset;
    uint32_t reserved0;
    uint64_t orig_image_offset;
    uint32_t handler_name_offset;
    uint32_t handler_name_size;
    uint32_t orig_slot_key;
    uint32_t flags;
};
```

Тот же ABI зафиксирован в `coldhook/include/coldhook_shared.h`. Runtime bootstrap реализован в
`coldhook/shared_runtime.c` и собирается в универсальную `libcoldhook.dylib`. Все offsets, кроме
`orig_image_offset`, относительны к началу `__DATA,__coldhook`; `orig_image_offset` — смещение
orig-трамплина относительно слайда target-образа. `handler_slot_offset` находится в target.
`orig_slot_key` идентифицирует слот в registry shared dylib, который bootstrap связывает с
`orig_image_offset`; поэтому код, сгенерированный для `%orig`, не требует target-экспорта.

`handler_name_offset` указывает на экспортное имя handler в shared dylib. Стабильный `hook_id`
может использоваться как дополнительная проверка соответствия `(binary, locator, handle)`.
Orig-трамплин остаётся в target, поэтому его адрес можно записать непосредственно в metadata;
экспортировать каждый orig-символ через export trie необязательно.

Bootstrap, выполняющийся из constructor shared dylib, делает следующее:

1. перечисляет загруженные Mach-O через dyld API;
2. находит `__DATA,__coldhook` у каждого target;
3. проходит записи и читает имена из string table;
4. разрешает handler в собственной shared dylib через `dlsym`;
5. атомарно заполняет `handler_slot` и `orig_slot`.

После этого вызов имеет вид:

```text
target function → local stub → handler_slot → shared handler
shared handler → orig_slot → target orig trampoline
```

Имена должны иметь уникальный префикс (`_coldhook_handler$...`), чтобы исключить случайное
разрешение символа из другого образа. Если handler, ORIG slot или gated dispatch не найден,
bootstrap пишет диагностику и завершает процесс через `abort()` (fail-fast).

Одна custom data-секция для таблицы и строк проще, чем синтезировать
импорт и chained-fixup bind для каждого handler. Native dyld-bind остаётся альтернативным,
более быстрым режимом, если в target достаточно места и его metadata можно безопасно расширить.

## Почему основной режим — bootstrap-table, а не native-bind

Для shared MVP выбирается `bootstrap-table`. Native-bind теоретически быстрее, но требует для
каждого target синтезировать обычный импорт handler-а, GOT-слот, bind/chained-fixup запись и, в
двухуровневом namespace, корректную связь с `LC_LOAD_DYLIB`. На реальных Mach-O это означает
расширение symbol/bind metadata и иногда load-command region; в headerpad или append-сценарии
для этого может не оказаться места. Ошибка в одной цепочке fixups ломает загрузку всего образа.

Табличный режим добавляет в target только локальный stub и заранее описанную custom-секцию с
фиксированным ABI. Имена handler-ов хранятся как данные, а не как dyld imports, поэтому один и
тот же bootstrap может обслуживать любое число хуков и несколько target-бинарей без изменения
собственного кода. Это также упрощает диагностику (`magic`/`version`/`count`), обработку
отсутствующих handler-ов и поддержку поздно загруженных образов через callback dyld.

Цена — один раз выполнить `dlsym` на hook при старте и поддерживать shared-side registry для
`%orig`. Для cold-hook сценария это предпочтительнее: стоимость startup пренебрежимо мала, а
патчинг кода и W^X-переходы по-прежнему отсутствуют.

## Точки интеграции реализации

Shared backend не должен переделывать существующий embedded merge path. Точки расширения
разделяются следующим образом:

| Компонент | Ответственность shared backend |
|---|---|
| `vendor/MachOMerger/.../main.swift` | shared-режим оставляет hook dylib отдельным и эмитит target metadata/stubs |
| `SharedHooks.swift` / `SharedAssembler.swift` | разобрать `CH_DYN_*`, выбрать записи и собрать metadata/stubs |
| `RelocInfo.swift` / `SegmentSplitInfo.swift` | дать адресные преобразования для orig/stub и проверить дальность локального `B` |
| `coldhook/include/coldhook_shared.h` | общий ABI таблицы, уже зафиксированный для патчера и bootstrap |
| `coldhook/build.py` | собрать shared dylib один раз и передать его каждому target |
| `coldhook/ipa.py` | найти main/framework images, установить dylib/runtime и при `--sign-bundle` подписать обработанные target images |
| runtime bootstrap | перечислить dyld images, прочитать metadata, разрешить handler names и заполнить registry/slots |

Текущие `MagicSymbols.swift` и `mergeChainedFixups` рассчитаны на merge двух образов и не должны
использоваться для разрешения shared handler-ов: в таблице сохраняется имя с magic-префиксом,
а его разрешение переносится в bootstrap. Существующие arm64 branch encoder и
`coldhookReencodeForSlot` переиспользуются для синтеза stub/orig.

## Трудность 1: дальность ветвления

Прямой `b` на ARM64 — ±128 МБ. Target и shared-lib в разных регионах → не дотянется. Нужен
косвенный бранч через указатель, который биндит dyld (import, не локальный слот). Но это 3
инструкции (12 байт) на входе → релокация 3 пролог-инструкций (риск PC-relative/бранча).

**Решение — два прыжка** (патч входа остаётся в ОДНУ инструкцию, как в embedded):

```
вход таргета:   b  <appended_stub>          ; 1 инструкция -> переиспуем save+reencode из embedded
appended_stub:  adrp x16,[got]              ; дописан к ТАРГЕТУ (тот же образ, в пределах ±128МБ)
                ldr  x16,[x16,#off]         ; got-слот биндит dyld -> hook в shared-lib
                br   x16
```

Дальнобойную часть прячем в дописанный к таргету stub-регион; вход трогаем минимально.

## Трудность 2: ORIG при раздельном слайде

PC-relative пролог, переэнкоженный и положенный в shared-lib, посчитает не ту страницу (слайд
другой). **Решение:** orig-трамплин держим **в образе таргета** (дописываем офлайн) — он слайдится
с таргетом; shared-lib зовёт `%orig` через import, dyld биндит в экспорт трамплина.

```
target:  _coldhook_orig_<bin>_<h>:  <reencode 1-й инстр> ; b target+4    (ЭКСПОРТ)
shared:  %orig  ->  import _coldhook_orig_<bin>_<h>                       (dyld bind)
```

## Установка (всё офлайн, no W^X, без JB)

Per каждый именованный бинарь:

```
1. дописать stub-регион + orig-трамплин (см. выше)
2. пропатчить вход хукнутых функций -> b <appended_stub>
3. каждый обработанный target image получает `LC_LOAD_DYLIB` на shared-lib (так dyld грузит её
   на старте, без `DYLD_INSERT`)
4. выбрать способ связки handler-ов:
   - **bootstrap-table (текущая реализация):** синтезировать `__COLDHOOK_TEXT` и
     `__COLDHOOK_DATA,__coldhook`; универсальный constructor shared-lib заполнит слоты через
     `dlsym`.
5. переподписать каждый тронутый бинарь и добавленные dylib (вручную либо отдельным bundler-ом)
```

В текущем bootstrap-table target не синтезирует отдельный import для каждого handler-а: runtime
разрешает имя через `dlsym` и заполняет локальный slot. ORIG передаётся через target-слайд и
экспортируемые runtime slots.

## Синтаксис: декларация ↔ тело

Разделяем **локатор** (метадата для инсталлера: бинарь/адрес/символ) и **тело** (код). Одна форма
тела `%hookf(ret, handle)` обслуживает все локаторы; `handle` — ключ связки (и для `%orig`, и для
препасса). Имя бинаря в декларации выбирает бэкенд: нет имени → embedded, есть → **shared**.

```c
// V1: символ в «текущем» таргете           -> embedded по умолчанию
CH_SYM(target1);
%hookf(void, target1)(int a) { %orig(a); }

// V2: адрес в текущем бинаре                -> embedded
CH_ADDR(0x100400, target2);
%hookf(void, target2)(void) { %orig(); }

// V3: адрес в ИМЕНОВАННОМ бинаре            -> ФОРСИТ shared (= зарезервированный HOOK_ADDR("Bin",...))
CH_DYN_ADDR("MainBinary", 0x8000, target3);
%hookf(void, target3)(void) { %orig(); }

// V4 (симметрия): символ в именованном бинаре -> shared
CH_DYN_SYM("SomeFramework", "_internalFn", target4);
%hookf(void, target4)(void) { %orig(); }
```

Маппинг по реализации:

| форма | бинарь | бэкенд | механизм |
|---|---|---|---|
| `CH_SYM(h)` | «тот самый» | embedded | by-name, всё готово |
| `CH_ADDR(off,h)` | «тот самый» | embedded | by-address, всё готово |
| `CH_DYN_ADDR("B",off,h)` | именованный | **shared** | stub+orig+двусторонний бинд, имя→путь через манифест |
| `CH_DYN_SYM("B",sym,h)` | именованный | **shared** | то же, локатор = символ вместо адреса |

## Где тут `%hookf`

Тело `%hookf` **mode-agnostic**. Препасс ColdTheos уже превращает `%hookf` → статическую glue;
разница только в бэкенде:

- **embedded build** — тело компилится В таргет, магик-символы `CH_HOOK_*` (как сейчас);
- **shared build** — то же тело компилится В shared-lib как export + import на orig; препасс
  отдаёт инсталлеру манифест-строку `(binary, locator, hook-sym, orig-sym)`.

Тело пишется одинаково; выбор embedded/shared делает декларация (`CH_DYN_*` форсят shared).

## Что переиспользуется / что новое

| Уже есть | Новое для shared |
|---|---|
| save+reencode первой инструкции входа (ORIG) | два прыжка: `b stub` + appended `adrp/ldr/br` через import-GOT |
| import-binding B (Step 2 / 2c, `--allow-new-dylibs`) | синтез import `_ch_hook_<h>` на ТАРГЕТЕ (не B-в-A, а патч готового бинаря) |
| gated-thunk, конструкторы хука/таргета | orig-трамплин-регион, ЭКСПОРТируемый таргетом (nlist + bind) |
| FAT-слайсинг, resign (`coldhook/ipa.py`, `macho.py`) | shared bundle обрабатывает thin images; FAT-слайсинг выполняется обычным `merge`/`patch` |
| препасс `%hookf` → статика | бэкенд-свитч embedded/shared в препассе + `CH_DYN_*` декларации |

## Открытые вопросы

- **Selector** имя→image проверяется оркестратором; при неоднозначности требуется
  bundle-relative или абсолютный selector.
- **`b stub` ≥ 4 байта** на входе: у крошечных leaf-функций может не хватить места под даже одну
  инструкцию-замену с сохранением (как и в embedded, но тут чаще). Нужна проверка длины + ошибка.
- **Подпись** — тронутых бинарей теперь несколько (main + каждый хукнутый фреймворк + shared-lib);
  surface шире embedded, all-или-ничего по entitlements. Оркестратор копирует dylib/runtime,
  а подпись добавленных dylib выполняется отдельным шагом.
- **Порядок загрузки** — runtime регистрирует callback dyld и обрабатывает уже загруженные и
  поздно добавленные images; отсутствие обязательной записи приводит к fail-fast `abort()`.
- **arm64e/PAC** — указатель в GOT-слоте может требовать auth-биндинга; `br x16` без auth ок, но
  слот биндим как обычный/auth по формату цепочки таргета.
- **Где живёт shared-lib в .app** — путь установки + корректный `install_name`/rpath, чтобы
  `LC_LOAD_DYLIB` главного бинаря её нашёл при запуске.

## Связанные сущности (уже в репо)

- `coldhook/include/coldhook.h` — `CH_HOOK_ADDR`/`CH_HOOK_SYM`, gated-макросы и реализованные `CH_DYN_*`.
- `vendor/MachOMerger` — shared table/stub assembly и save+reencode входа.
- `coldhook/ipa.py` — обход main/framework images, установка dylib/runtime; `macho.py` отвечает
  за introspection и FAT-слайсинг обычного merge-пути.
- `coldhook/logos_prepass.py` — препасс `%hookf` и `%hookf_shared`, генерирующий `CH_DYN_*`.
- Соседи по плану — `docs/swift-dsl.md`, `docs/sig-prescan.md`, `[[coldhook-direction-symbols-merge]]`.
- ObjC `%hook` остаётся ответственностью Logos/Substrate shim embedded-шаблона — см. `[[logos-integration-coldhook]]`,
  `[[append-mode-no-splitinfo]]`.
