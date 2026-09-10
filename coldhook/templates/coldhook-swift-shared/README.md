# @@PROJECTNAME@@

Shared Swift ColdHook template. Annotate a replacement with `@ColdHookMangled`
or `@ColdHookOffset`. The build preprocessor creates the C glue, private handler
and orig linker names; do not add `@_silgen_name` manually.

The project ships `libcoldhook.tbd`, so the real `libcoldhook.dylib` is not needed
while linking. It is required at runtime. Build and apply with:

```bash
make
python3 -m coldhook shared My.app \
  --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib \
  --out My.patched.app
```

For `@ColdHookMangled`, use the target's mangled Swift symbol without its leading
underscore. Call the generated `orig_<function-name>` declaration when the
replacement needs the original implementation.
