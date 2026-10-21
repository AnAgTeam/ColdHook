# ColdHook

Основная версия: [README.md](README.md).

ColdHook статически патчит Mach-O-бинари iOS/macOS: код хука сливается с приложением на этапе сборки, без jailbreak runtime-патчинга и W^X-переходов. Например, для sideload.

## Зачем

В sideload без джейлбрейка нельзя патчить код в рантайме — в частности, использовать
`MSHookFunction` (`%hookf`). При этом `MSHookMessage` для Objective-C остаётся рабочим.
ColdHook позволяет удобно патчить функции не в рантайме, а статически, на этапе сборки.
Swift-код практически всегда статичен, поэтому обычный Logos-подход в sideload для него
почти бессилен; ColdHook закрывает этот пробел статическими хуками по mangled-имени или адресу.

### Сравнение решений

| Решение | Нужен jailbreak | Работает с sideloading | Native Swift hooks | Работает в рантайме? | Нужен исходный код |
|---|:---:|:---:|:---:|:---:|:---:|
| **ColdHook** | Нет | Да | Да | Нет | Нет |
| Frida Gadget | Нет* | Да | Да, с debugger/JIT или jailbreak | Да* | Нет |
| ElleKit / Substrate | Обычно | Ограниченно | Да, с debugger/JIT или jailbreak | Да | Нет |
| Objective-C swizzling | Нет | Да | Только Swift-методы, видимые ObjC runtime | Да | Нет |
| SwiftHook | Нет | Только собственное приложение | Только Swift-методы, видимые ObjC runtime | Да | Да |

`*` У Frida `Interceptor` есть ограничения на jailed iOS без подключённого debugger. Таблица
описывает типичный сценарий; совместимость зависит от версии iOS, способа подписи, наличия
символов и ABI.

SwiftHook — это библиотека, которая линкуется с самим приложением. Она меняет dispatch методов,
доступных через Objective-C runtime (например, `@objc dynamic`), но не внедряется в произвольные
native Swift-функции уже собранного IPA.

**Преимущество ColdHook:** он заменяет native Swift-функции в sideloaded bundle без jailbreak,
подключённого debugger и runtime JIT. **Компромисс:** хуки выбираются и применяются до установки;
их нельзя подключать, отключать или менять во время работы приложения. После обновления целевого
приложения обычно требуется заново собрать, пропатчить и переподписать bundle.

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

Положи `MachOMerger` (`MachOMerger.exe` на Windows) в текущую рабочую папку или `PATH`, либо задай путь в `COLDHOOK_MERGER`. После этого можно сразу запускать команды ниже — локальная сборка Swift не требуется.

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

Для shared-патчинга уже собранных thin и FAT Mach-O достаточно Python-пакета ColdHook (он ставит
кроссплатформенный `lief`), `MachOMerger.exe`, готового `userhooks.dylib` и
`libcoldhook.dylib`. Команда `coldhook shared` не требует `coldhook.toml`: selectors читаются
из export trie hook-dylib, а bundle упаковывается встроенным Python `zipfile`.

Чтение Mach-O, извлечение и замена FAT-слайсов выполняются переносимым Python-кодом.
Команды `info`, `merge`, `patch`, `ipa` и `shared` не требуют `lipo`/`otool`.
Для `merge`/`patch` на Windows используй готовые dylib и `--no-sign`;
подпись бандлов по умолчанию выключена. Shared обрабатывает совместимые arm64/arm64e-слайсы,
сохраняя остальные побайтно. Сборка исходников через `xcrun`/SDK и подпись
`--sign-bundle` через `codesign` пока требуют macOS — это оставшиеся пробелы совместимости.
На Windows подпиши результат отдельным sideload-инструментом. Запуск на Windows
нужно проверять отдельно; переносимые тесты не подтверждают полную совместимость.

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
Команда `shared` обрабатывает thin и FAT Mach-O, сохраняя слайсы, которые не патчит.
Обычный вывод показывает стадии, прогресс по Mach-O и итоговые счётчики. `--verbose`
дополнительно печатает объявления хуков и результат их применения к каждому бинарнику.

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

Swift-функция должна сохранять ABI оригинала. Укажите бинарь и mangled target;
build-препроцессор сам создаст внутренние linker names и orig thunk:

```swift
@ColdHookMangled(
    binary: "TestSwiftApp",
    target: "$s12TestSwiftApp3url3forS2S_tF"
)
public func url(for domain: String) -> String {
    if domain == "unknown" { return "patched" }
    return orig_url(for: domain)
}
```

Добавлять `@_silgen_name` вручную не нужно. Ручная Swift/C-связка остаётся
экспертным низкоуровневым escape hatch без стабильности внутренних имён.

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

Для быстрого контрактного smoke-теста Python-кода установите dev-зависимости и запустите:

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

`tests/macos/` остаётся основным end-to-end набором: его runner’ы собирают реальные Mach-O,
вызывают CLI/toolchain и проверяют результат. `tests/test_shared_template.py` проверяет только
контракт шаблона и Logos-пре-пасса, без сборки и запуска Mach-O.

Локальные macOS-полигоны находятся в `tests/macos/`, C/Swift-примеры — в `tests/hooks/`.

## Лицензия

Проект распространяется под MIT. Лицензии vendored-компонентов находятся в `vendor/`.


## Диагностика Python CLI

Нужен Python 3.11+ и `lief>=0.17`. Команды обработки проверяют LIEF при
запуске; `--help`, `--version` и `install-theos` не требуют этой проверки.
Метаданные и FAT-слайсы обрабатываются Python-кодом без Apple-инструментов.
Дополнительно проверяются `xcrun` для сборки исходников и `codesign` или `ldid` при включённой подписи.
Наличие инструментов не гарантирует наличие нужного SDK или сертификата.

```sh
python3 -m coldhook doctor
python3 -m coldhook --log-file coldhook.log patch -c coldhook.toml
python3 -m coldhook --debug info ./AppBinary
```

Глобальные параметры `--debug` и `--log-file` ставятся **перед командой**.
Обычная консоль — это компактный пользовательский вывод без дат и уровней
логирования. `--debug` выводит внутренние этапы, команды и traceback в консоль,
а `--log-file` сохраняет ту же полную диагностику с датой и временем в файл.
Файл журнала дополняется при повторном запуске. Ошибки возвращают код 1,
Ctrl+C — 130. Для отключения цвета используется `NO_COLOR=1`.

Поиск MachOMerger не требует исходников. Порядок:

1. `COLDHOOK_MERGER` — путь к бинарнику, с поддержкой `~`. Если задан неверно,
   команда завершается ошибкой, другой бинарник не подставляется.
2. `MachOMerger` (`MachOMerger.exe` на Windows) в текущем рабочем каталоге.
3. Бинарник в `PATH`.

Каталоги сборки и Python-пакета не проверяются. После сборки задай путь
через `COLDHOOK_MERGER` или добавь каталог бинарника в `PATH`.

```sh
COLDHOOK_MERGER=/opt/coldhook/MachOMerger python3 -m coldhook doctor
```

`doctor` проверяет LIEF, обнаружение файла мерджера и права исполнения. Он **не запускает мерджер**, не проверяет его ABI/версию
и не скачивает бинарники. Совместимость мерджера проверяется реальным запуском.
Для обработки Mach-O `lipo`/`otool` не нужны. Для сборки исходников и подписи
по-прежнему нужны соответствующие внешние инструменты.

Другие возможные причины ошибок Python-обвязки:

- Неверный путь: `patch` разрешает binary относительно конфига, `ipa` — внутри
  `.app`; sources/dylib/out в конфиге разрешаются относительно его каталога.
- Неверный TOML или тип поля: например, sources должен быть массивом строк.
- Недостаточные права, отсутствие свободного места, сбой копирования, временного
  каталога или записи результата.
- Повреждённый ZIP/IPA, отсутствие `.app` внутри архива или неверный входной файл.
- Не Mach-O, неподдерживаемая архитектура, зашифрованный слайс (`cryptid != 0`).
- Ошибка компиляции хука, неподходящий SDK/target или параметры линковки.
- Ошибка подписи: сертификат, entitlements, доступ к keychain.
- Для shared: отсутствующий runtime, неоднозначный selector или неверный путь
  загрузки хука. Успешный патч сам по себе не проверяет запуск приложения.


Тесты: [общий запуск через pytest](tests/README.md), отдельные группы для macOS и симулятора.
