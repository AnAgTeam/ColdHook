import SwiftSyntax
import SwiftSyntaxMacros
import SwiftDiagnostics

public struct ColdHookMangledMacro: PeerMacro {
    public static func expansion(
        of node: AttributeSyntax,
        providingPeersOf declaration: some DeclSyntaxProtocol,
        in context: some MacroExpansionContext
    ) throws -> [DeclSyntax] {
        guard let arguments = node.arguments?.as(LabeledExprListSyntax.self),
              arguments.count == 2 else {
            throw DiagnosticsError(diagnostics: [
                Diagnostic(node: node, message: ColdHookMacroDiagnostic("expected binary and target"))
            ])
        }
        return []
    }
}

private struct ColdHookMacroDiagnostic: DiagnosticMessage {
    let message: String
    init(_ message: String) { self.message = message }
    var diagnosticID: MessageID { MessageID(domain: "ColdHookMacros", id: "invalid-arguments") }
    var severity: DiagnosticSeverity { .error }
}
