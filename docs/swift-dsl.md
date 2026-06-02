# ColdHook Swift DSL — идея (набросок)

Цель: писать хуки чистых Swift-методов так же привычно, как Logos для ObjC. Движок уже умеет
by-name / by-offset / ORIG (см. `tests/macos/run_swift.py`, `tests/hooks/swift_replace`); это —
дизайн **эргономичной обёртки** поверх него. Не реализация, а план.

## Принципы именования (по Swift API Design Guidelines)

- Без префиксов в стиле ObjC (`NS`/`UI`). Неймспейс даёт **модуль**: `import ColdHook`.
- Макрос — `@Hook` (а не `@CTHook`: `CT`-префикс не по канону). Квалифицируется модулем при
  конфликте: `ColdHook.Hook`.
- Группировка не-макро API — **caseless enum** `enum ColdHook { ... }`, не класс.
- `orig` — вызов оригинала (привычно по `%orig` Logos / `orig` Orion).
- Строка-цель = **демангленое имя** Swift (`Mod.Type.method(label:)`), как разработчик читает вызов.

## Как выглядит

Базовый случай (free / `final` / struct-функция — движок уже тянет):
```swift
import ColdHook

@Hook("TestSwiftApp.url(for:)")
func url(for domain: String) -> String {
    guard domain == "application" else { return "https://fallback" }
    return orig(domain)                  // оригинал
}
```

По адресу (стрипнутый бинарь без символов):
```swift
@Hook(address: 0xb99a8)
func fix(_ env: Int) -> String { env == 99 ? "patched" : orig(env) }
```

Метод класса (Orion-подобно, с `self`) — поздняя стадия:
```swift
@HookClass(MyViewModel.self)
final class MyHooks {
    @Hook("load(_:)")
    func load(_ n: Int) -> String { orig(n) + "!" }
}
```

## Как работает

ColdHook — **статика на этапе merge**, не рантайм-swizzle. Макрос не ходит в файлы при
раскрытии, поэтому эмитит *намерение*, а резолв — в мёрджере.

```
1. @Hook (compile-time) раскрывается в:
   - impl-функцию с фиксированным символом   (@_silgen_name "_ch_<id>")
   - orig — обёртку на ORIG-слот              (@_silgen_name "_coldhook_orig_<id>")
   - ДЕСКРИПТОР в секции __DATA_CONST,__coldhook:
       { target: "TestSwiftApp.url(for:)",  hook: &impl,  origSlot: &slot }

2. merge-time (мёрджер читает __coldhook):
   для каждого дескриптора:
   - target "0x..."    -> адрес напрямую
   - target "Mod.f()"  -> резолв по symtab ЦЕЛИ: демangling всех символов, матч по
                          читаемому имени (+ сигнатура для перегрузок) -> адрес
   - ПАТЧ: первая инструкция цели -> b hook; сохранить её (переэнкод если PC-relative)
           в origSlot + b цель+4
```

Под капотом — те же магик-символы `_MACHOMERGER_HOOK_/ORIG_/HOOKTRAMPOLINE_` + ORIG-слот, что
сейчас генерит `CH_HOOK_SYM`/`CH_HOOK_ADDR`. Разница в том, что цель задаётся ЧИТАЕМОЙ строкой,
а соответствие «строка → `$s`-символ» ищется в symtab цели (сырой парсер, SwiftMachO-независимый).

## Что переиспользуется / что новое

| Уже есть | Новое для @Hook |
|---|---|
| магик-символы HOOK/ORIG/HOOKTRAMPOLINE, ORIG-слот | Swift-макрос (5.9+), генерящий glue |
| переэнкод PC-relative первой инструкции (ORIG) | секция-дескрипторов `__coldhook` вместо ручных символов |
| by-offset / by-name; сырой разбор symtab | резолвер «читаемое имя → `$s`-символ» (демangling-матч, перегрузки) |
| free / `final` / struct — полностью | `self`-ABI + thunk/vtable для **методов** класса |

## Открытые вопросы

- **Резолвер имени** — отдельный, разблокирует и `@Hook`, и Logos-мост. Демangling символов
  цели (`nm | swift demangle`-эквивалент в оркестраторе) + матч по `Type.method(labels:)`,
  снятие неоднозначности перегрузок по типам аргументов.
- **Методы класса**: `self` приходит доп. параметром (для класса — указатель в контекст-регистре);
  виртуальные вызовы идут через vtable/`Tj`-thunk, протокольные — через witness `TW`. Чтобы
  ловить ВСЕ вызовы не-`final` метода, патчить надо thunk/запись vtable, а не только тело.
- **`@objc dynamic`** методы и так берёт Logos/Orion (через селектор/`NSString`). Уникальная
  ниша ColdHook — чистый Swift; для демо @Hook брать не-`@objc` цель.
- **Дескрипторная секция vs символы**: дескриптор в `__coldhook` чище ручных магик-символов и
  естественно покрывает и by-name, и by-offset. Решить формат записи (строки в `__cstring`).

## Связанные сущности (уже в репо)

- `coldhook/include/coldhook.h` — `CH_HOOK_ADDR` (by-offset), `CH_HOOK_SYM` (by-name), `CH_ORIG`.
- `tests/macos/run_swift.py` — by-name + ORIG, запускаемый на macOS.
- `tests/hooks/swift_replace` — сэмпл (by-name + ORIG) на TestSwiftApp, проверен на устройстве.
- Резолв символов — сырой `coldhookParseSymtab` в `vendor/MachOMerger/Sources/MachOMerger/main.swift`.
