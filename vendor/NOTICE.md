# Vendored third-party code

## Dopamine

Каталог содержит код, первоначально импортированный из ветки `2.x`
проекта [Dopamine](https://github.com/opa334/Dopamine), ревизия
[`5e2733d3677975d5e81093b343a0de7f676aaf08`](https://github.com/opa334/Dopamine/commit/5e2733d3677975d5e81093b343a0de7f676aaf08):

- `vendor/MachOMerger/` — из `BaseBin/MachOMerger`; автор исходного движка
  слияния — Linus Henze;
- `vendor/dyldhook/` — из `BaseBin/dyldhook`, используется как референс макросов
  `HOOK()` и `ORIG()`.

Dopamine распространяется под лицензией MIT, Copyright (c) 2023–2024
Lars Fröder (opa334). Копия лицензии находится в `vendor/LICENSE-Dopamine.md`.
Оригинальные copyright-заголовки в исходниках сохранены.

## Форк MachOMerger в ColdHook

`vendor/MachOMerger/` — поддерживаемый форк, который существенно отличается от
исходников Dopamine. Изменения ColdHook затрагивают алгоритмы слияния,
обработку load commands, сегментов, символов, релокаций и chained fixups,
добавляют append- и shared-режимы, FAT Mach-O и кроссплатформенную сборку.

История Git является полным реестром локальных изменений. Комментарии `ColdHook:`
в отдельных участках кода объясняют конкретные решения, но не являются полным
списком отличий от upstream.

## SwiftPM-зависимости MachOMerger

Сборка MachOMerger использует [SwiftUtils](https://github.com/pinauten/SwiftUtils) и
[SwiftMachO](https://github.com/pinauten/SwiftMachO). Оба проекта распространяются под лицензией MIT:

- SwiftUtils — Copyright (c) 2021 Pinauten GmbH;
- SwiftMachO — Copyright (c) 2021/2022 Pinauten GmbH.

Их исходники не хранятся в `vendor/`: SwiftPM загружает их при сборке. Используемые
ревизии закреплены в `vendor/MachOMerger/Package.resolved`; полные тексты лицензий
находятся в их upstream-репозиториях.
