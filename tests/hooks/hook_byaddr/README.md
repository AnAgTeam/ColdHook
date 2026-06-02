# hook_byaddr — хук ПО АДРЕСУ + ORIG (для стрипнутых целей)

Detour, когда у цели НЕТ символа (стрипнутый релиз). Цепляемся по **vmaddr** из дизассемблера.
Логика как у by-name: валидный путь -> **оригинал** (`CH_ORIG`), провальный -> фикс. Минус —
адрес плывёт при пересборке цели; если символ есть, предпочитай by-name (`../export_byname`).

Запускаемое доказательство этого пути (без устройства): `tests/macos/run_hookaddr.py`
(через макрос + оркестратор) и `tests/macos/run_offset.py` (сырой `_COLDHOOK_ADDR_<hex>`).

Файлы:
- `hook.c` — замена с прототипом цели + `CH_HOOK_ADDR(addr, fn)` (магик-символы по адресу).
- `ctor.c` — probe-конструктор (`syslog`), виден в Console по фильтру `coldhook`.

## Адрес — под свою цель

```bash
otool -tvV <binary> | less        # найди функцию, возьми её vmaddr (как в IDA/Hopper)
# или, если символ всё-таки есть:
nm <binary> | grep domain_for     # -> 0000000100004488 _domain_for
```
Подставь vmaddr в `CH_HOOK_ADDR(...)` в `hook.c`.

## Сборка (iOS arm64) + установка

```bash
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" \
  -I ../../../coldhook/include -dynamiclib hook.c ctor.c -o ch.dylib \
  -Xlinker -install_name -Xlinker @rpath/ch.dylib \
  -Xlinker -fixup_chains -Xlinker -add_split_seg_info

python3 ../../../scripts/build_install.py --hook "$PWD/ch.dylib"
```
