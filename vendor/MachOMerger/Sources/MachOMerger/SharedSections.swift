// Mach-O section/segment command helpers for shared mode.
import Foundation
import MachO

struct ColdhookSharedSectionSpec {
    let segment: String
    let section: String
    let address: UInt64
    let size: UInt64
    let fileOffset: UInt32
    let alignment: UInt32
    let flags: UInt32
}

enum ColdhookSharedSectionError: Error, CustomStringConvertible {
    case invalidName(String)
    case addressOverflow

    var description: String {
        switch self {
        case .invalidName(let name): return "shared: Mach-O name is too long: \(name)"
        case .addressOverflow: return "shared: section address/file offset does not fit Mach-O fields"
        }
    }
}

private func writeName<T>(_ name: String, into destination: inout T) throws {
    let bytes = Array(name.utf8)
    guard bytes.count < 16 else { throw ColdhookSharedSectionError.invalidName(name) }
    withUnsafeMutableBytes(of: &destination) { raw in
        raw.initializeMemory(as: Int8.self, repeating: 0)
        for (i, byte) in bytes.enumerated() { raw[i] = byte }
    }
}

func makeColdhookSharedSection(_ spec: ColdhookSharedSectionSpec) throws -> section_64 {
    guard spec.address <= UInt64.max, spec.size <= UInt64.max,
          UInt64(spec.fileOffset) <= UInt64(UInt32.max) else {
        throw ColdhookSharedSectionError.addressOverflow
    }
    var section = section_64()
    try writeName(spec.section, into: &section.sectname)
    try writeName(spec.segment, into: &section.segname)
    section.addr = spec.address
    section.size = spec.size
    section.offset = spec.fileOffset
    section.align = spec.alignment
    section.flags = spec.flags
    return section
}

func makeColdhookSharedSections(_ plan: ColdhookSharedTargetPlan) throws -> [String: [section_64]] {
    let stub = try makeColdhookSharedSection(ColdhookSharedSectionSpec(
        segment: "__TEXT", section: "__coldhook_stub",
        address: plan.layout.stubVMAddr, size: plan.layout.stubSize,
        fileOffset: UInt32(plan.layout.stubFileOffset), alignment: 2,
        flags: UInt32(S_REGULAR) | UInt32(S_ATTR_SOME_INSTRUCTIONS) | UInt32(S_ATTR_PURE_INSTRUCTIONS)
    ))
    let table = try makeColdhookSharedSection(ColdhookSharedSectionSpec(
        segment: "__DATA", section: "__coldhook",
        address: plan.layout.tableVMAddr, size: plan.layout.tableSize,
        fileOffset: UInt32(plan.layout.tableFileOffset), alignment: 3,
        flags: UInt32(S_REGULAR)
    ))
    return ["__TEXT": [stub], "__DATA": [table]]
}
