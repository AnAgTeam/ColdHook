# ColdHook

ColdHook статически патчит Mach-O-бинари iOS/macOS: код хука сливается с приложением на этапе сборки, без jailbreak runtime-патчинга и W^X-переходов. Например, для sideload.

## Зачем

В sideload без джейлбрейка нельзя патчить код в рантайме — в частности, использовать
`MSHookFunction` (`%hookf`). При этом `MSHookMessage` для Objective-C остаётся рабочим.
ColdHook позволяет удобно патчить функции не в рантайме, а статически, на этапе сборки.
Swift-код практически всегда статичен, поэтому обычный Logos-подход в sideload для него
почти бессилен; ColdHook закрывает этот пробел статическими хуками по mangled-имени или адресу.

Поддерживаются:

- хуки по символу (`CH_HOOK_SYM`);
- хуки по адресу/смещению (`CH_HOOK_ADDR`) для stripped-бинарей;
- `ORIG` для вызова оригинальной функции;
- shared-режим — одна hook dylib для приложения и его framework-ов;
- Logos `%hookf`, `%ctor`, `%group` и ObjC-свизл;
- Swift hooks по mangled имени или адресу;
- FAT Mach-O с обработкой arm64/arm64e-слайсов в обычной команде `merge`/`patch`;
- патчинг `.app` и `.ipa` с последующей переподписью.

Внутренняя схема сегментов, таблицы shared-режима, bootstrap, relocation и ограничения Mach-O описаны в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Быстрый старт

### Вариант 1: готовый релиз

Для обычного использования достаточно скачать из GitHub Release:

- бинарь `MachOMerger` для macOS;
- Python-пакет/скрипт `coldhook`;
- runtime `libcoldhook.dylib` для shared-режима.

Положи `MachOMerger` в `vendor/MachOMerger/.build/release/` либо укажи путь через переменные окружения проекта. После этого можно сразу запускать команды ниже — локальная сборка Swift не требуется.

### Вариант 2: сборка из исходников

Собрать MachOMerger:

```bash
cd vendor/MachOMerger
swift build -c release
cd ../..
```

Python-зависимости для CLI устанавливаются стандартным способом проекта. Для Theos-шаблонов
отдельно выполни `python3 -m coldhook install-theos`. Эта команда ставит только NIC-шаблоны
ColdHook в уже установленный `$THEOS`; сам Theos и его `logos.pl` она не устанавливает.

Чтобы команда `coldhook-logos` была доступна shared Logos-шаблону из `make`, сначала установи
сам Python-пакет (из корня checkout):

```bash
python3 -m pip install -e .
```

После этого выполни `python3 -m coldhook install-theos`. `install-theos` сам пакет через pip не
устанавливает.

Итого для сборки шаблонов нужны обе зависимости: установленный Python с пакетом ColdHook и
установленный Theos (`$THEOS`, включая `logos.pl`, makefiles и clang/Swift toolchain). Python
нужен также во время `make`: Logos-шаблон запускает `coldhook-logos`, а Swift-шаблон запускает
встроенный `coldhook_swift_preprocess.py`.

### Windows

Для shared-патчинга уже собранных thin Mach-O достаточно Python-пакета ColdHook (он ставит
кроссплатформенный `lief`), `MachOMerger.exe`, готового `userhooks.dylib` и
`libcoldhook.dylib`. Команда `coldhook shared` не требует `coldhook.toml`: selectors читаются
из export trie hook-dylib, а bundle упаковывается встроенным Python `zipfile`.

Статические `patch`/`ipa` по конфигурации и FAT-обработка пока требуют Apple-инструменты
`lipo`/`otool`; сборка hook-кода также остаётся задачей macOS/Theos/Xcode. Подпись на Windows
выполняется отдельным sideload-инструментом после патчинга.

### Использование

Одиночный merge:

```bash
python3 -m coldhook merge \
  --target Target.app/Target \
  --dylib .theos/obj/debug/arm64/MyTweak.dylib \
  --out Target.patched
```

Патчинг IPA/app по конфигу:

```bash
python3 -m coldhook ipa input.ipa \
  --config coldhook.toml \
  --out output.ipa
```

Shared-режим:

```bash
python3 -m coldhook shared input.ipa \
  --dylib MyHooks.dylib \
  --runtime libcoldhook.dylib \
  --out output.ipa \
  --verbose
```

Для тестовых bundle с неподдерживаемыми служебными Mach-O можно добавить `--skip-unsupported`.
Команда `shared` не выполняет FAT-слайсинг автоматически и рассчитана на thin Mach-O.

Подпись по умолчанию не выполняется для `ipa`. При `--sign-bundle` подписываются обработанные
target-бинари; добавленные shared hook/runtime dylib нужно подписать отдельно перед подписью
самого app способом, подходящим для конкретного sideload-инструмента.

## C/Objective-C API

```c
#include <coldhook.h>

CH_DECLARE_ORIG(domain_for, const char *, int);

const char *my_domain_for(int env) {
    if (env == 99) return "https://fallback";
    return CH_ORIG(domain_for)(env);
}

CH_HOOK_SYM("domain_for", my_domain_for);
```

Для stripped-функции используется адрес/смещение:

```c
CH_DECLARE_ORIG(fix_domain, const char *, int);
const char *fix_domain(int env) {
    return env == 99 ? "https://fallback" : CH_ORIG(fix_domain)(env);
}
CH_HOOK_ADDR(0xb99a8, fix_domain);
```

Гейтируемый вариант по умолчанию вызывает оригинал и включается из конструктора:

```c
CH_DECLARE_GATE(fix_domain);
CH_HOOK_SYM_GATED("domain_for", fix_domain);

__attribute__((constructor)) static void init(void) {
    if (setting_enabled()) CH_GATE_ENABLE(fix_domain);
}
```

## Logos

Установка шаблонов Theos:

```bash
python3 -m coldhook install-theos
$THEOS/bin/nic.pl
```

В меню выбери `iphone/coldhook_tweak` для Logos/Objective-C или `iphone/coldhook_tweak_swift` для Swift. После создания проекта обычные `make`/`make package` остаются Theos-командами.

Для Logos нужен установленный Theos с `$THEOS/bin/logos.pl`: ColdHook запускает собственный
Python-пре-пасс, который переводит `%hookf`/`%hookf_shared` в статические декларации, а
оставшиеся `%hook`, `%ctor` и `%group` обрабатывает штатный `logos.pl`. Отдельно ставить
«препроцессор ColdHook» не нужно — он входит в Python-пакет (`coldhook-logos`), но при установке
пакета как CLI-команды должен быть доступен в `PATH`.

Swift-шаблон не использует Swift macros и отдельный Swift-препроцессор. В проект уже входит
`coldhook_swift_preprocess.py`; `make` запускает его автоматически, генерирует glue и затем
Theos компилирует Swift-код обычным Swift-компилятором. Поэтому нужны Theos и Xcode/Swift
(сборка Swift остаётся macOS-зависимой), но вручную устанавливать Swift macro toolchain не надо.

Публичные shared-шаблоны (`coldhook-shared` и `coldhook-swift-shared`) не привязаны к checkout
ColdHook: первый вызывает `coldhook-logos` из `PATH`, второй содержит свой Python-препроцессор.
Старые embedded-шаблоны (`coldhook-tweak` и `coldhook-swift-tweak`) при генерации NIC получают
абсолютный путь к текущему checkout ColdHook и привязаны к его месту установки.

В `Tweak.x` можно использовать привычный Logos:

```logos
%hookf(const char *, domain_for, int env) {
    if (env == 99) return "https://fallback";
    return %orig;
}

%ctor {
    NSLog(@"ColdHook loaded");
}
```

Для shared-режима:

```logos
%hookf_shared("TestSwiftApp", const char *, domain_for, int env) {
    return "patched domain";
}
```

`make` генерирует hook dylib, а `coldhook shared` применяет её к подходящим бинарям bundle. `%group` переводится в gated-механику и активируется через `%init(Group)`.

## Swift

Swift-функция должна сохранять ABI оригинала:

```swift
import Foundation

@_silgen_name("orig_url")
private func orig_url(for domain: String) -> String

@_silgen_name("url")
public func url(for domain: String) -> String {
    if domain == "unknown" { return "patched" }
    return orig_url(for: domain)
}
```

Для shared Swift используется декларация с бинарём и mangled target:

```swift
@ColdHookMangled(
    binary: "TestSwiftApp",
    target: "$s12TestSwiftApp3url3forS2S_tF"
)
public func url(for domain: String) -> String {
    return "patched"
}
```

Готовый Theos-шаблон Swift устанавливается той же командой `install-theos`, после чего запускается `$THEOS/bin/nic.pl` с выбором `iphone/coldhook_tweak_swift`. Glue-код и экспортные объявления генерируются автоматически.

## Тестовое приложение

`tests/TestSwiftApp` — SwiftUI-приложение с отдельным `TestFramework`. В репозитории есть end-to-end runner для iOS Simulator:

```bash
python3 tests/simulator/run_shared.py \
  --udid <SIMULATOR_UDID>
```

Он собирает приложение, создаёт shared hook dylib и runtime, патчит main binary и framework, устанавливает bundle в simulator и запускает один UI-тест. Тест проверяет:

- замену Swift-функций в основном приложении;
- shared hook внутри framework;
- вызов patched-функции через UI.

Локальные macOS-полигоны находятся в `tests/macos/`, C/Swift-примеры — в `tests/hooks/`.

## Лицензия

Проект распространяется под MIT. Лицензии vendored-компонентов находятся в `vendor/`.
