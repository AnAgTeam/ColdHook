// Shared-table metadata emitter.  The byte layout mirrors coldhook_shared.h.
import Foundation
import SwiftMachO

struct ColdhookSharedSpec {
    let hookID: UInt64
    let handlerName: String
    let origImageOffset: UInt64
    let origSlotKey: UInt32
    let flags: UInt32
}

struct ColdhookSharedEmission {
    let data: Data
    let handlerSlotOffsets: [UInt32]
    let recordsOffset: UInt32
    let stringsOffset: UInt32
}

struct ColdhookSharedStub {
    let address: UInt64
    let slotAddress: UInt64
    let bytes: Data
}

private let coldhookSharedMagic: UInt32 = 0x43484b54 // CHKT
private let coldhookSharedVersion: UInt16 = 1
private let coldhookSharedHeaderSize: UInt16 = 28
private let coldhookSharedRecordSize: UInt16 = 40

private func appendLE<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
    var v = value.littleEndian
    data.append(Data(bytes: &v, count: MemoryLayout<T>.size))
}

private func align8(_ value: Int) -> Int { (value + 7) & ~7 }

private func encodeADRP(rd: UInt32, from: UInt64, to: UInt64) -> UInt32 {
    let fromPage = Int64(bitPattern: from & ~0xfff)
    let toPage = Int64(bitPattern: to & ~0xfff)
    let delta = (toPage - fromPage) >> 12
    precondition(delta >= -(1 << 20) && delta < (1 << 20), "ADRP target out of range")
    let imm = UInt64(bitPattern: delta) & 0x1fffff
    return 0x90000000 | (rd & 0x1f) | UInt32((imm & 3) << 29) | UInt32((imm >> 2) << 5)
}

private func encodeLDRUnsigned64(rt: UInt32, rn: UInt32, from: UInt64, to: UInt64) -> UInt32 {
    let delta = to - from
    precondition(delta & 7 == 0 && delta / 8 < 4096,
                 String(format: "LDR target out of range: from=0x%llx to=0x%llx delta=%llu", from, to, delta))
    return 0xf9400000 | (UInt32(delta / 8) << 10) | ((rn & 0x1f) << 5) | (rt & 0x1f)
}

private func encodeBR(rn: UInt32) -> UInt32 { 0xd61f0000 | ((rn & 0x1f) << 5) }

/// Emits the three-instruction local veneer used by bootstrap-table mode.
/// `slotAddress` is the address of the target-side writable handler slot.
func emitColdhookSharedStub(address: UInt64, slotAddress: UInt64) -> ColdhookSharedStub {
    var bytes = Data()
    let adrp = encodeADRP(rd: 16, from: address, to: slotAddress)
    // ADRP places the slot page in x16; LDR's immediate is page-relative.
    let ldr = encodeLDRUnsigned64(rt: 16, rn: 16, from: slotAddress & ~0xfff,
                                  to: slotAddress)
    bytes.append(Data(fromObject: adrp))
    bytes.append(Data(fromObject: ldr))
    bytes.append(Data(fromObject: encodeBR(rn: 16)))
    return ColdhookSharedStub(address: address, slotAddress: slotAddress, bytes: bytes)
}

/// Emits a self-describing __DATA,__coldhook payload.  Slots are zero-initialized;
/// the runtime fills them after resolving handlers.  All offsets are section-relative.
func emitColdhookSharedMetadata(_ specs: [ColdhookSharedSpec]) -> ColdhookSharedEmission {
    let recordsOffset = align8(Int(coldhookSharedHeaderSize))
    let stringsOffset = recordsOffset + specs.count * Int(coldhookSharedRecordSize)

    var strings = Data()
    var names: [(UInt32, UInt32)] = []
    for spec in specs {
        let bytes = Array(spec.handlerName.utf8)
        names.append((UInt32(strings.count), UInt32(bytes.count)))
        strings.append(contentsOf: bytes)
        strings.append(0)
    }

    // Header + records + string blob.  The records contain offsets to local slots;
    // each slot is an 8-byte zero value immediately following its record.
    var out = Data(repeating: 0, count: recordsOffset)
    out.replaceSubrange(0..<4, with: Data(fromObject: coldhookSharedMagic))
    out.replaceSubrange(4..<6, with: Data(fromObject: coldhookSharedVersion))
    out.replaceSubrange(6..<8, with: Data(fromObject: coldhookSharedHeaderSize))
    out.replaceSubrange(8..<10, with: Data(fromObject: coldhookSharedRecordSize))
    out.replaceSubrange(10..<12, with: Data(fromObject: UInt16(0)))
    out.replaceSubrange(12..<16, with: Data(fromObject: UInt32(specs.count)))
    out.replaceSubrange(16..<20, with: Data(fromObject: UInt32(recordsOffset)))
    out.replaceSubrange(20..<24, with: Data(fromObject: UInt32(stringsOffset)))
    out.replaceSubrange(24..<28, with: Data(fromObject: UInt32(strings.count)))

    let slotsOffset = align8(stringsOffset + strings.count)
    var slotOffsets: [UInt32] = []
    for (i, spec) in specs.enumerated() {
        var record = Data()
        appendLE(spec.hookID, to: &record)
        let slotOffset = slotsOffset + i * 8
        slotOffsets.append(UInt32(slotOffset))
        appendLE(UInt32(slotOffset), to: &record)
        appendLE(UInt32(0), to: &record)
        appendLE(spec.origImageOffset, to: &record)
        appendLE(names[i].0, to: &record)
        appendLE(names[i].1, to: &record)
        appendLE(spec.origSlotKey, to: &record)
        appendLE(spec.flags, to: &record)
        out.append(record)
    }
    out.append(strings)
    if out.count < slotsOffset { out.append(Data(repeating: 0, count: slotsOffset - out.count)) }
    out.append(Data(repeating: 0, count: specs.count * 8))
    return ColdhookSharedEmission(data: out, handlerSlotOffsets: slotOffsets,
                                  recordsOffset: UInt32(recordsOffset),
                                  stringsOffset: UInt32(stringsOffset))
}
