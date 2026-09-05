// Shared Swift hook. Keep the ABI identical to the target function.
// Replace the @_silgen_name values and signature with your target's ABI.
import Foundation

// @ColdHookMangled(binary: "TestSwiftApp", target: "$s12TestSwiftApp3url3forS2S_tF")

@_silgen_name("coldhook_orig_1")
func ch_orig(_ arg: String) -> String

@_silgen_name("coldhook_handler_1")
public func coldhook_handler_1(_ arg: String) -> String {
    if arg == "trigger" { return "patched by @@PROJECTNAME@@" }
    return ch_orig(arg)
}
