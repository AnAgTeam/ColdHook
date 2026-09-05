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

/// Reads the same `_MACHOMERGER_HOOK_*` declarations consumed by embedded mode.
/// In a normal clang-produced dylib the magic symbol is the handler itself (its
/// first instruction is a prologue, not a branch), so the handler name is derived
/// directly from the magic symbol rather than decoding code bytes.
func extractColdhookSharedSpecs(from resolver: ColdhookSymbolResolver, data: MachOMergeData)
    throws -> [ColdhookSharedSpec] {
    var specs: [ColdhookSharedSpec] = []
    let hooks = resolver.all(prefix: "_MACHOMERGER_HOOK_")
    for hook in hooks {
        let locator = String(hook.name.dropFirst("_MACHOMERGER_HOOK_".count))
        let handlerName = String(hook.name.dropFirst())
        specs.append(ColdhookSharedSpec(
            hookID: fnv1a(locator),
            handlerName: handlerName,
            origImageOffset: 0,
            origSlotKey: UInt32(truncatingIfNeeded: fnv1a(locator)),
            flags: 0
        ))
    }
    return specs
}
