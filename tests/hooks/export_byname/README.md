# export_byname — хук экспортированной функции ПО ИМЕНИ + ORIG

Detour функции, у которой есть символ в symtab цели (экспорт библиотеки или просто не-static
функция бинаря). Цепляемся по **имени символа** — не по адресу, поэтому хук не ломается при
пересборке цели. Здесь цель — `domain_for(int) -> const char *`; провальный путь чиним, валидный
уводим в **оригинал** (`CH_ORIG`).

Запускаемое доказательство этого пути (без устройства): `tests/macos/run_export.py` — собирает
dylib с экспортом, мёрджит хук, линкует exe, проверяет ORIG (cbz берётся/нет) и фикс.

Файлы:
- `hook.c` — замена с тем же прототипом + объявление оригинала; `CH_HOOK_SYM` навешивает
  магик-символы (HOOK + ORIG-слот + alias `_coldhook_orig_domain_fix`).
- `ctor.c` — probe-конструктор (`syslog`), виден в Console по фильтру `coldhook`.

## Имя символа — под свою цель

```bash
nm <binary> | grep domain_for        # -> _domain_for (и адрес)
```
В `hook.c` в `CH_HOOK_SYM` подставь имя **без ведущего `_`** (`_domain_for` -> `"domain_for"`).
Если у функции символа нет (стрипнут) — цепляйся по адресу: см. `../hook_byaddr`.

## Сборка (iOS arm64) + установка

```bash
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun --sdk iphoneos clang -arch arm64 -target arm64-apple-ios15.6 -isysroot "$SDK" \
  -I ../../../coldhook/include -dynamiclib hook.c ctor.c -o ch.dylib \
  -Xlinker -install_name -Xlinker @rpath/ch.dylib \
  -Xlinker -fixup_chains -Xlinker -add_split_seg_info

# собрать -> merge (append) -> переподписать -> поставить
python3 ../../../scripts/build_install.py --hook "$PWD/ch.dylib"
```
