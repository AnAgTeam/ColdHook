// Pure layout planning for shared-mode payloads.  Mach-O emission is kept out of
// this file so the planner can be tested independently from load-command rewriting.
import Foundation

struct ColdhookSharedLayout {
    let stubVMAddr: UInt64
    let stubFileOffset: UInt64
    let stubSize: UInt64
    let tableVMAddr: UInt64
    let tableFileOffset: UInt64
    let tableSize: UInt64
}

enum ColdhookSharedLayoutError: Error, CustomStringConvertible {
    case noExecutableSegment
    case noWritableSegment
    case addressOutOfRange

    var description: String {
        switch self {
        case .noExecutableSegment: return "shared: target has no executable segment"
        case .noWritableSegment: return "shared: target has no writable data segment"
        case .addressOutOfRange: return "shared: mini-stub slot is out of ADRP/LDR range"
        }
    }
}

private func pageAlign(_ value: UInt64, _ page: UInt64) -> UInt64 {
    (value + page - 1) & ~(page - 1)
}

/// Computes append locations for executable stubs and writable metadata.  The caller
/// is responsible for materializing the sections and updating segment commands.
func planColdhookSharedLayout(
    executableVMEnd: UInt64,
    executableFileEnd: UInt64,
    writableVMEnd: UInt64,
    writableFileEnd: UInt64,
    stubSize: UInt64,
    tableSize: UInt64,
    pageSize: UInt64 = 0x4000
) throws -> ColdhookSharedLayout {
    guard stubSize > 0, tableSize > 0 else {
        throw ColdhookSharedLayoutError.noExecutableSegment
    }

    let stubVMAddr = pageAlign(executableVMEnd, pageSize)
    let stubFileOffset = pageAlign(executableFileEnd, pageSize)
    let tableVMAddr = pageAlign(writableVMEnd, pageSize)
    let tableFileOffset = pageAlign(writableFileEnd, pageSize)

    // The stub uses ADRP to address the table slot.  Keep this check here so an
    // assembler cannot accidentally emit an invalid veneer for distant segments.
    let pageDelta = Int64(bitPattern: (tableVMAddr & ~0xfff))
        - Int64(bitPattern: (stubVMAddr & ~0xfff))
    guard pageDelta >= -(1 << 20) * 0x1000 && pageDelta < (1 << 20) * 0x1000 else {
        throw ColdhookSharedLayoutError.addressOutOfRange
    }

    return ColdhookSharedLayout(
        stubVMAddr: stubVMAddr,
        stubFileOffset: stubFileOffset,
        stubSize: stubSize,
        tableVMAddr: tableVMAddr,
        tableFileOffset: tableFileOffset,
        tableSize: tableSize
    )
}
