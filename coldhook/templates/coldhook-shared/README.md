# @@PROJECTNAME@@

Shared ColdHook Logos template. `%hookf_shared` is translated by the ColdHook prepass
to `CH_DYN_SYM`/`CH_DYN_ADDR` declarations with an explicit binary selector. The
`coldhook_shared.h` ABI header is included by the template, while `coldhook.h` is
inserted automatically by the prepass.

This template assumes an existing Theos installation (`$THEOS`, including
`$THEOS/bin/logos.pl`). `coldhook install-theos` installs the template only; it does not
install Theos or Logos. The `coldhook-logos` prepass is supplied by the ColdHook Python
package and is run automatically by `make`.

The hook dylib must link the universal bootstrap runtime. Set its location before
building (the default is `/usr/local/lib`):

```bash
make COLDHOOK_RUNTIME_DIR=/path/to/runtime
```

The directory must contain `libcoldhook.dylib`.

Supported forms:

```logos
%hookf_shared("Binary", ret, symbol, args...) { ... }
%hookf_shared("Binary", ret, 0x1234, args...) { ... }
```

`%orig` is available through the generated `coldhook_orig_*` trampoline. A shared
hook inside `%group` is converted to the gated dynamic form and is enabled by the
usual `%init(Group)`.

```bash
make
python3 -m coldhook shared My.app \
  --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib \
  --out My.patched.app
```

The merger is invoked for every Mach-O in the app; images whose selector does not match
are copied unchanged.
