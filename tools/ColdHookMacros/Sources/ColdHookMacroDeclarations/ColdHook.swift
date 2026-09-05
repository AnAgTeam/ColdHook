@attached(peer)
public macro ColdHookMangled(binary: String, target: String) =
    #externalMacro(module: "ColdHookMacros", type: "ColdHookMangledMacro")
