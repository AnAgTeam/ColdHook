# Vendored third-party code

Этот каталог содержит код из проекта **Dopamine** (https://github.com/opa334/Dopamine,
ветка `2.x`), распространяемого под лицензией **MIT** (глобальный `LICENSE.md` репозитория,
© 2023–2024 Lars Fröder / opa334). Копия лицензии — `vendor/LICENSE-Dopamine.md`.

## Что завендорено

- `vendor/MachOMerger/` — из `BaseBin/MachOMerger`. Автор движка слияния — Linus Henze.
- `vendor/dyldhook/`    — из `BaseBin/dyldhook` (референс использования макросов `HOOK()`/`ORIG()`).

## Локальные модификации MachOMerger (ColdHook)

Изменения внесены в `vendor/MachOMerger/Sources/MachOMerger/`, помечены комментариями `ColdHook:`:

- `main.swift` — `hdr.filetype = a.filetype.rawValue` вместо хардкода `MH_DYLINKER`
  (иначе dyld не грузит результат как dylib);
- `main.swift` — сохранение `LC_LOAD_DYLIB` целевого бинаря (иначе «missing LC_LOAD_DYLIB»);
- `SegmentLoadCommand.swift` — выставление флага `SG_READ_ONLY` на `__DATA_CONST`/`__AUTH_CONST`
  (иначе «__DATA_CONST segment missing SG_READ_ONLY flag» при загрузке).

Оригинальные copyright-заголовки в исходниках сохранены.
