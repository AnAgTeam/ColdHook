// Shared Swift hook. Keep the ABI identical to the target function. The build
// preprocessor supplies private linker names; do not add @_silgen_name manually.
import Foundation

// @ColdHookMangled(binary: "TestSwiftApp", target: "$s12TestSwiftApp3url3forS2S_tF")

public func coldhook_handler_1(_ arg: String) -> String {
    if arg == "trigger" { return "patched by @@PROJECTNAME@@" }
    return orig_coldhook_handler_1(arg)
}
