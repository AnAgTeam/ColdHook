import SwiftCompilerPlugin
import SwiftSyntaxMacros

@main
struct ColdHookPlugin: CompilerPlugin {
    let providingMacros: [Macro.Type] = [ColdHookMangledMacro.self]
}
