# ColdHook

ColdHook statically patches Mach-O binaries for iOS and macOS by merging hook code into the target at build time. It is designed for sideloaded apps, where jailbreak-style runtime patching is unavailable.

Русская версия: [README.ru.md](README.ru.md).

## Why

On a non-jailbroken sideloaded app, runtime code patching such as `MSHookFunction` (`%hookf`) is generally unavailable, while Objective-C message swizzling may still work. ColdHook applies hooks statically during the build, including hooks for Swift functions that are normally statically dispatched.

### How it compares

| Solution | Jailbreak required | Works with sideloading | Native Swift hooks | Works at runtime? | Source code required |
|---|:---:|:---:|:---:|:---:|:---:|
| **ColdHook** | No | Yes | Yes | No | No |
| Frida Gadget | No* | Yes | Yes, with a debugger/JIT or jailbreak | Yes* | No |
| ElleKit / Substrate | Usually | Limited | Yes, with a debugger/JIT or jailbreak | Yes | No |
| Objective-C swizzling | No | Yes | Only `@objc` methods | Yes | No |
| SwiftHook | No | Own app only | ObjC-visible Swift methods only | Yes | Yes |

`*` Frida's `Interceptor` has restrictions on jailed iOS when no debugger is attached. The table describes typical use; exact compatibility depends on the iOS version, signing method, symbols, and ABI.

SwiftHook is a library linked into the app itself. It changes dispatch for methods exposed to the Objective-C runtime (for example, `@objc dynamic` methods); it is not an injector for arbitrary native Swift functions in an already-built IPA.

**ColdHook's advantage:** it can replace native Swift functions in a sideloaded bundle without a jailbreak, attached debugger, or runtime JIT. **Trade-off:** hooks are chosen and applied before installation; they cannot be attached, detached, or changed while the app is running. Updating the target app normally requires rebuilding, patching, and re-signing the bundle again.

Supported features:

- symbol hooks (`CH_HOOK_SYM`);
- address/offset hooks (`CH_HOOK_ADDR`) for stripped binaries;
- `ORIG` calls to the original implementation;
- shared mode: one hook dylib for an app and its frameworks;
- Logos `%hookf`, `%ctor`, `%group`, and Objective-C swizzling;
- Swift hooks by mangled name or address;
- FAT Mach-O files with arm64/arm64e slice handling in `merge`/`patch`;
- patching `.app` and `.ipa` bundles, followed by re-signing.

The segment layout, shared-mode tables, bootstrap, relocations, and Mach-O limitations are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

### Option 1: release artifacts

Download these artifacts from a GitHub release:

- the macOS `MachOMerger` binary;
- the ColdHook Python package/CLI;
- `libcoldhook.dylib` for shared mode.

Put `MachOMerger` in `vendor/MachOMerger/.build/release/`, or set the project environment variables to point to it. No local Swift build is required afterwards.

### Option 2: build from source

Build MachOMerger:

```bash
cd vendor/MachOMerger
swift build -c release
cd ../..
```

Install the Python package from the checkout root:

```bash
python3 -m pip install -e .
```

For Theos templates, run:

```bash
python3 -m coldhook install-theos
```

This installs only the ColdHook NIC templates into an existing `$THEOS`; it does not install Theos or `logos.pl`. Building the templates requires Python with ColdHook installed, Theos (including `logos.pl`, makefiles, and clang/Swift toolchains), and Xcode/Swift on macOS.

### Windows

`coldhook shared` is supported on Windows for already-built **thin Mach-O** files. You need the ColdHook Python package (with cross-platform `lief`), `MachOMerger.exe`, a built `userhooks.dylib`, and `libcoldhook.dylib`. `coldhook shared` does not require `coldhook.toml`: selectors are read from the hook dylib export trie, and `.app`/`.ipa` bundles are unpacked and repacked with Python's built-in `zipfile`.

Windows limitations: shared mode does not perform FAT slicing automatically; configuration-based `patch`/`ipa` and FAT handling require Apple's `lipo`/`otool`, while building hook code remains a macOS/Theos/Xcode task. Re-sign the bundle on Windows with the sideload tool appropriate for your workflow.

## Usage

Single merge:

```bash
python3 -m coldhook merge \
  --target Target.app/Target \
  --dylib .theos/obj/debug/arm64/MyTweak.dylib \
  --out Target.patched
```

Patch an IPA/app from a config:

```bash
python3 -m coldhook ipa input.ipa \
  --config coldhook.toml \
  --out output.ipa
```

Shared mode:

```bash
python3 -m coldhook shared input.ipa \
  --dylib MyHooks.dylib \
  --runtime libcoldhook.dylib \
  --out output.ipa \
  --verbose
```

Use `--skip-unsupported` for test bundles containing unsupported auxiliary Mach-O files. `shared` expects thin Mach-O files and does not perform FAT slicing automatically.

IPA signing is disabled by default. With `--sign-bundle`, processed target binaries are signed; added shared hook/runtime dylibs must be signed separately before signing the app using the method required by your sideload tool.

## C/Objective-C API

```c
#include <coldhook.h>

CH_DECLARE_ORIG(domain_for, const char *, int);

const char *my_domain_for(int env) {
    if (env == 99) return "https://fallback";
    return CH_ORIG(domain_for)(env);
}

CH_HOOK_SYM("domain_for", my_domain_for);
```

For a stripped function, use an address/offset:

```c
CH_DECLARE_ORIG(fix_domain, const char *, int);
const char *fix_domain(int env) {
    return env == 99 ? "https://fallback" : CH_ORIG(fix_domain)(env);
}
CH_HOOK_ADDR(0xb99a8, fix_domain);
```

Gated hooks call the original by default and can be enabled from a constructor:

```c
CH_DECLARE_GATE(fix_domain);
CH_HOOK_SYM_GATED("domain_for", fix_domain);

__attribute__((constructor)) static void init(void) {
    if (setting_enabled()) CH_GATE_ENABLE(fix_domain);
}
```

## Logos

Install the templates:

```bash
python3 -m coldhook install-theos
$THEOS/bin/nic.pl
```

Choose `iphone/coldhook_tweak` for Logos/Objective-C or `iphone/coldhook_tweak_swift` for Swift. Normal Theos `make` and `make package` commands remain unchanged.

Logos requires an existing Theos installation with `$THEOS/bin/logos.pl`. ColdHook's Python prepass translates `%hookf`/`%hookf_shared` into static declarations; the standard `logos.pl` handles the remaining `%hook`, `%ctor`, and `%group` directives. The prepass is included in the Python package as `coldhook-logos`.

The Swift template includes `coldhook_swift_preprocess.py`; `make` runs it automatically, generates glue, and lets Theos compile the Swift code with the normal Swift compiler. No separate Swift macro toolchain is required.

Example:

```logos
%hookf(const char *, domain_for, int env) {
    if (env == 99) return "https://fallback";
    return %orig;
}

%ctor {
    NSLog(@"ColdHook loaded");
}
```

Shared mode:

```logos
%hookf_shared("TestSwiftApp", const char *, domain_for, int env) {
    return "patched domain";
}
```

## Swift

The replacement must preserve the original ABI. Specify the binary and mangled
target; the build preprocessor generates the private linker names and orig thunk:

```swift
@ColdHookMangled(
    binary: "TestSwiftApp",
    target: "$s12TestSwiftApp3url3forS2S_tF"
)
public func url(for domain: String) -> String {
    if domain == "unknown" { return "patched" }
    return orig_url(for: domain)
}
```

Do not add `@_silgen_name` yourself. Manual Swift/C glue remains an expert
low-level escape hatch whose internal names are not stable API.

Use `install-theos` and select `iphone/coldhook_tweak_swift`; glue and export declarations are generated automatically.

## Test app

`tests/TestSwiftApp` is a SwiftUI app with a separate `TestFramework`. The repository includes an end-to-end iOS Simulator runner:

```bash
python3 tests/simulator/run_shared.py \
  --udid <SIMULATOR_UDID>
```

It builds the app, creates the shared hook dylib and runtime, patches the main binary and framework, installs the bundle in the simulator, and runs a UI test covering app and framework Swift hooks.

Local macOS fixtures are in `tests/macos/`; C/Swift examples are in `tests/hooks/`.

## License

ColdHook is released under the MIT license. Licenses for vendored components are in `vendor/`.


## Python CLI diagnostics

Python 3.11+ and LIEF >=0.17 are required. Run `python3 -m coldhook doctor`
to check LIEF, merger discovery/executable permissions, and `lipo`/`otool`.
This checks the merger file, not its runtime compatibility or version.
Compilation additionally needs `xcrun` and a suitable SDK; signing needs
`codesign` or `ldid`. Apple tools are still required for Mach-O inspection.

Use `python3 -m coldhook --log-file coldhook.log patch -c coldhook.toml`
for a detailed appended diagnostic log, or `--debug` for console tracebacks.
Both flags go before the subcommand. Errors include stages, paths, and failed
command output. Processing commands check LIEF before work begins.

Merger search order: explicit `COLDHOOK_MERGER` path (supports `~`), current
working directory, `PATH`, bundled `bin/`, package directory, then the legacy
`vendor/MachOMerger/.build/release/` build. An invalid explicit environment
path fails without fallback. The filename is `MachOMerger.exe` on Windows.
No source checkout is needed when supplying a binary; no download is performed.

See [the Russian diagnostics notes](README.ru.md#диагностика-python-cli) for
common configuration, filesystem, archive, architecture, SDK, and signing errors.


Tests: see [tests/README.md](tests/README.md) for the unified pytest runner, macOS and simulator options.
