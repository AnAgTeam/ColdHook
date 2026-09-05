# @@PROJECTNAME@@

Shared Swift ColdHook template. `Hook.swift` contains the Swift replacement and
`glue.c` emits `CH_DYN_SYM` (or `CH_DYN_ADDR`) metadata for the selected binary.

The project ships `libcoldhook.tbd`, so the real `libcoldhook.dylib` is not needed
while linking. It is required at runtime. Build and apply with:

```bash
make
python3 -m coldhook shared My.app \
  --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib \
  --out My.patched.app
```

Use the target's mangled Swift symbol without its leading underscore in `CH_DYN_SYM`.
