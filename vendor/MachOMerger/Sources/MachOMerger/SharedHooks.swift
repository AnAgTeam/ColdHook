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
/// The handler name is recovered by decoding the declaration's `b _handler`
/// instruction, so no second manifest is required.
func extractColdhookSharedSpecs(from resolver: ColdhookSymbolResolver, data: MachOMergeData)
    throws -> [ColdhookSharedSpec] {
    var specs: [ColdhookSharedSpec] = []
    let hooks = resolver.all(prefix: "_MACHOMERGER_HOOK_")
    for hook in hooks {
        guard let instruction = readBInstruction(hook.value, from: data),
              instruction & 0xfc000000 == 0x14000000 else {
            throw ColdhookSharedHookError.invalidBranch(hook.name)
        }
        let target = UInt64(Int64(bitPattern: hook.value) +
                            signExtend(instruction & 0x03ffffff, bits: 26) * 4)
        guard let handler = resolver.symbols.first(where: { $0.value == target &&
                                                    ($0.type & 0x0e) == 0x0e }) else {
            throw ColdhookSharedHookError.handlerNotFound(hook.name)
        }
        let locator = String(hook.name.dropFirst("_MACHOMERGER_HOOK_".count))
        specs.append(ColdhookSharedSpec(
            hookID: fnv1a(locator),
            handlerName: handler.name,
            origImageOffset: 0,
            origSlotKey: UInt32(truncatingIfNeeded: fnv1a(locator)),
            flags: 0
        ))
    }
    return specs
}
