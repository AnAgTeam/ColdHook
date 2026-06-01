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

python3 harness/macos/run.py         # merge + Replace + ORIG + импорты A/B (dylib)
python3 harness/macos/run_offset.py  # хук по сырому оффсету (без символа)
python3 harness/macos/run_app.py     # полный .app: собрать -> coldhook ipa -> запустить
```

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
Проверяет арку/платформу/cryptid, отказывается от FAT и зашифрованных бинарей.

**Подпись**: `merge`/`patch` подписывают (codesign/ldid), `ipa` — НЕТ по умолчанию
(`--sign-bundle` включает). iOS-установка требует подписи отдельно.

## Статус

- [x] M1: parse + merge + Replace-хук по символу + codesign + загрузка (локально, macOS)
- [x] Merge импортов таргета A (Step 1) + внешних импортов B (Step 2), dual-format (arm64 2/6, arm64e 1/12)
- [x] Detour-режим (`ORIG`/возврат в оригинал, single-instruction трамплин)
- [x] Хук по оффсету (`COLDHOOK_ADDR_<hex>`, для стрипнутых бинарей)
- [x] Python-оркестратор: `info | merge | patch`
- [x] Патч бандла `ipa` (.ipa/.app, merge in-place, без подписи) + macOS .app полигон
- [ ] Подпись бандла под TrollStore/dev-серт (resign .app, порядок вложенности)
- [ ] Дыра 2c (импорт B из dylib, которого нет в таргете) / exports trie / multi-chain / FAT-слайсинг / MH_EXECUTE base

## Лицензии

Завендоренный код — MIT (Dopamine, © opa334). См. `vendor/LICENSE-Dopamine.md` и `vendor/NOTICE.md`.
