import Foundation
import SwiftMachO

private struct FatSliceRecord { var cpu: UInt32; var sub: UInt32; var align: UInt32; var data: Data }
private struct FatImage { var is64: Bool; var slices: [FatSliceRecord] }

private func be32(_ d: Data, _ o: Int) -> UInt32 {
    UInt32(d[o]) << 24 | UInt32(d[o+1]) << 16 | UInt32(d[o+2]) << 8 | UInt32(d[o+3])
}
private func be64(_ d: Data, _ o: Int) -> UInt64 {
    UInt64(be32(d,o)) << 32 | UInt64(be32(d,o+4))
}
private func putBE32(_ v: UInt32, into d: inout Data) { d.append(UInt8(v >> 24)); d.append(UInt8(v >> 16)); d.append(UInt8(v >> 8)); d.append(UInt8(v)) }
private func putBE64(_ v: UInt64, into d: inout Data) { putBE32(UInt32(v >> 32), into: &d); putBE32(UInt32(v), into: &d) }

private func parseFat(_ data: Data) -> FatImage? {
    guard data.count >= 8 else { return nil }
    let magic = be32(data, 0)
    let is64 = magic == 0xcafebabf
    guard magic == 0xcafebabe || is64 else { return nil }
    let n = Int(be32(data, 4)); let entrySize = is64 ? 32 : 20
    guard n > 0, n <= 4096, 8 + n * entrySize <= data.count else { return nil }
    var slices: [FatSliceRecord] = []
    for i in 0..<n {
        let p = 8 + i * entrySize
        let cpu = be32(data,p), sub = be32(data,p+4)
        let off = is64 ? be64(data,p+8) : UInt64(be32(data,p+8))
        let size = is64 ? be64(data,p+16) : UInt64(be32(data,p+12))
        let align = is64 ? be32(data,p+24) : be32(data,p+16)
        guard off <= UInt64(data.count), size <= UInt64(data.count) - off else { return nil }
        slices.append(FatSliceRecord(cpu: cpu, sub: sub, align: align, data: data.subdata(in: Int(off)..<Int(off+size))))
    }
    return FatImage(is64: is64, slices: slices)
}

private var originalFat: FatImage?

func loadMachO(_ path: String) throws -> MachO {
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    if let fat = parseFat(data) {
        // The output keeps the target's architecture set (A); B is only an
        // input payload and must not change the container format.
        if originalFat == nil { originalFat = fat }
        guard let arm = fat.slices.first(where: { $0.cpu == CPU_TYPE_ARM64 }) else { throw MachOError.BadFormat }
        return try MachO(fromData: arm.data, okToLoadFAT: false)
    }
    return try MachO(fromData: data, okToLoadFAT: false)
}

func writeMachO(_ data: Data, to path: String) throws {
    guard let fat = originalFat else { try data.write(to: URL(fileURLWithPath: path)); return }
    var slices = fat.slices
    if let i = slices.firstIndex(where: { $0.cpu == CPU_TYPE_ARM64 }) { slices[i].data = data }
    let headerSize = 8 + slices.count * (fat.is64 ? 32 : 20)
    var output = Data(); output.reserveCapacity(headerSize + slices.reduce(0) { $0 + $1.data.count })
    putBE32(fat.is64 ? 0xcafebabf : 0xcafebabe, into: &output); putBE32(UInt32(slices.count), into: &output)
    output.append(Data(repeating: 0, count: slices.count * (fat.is64 ? 32 : 20)))
    var offsets: [UInt64] = []; var cursor = UInt64(headerSize)
    for slice in slices { let align = min(slice.align, 20); let boundary = UInt64(1) << align; cursor = (cursor + boundary - 1) & ~(boundary - 1); offsets.append(cursor); cursor += UInt64(slice.data.count) }
    if output.count < Int(cursor) { output.append(Data(repeating: 0, count: Int(cursor) - output.count)) }
    for (i,slice) in slices.enumerated() { let off = Int(offsets[i]); output.replaceSubrange(off..<off+slice.data.count, with: slice.data); let p = 8 + i * (fat.is64 ? 32 : 20); var e = Data(); putBE32(slice.cpu, into: &e); putBE32(slice.sub, into: &e); if fat.is64 { putBE64(offsets[i], into: &e); putBE64(UInt64(slice.data.count), into: &e) } else { putBE32(UInt32(offsets[i]), into: &e); putBE32(UInt32(slice.data.count), into: &e) }; putBE32(slice.align, into: &e); if fat.is64 { putBE32(0, into: &e); putBE32(0, into: &e) }; output.replaceSubrange(p..<p+e.count, with: e) }
    try output.write(to: URL(fileURLWithPath: path))
}
