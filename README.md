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

## Статус

- [x] M1: parse + merge + Replace-хук по символу + codesign + загрузка (локально, macOS)
- [ ] Merge импортов таргета A (см. `vendor/MachOMerger` — главный блокер для боевых бинарей)
- [ ] Detour-режим (`ORIG`/возврат в оригинал)
- [ ] Python-оркестратор + IPA in/out + resign под TrollStore/dev-серт

## Лицензии

Завендоренный код — MIT (Dopamine, © opa334). См. `vendor/LICENSE-Dopamine.md` и `vendor/NOTICE.md`.
