// Extraction of shared hook declarations from the same magic symbols used by
// embedded mode.  This keeps the declaration/handler naming contract identical.
import Foundation

enum ColdhookSharedHookError: Error, CustomStringConvertible {
    case invalidBranch(String)
    case handlerNotFound(String)

    var description: String {
        switch self {
        case .invalidBranch(let name): return "shared: hook magic symbol is not a B instruction: \(name)"
        case .handlerNotFound(let name): return "shared: cannot resolve handler for \(name)"
        }
    }
}

func coldhookBinarySelectors(path: String) -> Set<String> {
    let filename = URL(fileURLWithPath: path).lastPathComponent
    var result: Set<String> = [filename]
    // Also accept a bundle-relative selector, e.g.
    // Frameworks/TestFramework.framework/TestFramework.  This disambiguates
    // equal basenames in nested frameworks while remaining stable for IPA
    // extraction into a temporary directory.
    let normalized = URL(fileURLWithPath: path).standardizedFileURL.path
    if let appRange = normalized.range(of: ".app/") {
        result.insert(String(normalized[appRange.upperBound...]))
    }
    return result
}

private func signExtend(_ value: UInt32, bits: Int) -> Int64 {
    let shift = 64 - bits
    return Int64(bitPattern: UInt64(value) << shift) >> shift
}

private func fnv1a(_ value: String) -> UInt64 {
    var hash: UInt64 = 0xcbf29ce484222325
    for byte in value.utf8 {
        hash ^= UInt64(byte)
        hash &*= 0x100000001b3
    }
    return hash == 0 ? 1 : hash
}

private func readBInstruction(_ address: UInt64, from data: MachOMergeData) -> UInt32? {
    for (segment, bytes) in data.segments {
        guard address >= segment.vmAddr,
              address < segment.vmAddr + segment.fileSize else { continue }
        let offset = Int(address - segment.vmAddr)
        guard offset >= 0, offset + 4 <= bytes.count else { return nil }
        return bytes.withUnsafeBytes { $0.load(fromByteOffset: offset, as: UInt32.self) }
    }
    return nil
}

/// Reads ColdHook magic declarations. Dynamic forms encode selector, locator and
/// handler as `_COLDHOOK_DYN_<kind>_<selector>__CH__<locator>__CH__<handler>`.
/// Target metadata retains this complete name so runtime can resolve the entry
/// together with its `_COLDHOOK_ORIG_*` slot in one provider-image scope.
func extractColdhookSharedSpecs(from resolver: ColdhookSymbolResolver, data: MachOMergeData,
                                targetSelectors: Set<String> = [])
    throws -> [ColdhookSharedSpec] {
    var specs: [ColdhookSharedSpec] = []
    let hooks = resolver.all(prefix: "_COLDHOOK_DYN_")
    for hook in hooks {
        let payload = String(hook.name.dropFirst("_COLDHOOK_DYN_".count))
        let parts = payload.components(separatedBy: "__CH__")
        guard parts.count == 3 else { throw ColdhookSharedHookError.invalidBranch(hook.name) }
        let dynKindAndSelector = parts[0].split(separator: "_", maxSplits: 1).map(String.init)
        guard dynKindAndSelector.count == 2,
              dynKindAndSelector[0] == "SYM" || dynKindAndSelector[0] == "ADDR",
              !dynKindAndSelector[1].isEmpty else {
            throw ColdhookSharedHookError.invalidBranch(hook.name)
        }
        let kind: ColdhookHookKind = dynKindAndSelector[0] == "SYM" ? .symbol : .address
        let binarySelector = dynKindAndSelector[1]
        guard targetSelectors.isEmpty || targetSelectors.contains(binarySelector) else {
            continue
        }
        let locator = parts[1]
        // dlsym uses the C spelling (without Mach-O's leading underscore).
        // Keeping the complete magic name in target metadata lets runtime
        // resolve the entry and its matching ORIG slot in one dylib scope.
        let handlerName = String(hook.name.dropFirst())
        specs.append(ColdhookSharedSpec(
            kind: kind,
            binarySelector: binarySelector,
            locator: locator,
            hookID: fnv1a(locator),
            handlerName: handlerName,
            origImageOffset: 0,
            origSlotKey: UInt32(truncatingIfNeeded: fnv1a(locator)),
            flags: 0
        ))
    }
    return specs
}
