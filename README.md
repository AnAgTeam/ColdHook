# ColdHook

Статический «холодный» хук iOS-бинарей через **слияние** хук-кода в таргет (на базе
MachOMerger), без рантайм-кодогенерации и W^X-переходов. Хуки — по символам
(`HOOK(name)`/`ORIG(name)`), без интеграции Logos. Подробный план — `coldhook_plan.md`.

## Структура

```
vendor/MachOMerger/   форк движка слияния (Dopamine 2.x, MIT) + правки ColdHook
vendor/dyldhook/      референс макросов HOOK()/ORIG()
harness/macos/        локальный macOS-харнесс (arm64) — dev-полигон без устройства
coldhook/             Python-оркестратор (compile → merge → resign → repack) [WIP]
```

## Локальный харнесс (M1, Replace)

Доказывает merge-путь end-to-end на macOS arm64 без iOS-устройства:
target.dylib + hook.dylib → merge → codesign → driver dlopen.

```bash
# сборка движка (один раз)
cd vendor/MachOMerger && swift build -c release && cd -
# прогон харнесса
python3 harness/macos/run.py
```

Ожидаемо: без хука `domain_for(99)` падает в `__builtin_trap()` (SIGTRAP), с хуком —
возвращает валидный домен.

## Оркестратор (Python)

Конфиг-движок: интроспекция Mach-O → сборка хука под платформу таргета → merge → resign.

```bash
# одиночный бинарь
python3 -m coldhook info   <binary>
python3 -m coldhook merge  --target <binary> --src hook.c --src orig_stubs.S --out <out> --sign -

# пачкой по конфигу (маппинг разных таргетов на свои хуки)
python3 -m coldhook patch  -c coldhook.toml
```

Конфиг (`coldhook.toml`) — список `[[target]]` (binary → sources|dylib) + `[signing]`.
Проверяет арку/платформу/cryptid, отказывается от FAT и зашифрованных бинарей.

## Статус

- [x] M1: parse + merge + Replace-хук по символу + codesign + загрузка (локально, macOS)
- [x] Merge импортов таргета A (Step 1) + внешних импортов B (Step 2), dual-format (arm64 2/6, arm64e 1/12)
- [x] Detour-режим (`ORIG`/возврат в оригинал, single-instruction трамплин)
- [x] Python-оркестратор: конфиг + merge + resign (`coldhook info|merge|patch`)
- [ ] Патч бинарников из IPA (распаковка/запаковка/resign .app)
- [ ] Дыра 2c (импорт B из dylib, которого нет в таргете) / exports trie / multi-chain

## Лицензии

Завендоренный код — MIT (Dopamine, © opa334). См. `vendor/LICENSE-Dopamine.md` и `vendor/NOTICE.md`.
