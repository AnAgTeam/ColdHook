# @@PROJECTNAME@@

Shared ColdHook Logos template. `%hookf_shared` is translated by the ColdHook prepass
to `CH_DYN_SYM`/`CH_DYN_ADDR` declarations with an explicit binary selector.

```bash
make
python3 -m coldhook shared My.app \
  --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib \
  --out My.patched.app
```

The merger is invoked for every Mach-O in the app; images whose selector does not match
are copied unchanged.
