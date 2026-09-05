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
              arguments.count == 2,
              let binary = stringValue(Array(arguments)[0].expression),
              let target = stringValue(Array(arguments)[1].expression),
              !binary.isEmpty, !target.isEmpty else {
            throw DiagnosticsError(diagnostics: [
                Diagnostic(node: node, message: ColdHookMacroDiagnostic("expected binary and target"))
            ])
        }
        let suffix = target.utf8.reduce(UInt64(1469598103934665603)) {
            ($0 ^ UInt64($1)) &* 1099511628211
        }
        let name = "__coldhook_mangled_\(String(suffix, radix: 16))"
        let marker = "private let \(name) = \"\(escape(binary))|\(escape(target))\""
        return [DeclSyntax(stringLiteral: marker)]
    }

    private static func stringValue(_ expression: ExprSyntax) -> String? {
        guard let literal = expression.as(StringLiteralExprSyntax.self),
              literal.segments.count == 1,
              let segment = literal.segments.first?.as(StringSegmentSyntax.self) else { return nil }
        return segment.content.text
    }

    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}

private struct ColdHookMacroDiagnostic: DiagnosticMessage {
    let message: String
    init(_ message: String) { self.message = message }
    var diagnosticID: MessageID { MessageID(domain: "ColdHookMacros", id: "invalid-arguments") }
    var severity: DiagnosticSeverity { .error }
}
