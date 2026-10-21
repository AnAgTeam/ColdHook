# @@PROJECTNAME@@

Shared ColdHook Logos template. `%hookf_shared` is translated by the ColdHook prepass
to `CH_DYN_SYM`/`CH_DYN_ADDR` declarations with an explicit binary selector. The
`coldhook_shared.h` ABI header is included by the template, while `coldhook.h` is
inserted automatically by the prepass.

This template assumes an existing Theos installation (`$THEOS`, including
`$THEOS/bin/logos.pl`) and an installed ColdHook Python package. From the ColdHook checkout,
run `python3 -m pip install -e .` so that `coldhook-logos` is on `PATH`; then run
`python3 -m coldhook install-theos`. The latter installs the template only; it does not
install Theos, Logos, or the Python package. The `coldhook-logos` prepass is then run
automatically by `make`.

The hook dylib must link the universal bootstrap runtime. Set its location before
building (the default is the generated project directory):

```bash
make COLDHOOK_RUNTIME_DIR=/path/to/runtime
```

The directory must contain `libcoldhook.tbd` (included in the template) or
`libcoldhook.dylib`. Headers and Objective-C support sources are copied into
the generated project; no path to the ColdHook checkout is embedded.

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
