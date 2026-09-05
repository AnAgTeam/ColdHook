import ColdHookMacroDeclarations

@ColdHookMangled(binary: "TestSwiftApp", target: "$s12TestSwiftApp3url3forS2S_tF")
func smoke(_ value: String) -> String { value }

print(smoke("macro-ok"))
