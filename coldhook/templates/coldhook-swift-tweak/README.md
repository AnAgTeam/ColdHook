# @@PROJECTNAME@@

Swift-твик на **ColdHook** — статический хук чистых Swift-методов через merge, без джейлбрейка и
W^X. Хукаешь по символу (мангл) или адресу; замена и оригинал — Swift-функции с тем же ABI.

## Поток

```
Hook.swift + glue.c  →  make  →  .theos/obj/.../@@PROJECTNAME@@.dylib  →  инжект в цель
```

Без пре-пасса и substrate-шима (это нужно только Logos-шаблону) — чистый swiftc + clang.

## Под свою цель

1. Найди символ цели и его сигнатуру:
   ```bash
   nm <target-binary> | grep <fn>        # -> _$s12YourModule6target...  (мангл)
   echo '$s12YourModule6target...' | swift demangle
   ```
2. В `Hook.swift` — задай ту же сигнатуру у `ch_hook`/`ch_orig` (через `@_silgen_name`).
3. В `glue.c` — вставь мангл (без ведущего `_`) в `CH_HOOK_SYM`, либо адрес в `CH_HOOK_ADDR`.

`%orig`-аналог — функция `ch_orig` (символ делает `CH_HOOK_SYM`). PC-relative пролог цели
(`cbz`/`adrp`/…) мёрджер переэнкодит под ORIG-слот сам.

## Сборка и инжект

```bash
make                                  # -> .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib

# инжект отдельным шагом (merge + переподпись). Хук тянет Swift-рантайм -> --allow-new-dylibs:
python3 -m coldhook merge --target <target-binary> \
    --src .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib --out <patched> --allow-new-dylibs
# или сразу собрать+merge+resign+поставить на устройство:
python3 <coldhook>/scripts/build_install.py --hook .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib
```

Готовый рабочий пример (проверен на устройстве) — `tests/hooks/swift_replace`; запускаемый на
macOS прогон (by-name + ORIG) — `tests/macos/run_swift.py`.
