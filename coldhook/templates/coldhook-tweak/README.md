# @@PROJECTNAME@@

Твик на **Logos с бэкендом ColdHook** — статический хук через merge, без джейлбрейка и W^X.
Пишешь обычный Logos-твик, собираешь `make`, инжектишь отдельным шагом.

## Поток

```
Tweak.x  →  make  →  .theos/obj/.../@@PROJECTNAME@@.dylib  →  инжект в цель
            (ColdHook-пре-пасс: %hookf -> статика; logos -> остальное)
```

`make` внутри: пре-пасс переводит `%hookf` в статический glue (`.coldhook/Tweak.xm`), theos
гонит logos на `.xm` и компилит. Ты правишь только `Tweak.x`.

## Что едет как

| Конструкт | Бэкенд |
|---|---|
| `%hookf` (C-функция) | **статика ColdHook** — патч на merge, без MSHookFunction/W^X |
| `%hookf` в `%group` | **gated** — установлен статически, включается рантаймом на `%init(Group)` |
| `%ctor` / `%orig` | как обычно (конструктор сливается через `__init_offsets`) |
| ObjC `%hook` | компилится, но через merge ПОКА не активируется (приедет с shared-режимом) |

## Сборка и инжект

```bash
make                                  # -> .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib

# инжект в цель отдельным шагом (merge + переподпись):
python3 -m coldhook merge --target <target-binary> \
    --src <этот dylib> --out <patched>
# или сразу собрать+merge+resign+поставить на устройство:
python3 <coldhook>/scripts/build_install.py --hook .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib
```

Цель `%hookf` задаётся ИМЕНЕМ символа (как в `nm <target> | grep <fn>`, без ведущего `_`).
```
