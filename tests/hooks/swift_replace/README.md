# swift_replace — хук Swift-метода: by-name + ORIG (PoC, проверен на iPhone)

Хук чистого Swift-метода `url(for:) -> String` в `TestSwiftApp` (мишень №2,
`tests/TestSwiftApp/.../ContentView.swift`): в `default` он уходит в `preconditionFailure`
(краш по тапу). Хук для известного домена зовёт **оригинал** (`CH_ORIG`), а для остального
возвращает фолбэк — краша больше нет. `ctor.c` логирует факт загрузки в Console.

Почему так: Logos берёт только `@objc dynamic` Swift-методы (есть селектор, `String`↔`NSString`).
Чистый Swift зовётся по Swift-ABI напрямую — swizzlить нечего. ColdHook патчит статически.
Замена и оригинал — Swift-функции с тем же ABI через `@_silgen_name` (Swift `String` нельзя
вернуть из C/`@_cdecl` — это value-тип). Symtab реального Swift-бинаря SwiftMachO не парсит,
но мёрджер резолвит цель сырым разбором symtab — поэтому by-name работает.

Файлы:
- `hook.swift` — Swift-замена + объявление оригинала (`@_silgen_name`).
- `glue.c` — навешивает магик-символы: `CH_HOOK_SYM` (по имени, рекомендуется) или
  `CH_HOOK_ADDR` (по адресу). Генерит и ORIG-слот, и alias `_coldhook_orig_ch_url`.
- `ctor.c` — probe-конструктор (`syslog`), виден в Console по фильтру `coldhook`.

## Имя/адрес цели — под свою сборку

```bash
nm <app-binary> | grep -i url        # -> _$s12TestSwiftApp3url3forS2S_tF (мангл) и адрес
```
В `glue.c` подставь мангл (без ведущего `_`) в `CH_HOOK_SYM`, либо адрес в `CH_HOOK_ADDR`.

## Сборка (iOS arm64) + установка

```bash
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" \
  -I ../../../coldhook/include -c glue.c -o glue.o
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" -c ctor.c -o ctor.o
xcrun --sdk iphoneos swiftc -target arm64-apple-ios15.6 -sdk "$SDK" \
  -emit-library hook.swift glue.o ctor.o -o ch.dylib \
  -Xlinker -install_name -Xlinker @rpath/ch.dylib \
  -Xlinker -fixup_chains -Xlinker -add_split_seg_info

# собрать -> merge -> переподписать -> поставить (хук тянет Swift-рантайм -> --allow-new-dylibs
# внутри merge; build_install.py уже зовёт merge в append-режиме)
python3 ../../../scripts/build_install.py --hook "$PWD/ch.dylib"
```

Проверено end-to-end: устройство приняло пропатченный подписанный бандл, краш убран, в Console
строка `[coldhook]`. Запускаемый аналог без устройства (by-name + ORIG, с PC-relative прологом) —
`tests/macos/run_swift.py`.
