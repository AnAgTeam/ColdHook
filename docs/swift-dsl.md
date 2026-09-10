# ColdHook Swift DSL

Для shared Swift основной API — аннотации `@ColdHookMangled` и
`@ColdHookOffset` из шаблона `iphone/coldhook_tweak_swift`. Пользователь пишет
обычную Swift-функцию с ABI цели; build-препроцессор удаляет аннотацию, назначает
внутренние linker names handler-а и `orig`, затем генерирует C/assembler glue.

## По mangled symbol

```swift
@ColdHookMangled(
    binary: "TestSwiftApp",
    target: "$s12TestSwiftApp3url3forS2S_tF"
)
public func url(for domain: String) -> String {
    if domain == "unknown" { return "https://fallback" }
    return orig_url(for: domain)
}
```

`target` задаётся без ведущего Mach-O-подчёркивания. Сигнатура replacement и
сгенерированного `orig_url` совпадает с ABI оригинальной Swift-функции, включая
Swift-типы, metadata и calling convention.

## По адресу

```swift
@ColdHookOffset(binary: "TestSwiftApp", offset: 0xb99a8)
public func fix(_ env: Int) -> String {
    env == 99 ? "patched" : orig_fix(env)
}
```

`offset` — исходный unslid vmaddr/offset выбранного Mach-O. `@ColdHookOffset`
использует тот же orig thunk, что и вариант по символу.

## Linker names

Пользователь не добавляет `@_silgen_name`. Препроцессор связывает handler с
внутренним именем и объявляет `orig_<имя функции>` на private orig alias/thunk.
Magic entry остаётся отдельным стабом `b handler`, одинаковым для by-name и
by-offset.

На каждый hook из dylib экспортируются только:

```text
_COLDHOOK_DYN_<kind>_<binary>__CH__<locator>__CH__<handler>
_COLDHOOK_ORIG_<kind>_<binary>__CH__<locator>__CH__<handler>
```

Handler, orig thunk, `orig_*` alias, gate и dispatch slot имеют private linkage.
Ручная связка Swift `@_silgen_name` с собственным C/Objective-C glue остаётся
низкоуровневым escape hatch без гарантии стабильности внутренних имён.

## Ограничения

- Replacement обязан точно сохранять Swift ABI цели.
- Автоматический путь принимает уже известное mangled name либо адрес; поиск по
  demangled имени пока не реализован.
- Виртуальные методы классов, witness/vtable dispatch и `@objc dynamic` требуют
  выбора правильного target thunk; для Objective-C обычно удобнее Logos.
- Chaining нескольких providers одного locator остаётся отдельным этапом.

Реализация препроцессора находится в
`coldhook/templates/coldhook-swift-shared/coldhook_swift_preprocess.py`;
регрессия `@ColdHookOffset` — в `tests/macos/run_swift_offset.py`.
