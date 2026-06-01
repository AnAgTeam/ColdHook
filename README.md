# ColdHook

Статический «холодный» хук iOS-бинарей через **слияние** хук-кода в таргет (на базе
MachOMerger), без рантайм-кодогенерации и W^X-переходов. Хуки — **по символам**
(`HOOK(name)`/`ORIG(name)`) и **по оффсету** (`COLDHOOK_ADDR_<hex>` для стрипнутых
бинарей), без интеграции Logos. Подробный план — `coldhook_plan.md`.

## Структура

```
vendor/MachOMerger/   форк движка слияния (Dopamine 2.x, MIT) + правки ColdHook
vendor/dyldhook/      референс макросов HOOK()/ORIG()
harness/macos/        локальные macOS-харнессы (arm64) — dev-полигоны без устройства
coldhook/             Python-оркестратор (info | merge | patch | ipa)
```

## Локальные харнессы (macOS arm64, без устройства)

```bash
# сборка движка (один раз)
cd vendor/MachOMerger && swift build -c release && cd -

python3 harness/macos/run.py           # merge + Replace + ORIG + импорты A/B (dylib)
python3 harness/macos/run_offset.py    # хук по сырому оффсету (магик-символ вручную)
python3 harness/macos/run_hookaddr.py  # by-offset через макрос HOOK_ADDR + coldhook merge
python3 harness/macos/run_fat.py       # FAT (arm64+x86_64): патч arm64, x86_64 как есть
python3 harness/macos/run_newdylib.py  # хук тянет свой dylib (libz) -> --allow-new-dylibs
python3 harness/macos/run_app.py       # полный .app: собрать -> coldhook ipa -> запустить
```

### Хуки по оффсету в коде (`HOOK_ADDR`)

Для стрипнутых бинарей — обычная функция + `HOOK_ADDR(offset, fn)` (из `<coldhook.h>`);
оффсет = оригинальный vmaddr цели (как в IDA). Магик-символы/ORIG-трамплины генерит макрос.

```c
#include <coldhook.h>
COLDHOOK_ORIG(fix_domain, const char *, int);
const char *fix_domain(int env) {
    if (env == 99) return "https://fallback";   // чиним провал
    return ORIG(fix_domain)(env);                // остальное -> в оригинал
}
HOOK_ADDR(0xb99a8, fix_domain);
```

Конфиг для такого таргета — просто `binary` + `sources` (оффсеты живут в коде). Строка-модуль
`HOOK_ADDR("Bin", off, fn)` зарезервирована под будущий shared-режим (одна либа на много бинарей).

Паттерн цели: `domain_for(env)` отдаёт домен для известного окружения, иначе падает
в `__builtin_trap()` (модель `assertionFailure`). Хук чинит провальный путь, известное
делегирует оригиналу через `ORIG`.

## Оркестратор (Python)

Интроспекция Mach-O → сборка хука под платформу таргета → merge → (опц.) resign.

```bash
python3 -m coldhook info   <binary>
python3 -m coldhook merge  --target <binary> --src hook.c --src orig_stubs.S --out <out>
python3 -m coldhook patch  -c coldhook.toml                    # пачкой, отдельные бинари
python3 -m coldhook ipa    <in.ipa|.app> -c cfg -o <out>       # merge в бандл in-place
```

Конфиг (`coldhook.toml`) — список `[[target]]` (binary → sources|dylib) + `[signing]`.
Проверяет арку/платформу/cryptid; FAT — патчит arm64/arm64e-слайсы, остальные оставляет.

Импорты хука B: новые символы из dylib, которые таргет **уже линкует**, дозаписываются
автоматически. Если хуку нужен dylib, которого в таргете НЕТ — по умолчанию ошибка;
`allow_new_dylibs = true` (в `[[target]]`) или `--allow-new-dylibs` (в `merge`) разрешает
дописать `LC_LOAD_DYLIB`. Доп. флаги линковки хука — `ldflags = ["-lz"]` / `--ldflags`.

**Подпись**: `merge`/`patch` подписывают (codesign/ldid), `ipa` — НЕТ по умолчанию
(`--sign-bundle` включает). iOS-установка требует подписи отдельно.

## Статус

- [x] M1: parse + merge + Replace-хук по символу + codesign + загрузка (локально, macOS)
- [x] Merge импортов таргета A (Step 1) + внешних импортов B (Step 2), dual-format (arm64 2/6, arm64e 1/12)
- [x] Detour-режим (`ORIG`/возврат в оригинал, single-instruction трамплин)
- [x] Хук по оффсету: магик-символ `COLDHOOK_ADDR_<hex>` + макрос `HOOK_ADDR(off, fn)` в коде
- [x] Python-оркестратор: `info | merge | patch`
- [x] Патч бандла `ipa` (.ipa/.app, merge in-place, без подписи) + macOS .app полигон
- [ ] Подпись бандла под TrollStore/dev-серт (resign .app, порядок вложенности)
- [x] FAT-слайсинг (патч arm64/arm64e-слайсов, неподдерживаемые — как есть, сборка lipo)
- [x] Свои dylib у B (`--allow-new-dylibs`: вставка LC_LOAD_DYLIB + ремап dylib-ordinals)
- [ ] exports trie / multi-chain / MH_EXECUTE base / многоинструкционный ORIG (PC-relative пролог)

## Лицензии

Завендоренный код — MIT (Dopamine, © opa334). См. `vendor/LICENSE-Dopamine.md` и `vendor/NOTICE.md`.
