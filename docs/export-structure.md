# Экспорты и hook-декларации

В проекте есть два разных уровня, которые нельзя смешивать.

## Декларации ColdHook

Это magic-символы, которые создаются в hook-dylib и читаются MachOMerger:

| Форма | Локатор | Binary selector | Режим |
|---|---|---|---|
| `CH_HOOK_SYM(sym, fn)` | имя символа | нет, текущий target | embedded/shared |
| `CH_HOOK_ADDR(off, fn)` | vmaddr/offset | нет, текущий target | embedded/shared |
| `CH_HOOK_SYM_GATED(sym, fn)` | имя символа | нет, текущий target | embedded |
| `CH_HOOK_ADDR_GATED(off, fn)` | vmaddr/offset | нет, текущий target | embedded |
| `CH_DYN_SYM(bin, sym, fn)` | имя символа | `bin` | shared |
| `CH_DYN_ADDR(bin, off, fn)` | vmaddr/offset | `bin` | shared |

`CH_DYN_*` не требуют отдельного конфигурационного файла: selector хранится в
magic-декларации самого hook-dylib. MachOMerger получает один и тот же dylib для
каждого Mach-O и оставляет только записи, чей selector совпадает с текущим образом.

## Грамматика имён

Ниже приведены именно имена Mach-O-символов (с ведущим `_`), которые видит
MachOMerger. Это не имена C-функций и не имена секций.

### Обычные декларации

Для `CH_HOOK_SYM("domain_for", domain_fix)` создаётся:

```text
_COLDHOOK_SYM_domain_for
_COLDHOOK_ORIG_SYM_domain_for
_COLDHOOK_TRAMPOLINE_SYM_domain_for
_coldhook_orig_domain_fix
```

Первая строка — locator хука. Две следующие — служебные ORIG/trampoline-слоты.
Последняя строка — alias, через который тело handler-а вызывает оригинал.

Для `CH_HOOK_ADDR(0x1234, fix)` locator кодируется как:

```text
_COLDHOOK_ADDR_0x1234
_COLDHOOK_ORIG_ADDR_0x1234
_COLDHOOK_TRAMPOLINE_ADDR_0x1234
```

`COLDHOOK_ADDR_<hex>` — это magic-значение, а не экспорт target-бинаря.

### Именованные shared-декларации

Для реализованных `CH_DYN_SYM("Foo", "domain_for", domain_fix)` и
`CH_DYN_ADDR("Foo", 0x1234, fix)` используется self-describing namespace:

```text
_COLDHOOK_DYN_SYM_<binary-selector>__CH__<locator>__CH__<handler>
_COLDHOOK_DYN_ADDR_<binary-selector>__CH__<locator>__CH__<handler>
```

Примеры:

```text
_COLDHOOK_DYN_SYM_Foo__CH__domain_for__CH__domain_fix
_COLDHOOK_DYN_ADDR_Foo__CH__COLDHOOK_ADDR_0x1234__CH__fix
```

Внутри merger имя разбирается в `SharedHooks.swift`:

```text
prefix = _COLDHOOK_DYN_<kind>_
binary-selector __CH__ locator __CH__ handler
```

`binary-selector` сравнивается с identity текущего Mach-O, `locator` разрешается
через общий symbol resolver или как `COLDHOOK_ADDR_*`, а `handler` записывается в
shared-таблицу как имя, передаваемое runtime в `dlsym`. Последовательность `__CH__` в этих полях
должны быть запрещены или экранироваться на этапе генерации.

Это служебные export-like magic-символы hook-dylib. Они не являются экспортами
target-бинаря: target export разрешается отдельно, а runtime-экспортом handler-а
остаётся обычная глобальная функция `domain_fix`/`fix`.

## Данные Mach-O, которые могут описывать экспорт

На уровне Mach-O практически используются два источника имён и адресов:

1. `LC_SYMTAB` — классическая таблица `nlist_64` со строковой таблицей. Она может
   содержать defined (`N_SECT`) символы, undefined (`N_UNDF`) импорты и STABS/debug
   записи. Для поиска target-локатора подходят только defined non-STAB symbols.
2. `LC_DYLD_EXPORTS_TRIE` (или старый `LC_DYLD_INFO[_ONLY]`) — компактное trie,
   используемое dyld для публичных экспортов. В узле могут быть обычный export,
   weak-def, re-export, thread-local export или stub-and-resolver export.

Дополнительные флаги export trie влияют на способ загрузки символа, но не меняют
формат ColdHook locator. Для первой реализации достаточно единого resolver API:
`name -> address + kind + flags`; конкретный источник (`symtab` или exports trie)
должен быть скрыт внутри resolver.

## Что поддерживает текущий merger

Общая часть разрешения использует raw `LC_SYMTAB` и фильтрует STABS и
undefined-записи. `LC_DYLD_EXPORTS_TRIE` сохраняется/пересобирается в output, но
отдельного trie-resolver для выбора hook target нет. Shared-декларации уже разбираются
в `SharedHooks.swift`, после чего target locator разрешается общим symtab-resolver-ом.
