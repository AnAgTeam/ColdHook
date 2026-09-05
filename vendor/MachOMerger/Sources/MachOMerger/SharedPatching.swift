// Byte-level arm64 patching used by the shared assembler.
import Foundation
import SwiftMachO

enum ColdhookSharedPatchError: Error, CustomStringConvertible {
    case unaligned(UInt64)
    case outOfRange(UInt64)
    case branchOutOfRange(UInt64, UInt64)

    var description: String {
        switch self {
        case .unaligned(let address): return String(format: "shared: unaligned address 0x%llx", address)
        case .outOfRange(let address): return String(format: "shared: address is outside target segment: 0x%llx", address)
        case .branchOutOfRange(let from, let to):
            return String(format: "shared: B out of range: 0x%llx -> 0x%llx", from, to)
        }
    }
}

/// Replaces one target instruction with `B stub`, preserving all other bytes.
func patchColdhookSharedEntry(_ bytes: inout Data, segmentVMAddr: UInt64,
                              entryAddress: UInt64, stubAddress: UInt64) throws {
    guard entryAddress >= segmentVMAddr else { throw ColdhookSharedPatchError.outOfRange(entryAddress) }
    let offset = entryAddress - segmentVMAddr
    guard offset <= UInt64(Int.max), Int(offset) + 4 <= bytes.count else {
        throw ColdhookSharedPatchError.outOfRange(entryAddress)
    }
    let instruction: UInt32
    do {
        instruction = try encodeColdhookB(from: entryAddress, to: stubAddress)
    } catch ColdhookBranchError.outOfRange {
        throw ColdhookSharedPatchError.branchOutOfRange(entryAddress, stubAddress)
    } catch {
        throw ColdhookSharedPatchError.unaligned(entryAddress)
    }
    bytes.replaceSubrange(Int(offset)..<Int(offset) + 4, with: Data(fromObject: instruction))
}

/// Concatenates each veneer and its reserved eight-byte orig body.  The orig body
/// is intentionally left zeroed; the caller fills it with the relocated prologue
/// and return branch once the target segment is available.
func materializeColdhookSharedStubs(_ plan: ColdhookSharedTargetPlan) -> Data {
    var result = Data()
    for hook in plan.hooks {
        result.append(hook.stub.bytes)
        result.append(Data(repeating: 0, count: 8))
    }
    return result
}
