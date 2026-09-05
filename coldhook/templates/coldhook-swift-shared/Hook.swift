// Shared Swift hook. Keep the ABI identical to the target function.
// Replace the @_silgen_name values and signature with your target's ABI.
import Foundation

@_silgen_name("coldhook_orig_ch_hook")
func ch_orig(_ arg: String) -> String

@_silgen_name("ch_hook")
public func ch_hook(_ arg: String) -> String {
    if arg == "trigger" { return "patched by @@PROJECTNAME@@" }
    return ch_orig(arg)
}

