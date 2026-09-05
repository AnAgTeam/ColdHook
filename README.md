# ColdHook

ColdHook статически патчит Mach-O-бинари iOS/macOS: код хука сливается с приложением на этапе сборки, без jailbreak runtime-патчинга и W^X-переходов. Например, для sideload.

Поддерживаются:

- хуки по символу (`CH_HOOK_SYM`);
- хуки по адресу/смещению (`CH_HOOK_ADDR`) для stripped-бинарей;
- `ORIG` для вызова оригинальной функции;
- shared-режим — одна hook dylib для приложения и его framework-ов;
- Logos `%hookf`, `%ctor`, `%group` и ObjC-свизл;
- Swift hooks по mangled имени или адресу;
- FAT Mach-O с обработкой arm64/arm64e-слайсов;
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

Python-зависимости для CLI устанавливаются стандартным способом проекта. Для Theos-шаблонов отдельно выполни `python3 -m coldhook install-theos`.

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

Для тестовых bundle с FAT XCTest-бинарями можно добавить `--skip-unsupported`.

Подпись по умолчанию не выполняется для `ipa`; после merge app нужно переподписать способом, подходящим для конкретного sideload-инструмента.

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
nic.pl
```

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

Готовый Theos-шаблон Swift устанавливается той же командой `install-theos`. Glue-код и экспортные объявления генерируются автоматически.

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
