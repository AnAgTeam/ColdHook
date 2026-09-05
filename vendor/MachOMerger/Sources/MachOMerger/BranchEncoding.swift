import Foundation

enum ColdhookBranchError: Error, CustomStringConvertible {
    case unaligned(UInt64, UInt64)
    case outOfRange(UInt64, UInt64)

    var description: String {
        switch self {
        case .unaligned(let from, let to):
            return String(format: "B: unaligned addresses 0x%llx -> 0x%llx", from, to)
        case .outOfRange(let from, let to):
            return String(format: "B: delta too large 0x%llx -> 0x%llx", from, to)
        }
    }
}

/// Shared encoder for the unconditional arm64 B instruction.  Both embedded
/// and shared backends must use this implementation to keep range semantics equal.
func encodeColdhookB(from: UInt64, to: UInt64) throws -> UInt32 {
    guard from & 3 == 0, to & 3 == 0 else {
        throw ColdhookBranchError.unaligned(from, to)
    }
    let delta = Int64(bitPattern: to) - Int64(bitPattern: from)
    let words = delta >> 2
    guard delta & 3 == 0, words >= -(1 << 25), words < (1 << 25) else {
        throw ColdhookBranchError.outOfRange(from, to)
    }
    return 0x14000000 | UInt32(UInt64(bitPattern: words) & 0x03ffffff)
}
