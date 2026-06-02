# swift_replace — хук Swift-функции по оффсету (PoC, проверен на iPhone)

Замена Swift-метода `url(for:) -> String` в `TestSwiftApp` (мишень №2, см.
`tests/TestSwiftApp/.../ContentView.swift`): в `default` она уходит в
`preconditionFailure` (краш по тапу). Хук уводит цель в Swift-замену с тем же ABI,
краш исчезает, вместо него возвращается строка. `ctor.c` логирует факт загрузки.

Почему так: Swift `(String) -> String` нельзя выразить C-функцией (`@_cdecl` не умеет
Swift String). Поэтому замена — Swift-функция с тем же ABI + фиксированный символ через
`@_silgen_name`, а магик-символ ColdHook по оффсету (`_COLDHOOK_ADDR_<hex>`) — асм-стаб,
тейл-ветвящийся в неё. Symtab реального Swift-бинаря SwiftMachO не парсит, поэтому хук
именно ПО ОФФСЕТУ (магик-адрес), а не по имени символа.

## Сборка (iOS arm64)

```bash
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" -c stub.s -o stub.o
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" -c ctor.c -o ctor.o
xcrun --sdk iphoneos swiftc -target arm64-apple-ios15.6 -sdk "$SDK" \
  -emit-library hook.swift stub.o ctor.o -o ch.dylib \
  -Xlinker -install_name -Xlinker @rpath/ch.dylib \
  -Xlinker -fixup_chains -Xlinker -add_split_seg_info
```

## Оффсет цели — найти под свою сборку

`stub.s` зашит на `0x100004298` (vmaddr `url(for:)` в конкретной сборке). Для своей:

```bash
nm -n <app-binary> | grep -i url      # -> 0x1000xxxxx у нужной функции
```

и заменить суффикс символа в `stub.s` на этот hex без `0x`.

## Merge + установка на устройство

```bash
# merge (append-режим: таргет без split-info; Swift-рантайм хука -> --allow-new-dylibs)
vendor/MachOMerger/.build/release/MachOMerger <app>/TestSwiftApp ch.dylib out --allow-new-dylibs
# либо одной командой: собрать -> merge -> переподписать -> поставить
python3 scripts/build_install.py --hook /path/to/ch.dylib
```

Проверено end-to-end: устройство приняло пропатченный подписанный бандл, тап по кнопке
не крашит и показывает `https://patched.coldhook`, в Console.app — строка `[coldhook]`.
