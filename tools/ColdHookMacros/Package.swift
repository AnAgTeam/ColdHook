// swift-tools-version: 5.9
import PackageDescription
import CompilerPluginSupport

let package = Package(
    name: "ColdHookMacros",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "ColdHookMacroDeclarations", targets: ["ColdHookMacroDeclarations"]),
    ],
    dependencies: [
        .package(url: "https://github.com/swiftlang/swift-syntax.git", from: "509.0.0")
    ],
    targets: [
        .macro(name: "ColdHookMacros", dependencies: [
            .product(name: "SwiftSyntax", package: "swift-syntax"),
            .product(name: "SwiftSyntaxMacros", package: "swift-syntax"),
            .product(name: "SwiftCompilerPlugin", package: "swift-syntax"),
            .product(name: "SwiftDiagnostics", package: "swift-syntax"),
        ]),
        .target(name: "ColdHookMacroDeclarations", dependencies: ["ColdHookMacros"]),
        .executableTarget(name: "ColdHookMacroSmoke", dependencies: ["ColdHookMacroDeclarations"]),
    ]
)
