import Foundation
import MachO

/// Common builder for append-style segments used by append and shared modes.
func makeAppendedSegmentCommand(name: String, vmAddr: UInt64, fileOffset: UInt64,
                                vmSize: UInt64, fileSize: UInt64,
                                maxProt: Int32, initProt: Int32,
                                sections: [section_64], flags: UInt32 = 0) throws -> Data {
    var command = segment_command_64()
    command.cmd = UInt32(LC_SEGMENT_64)
    command.cmdsize = UInt32(MemoryLayout<segment_command_64>.size + sections.count * MemoryLayout<section_64>.size)
    let bytes = Array(name.utf8)
    guard bytes.count < 16 else { throw ColdhookSharedSectionError.invalidName(name) }
    withUnsafeMutableBytes(of: &command.segname) { raw in
        raw.initializeMemory(as: Int8.self, repeating: 0)
        for (i, byte) in bytes.enumerated() { raw[i] = byte }
    }
    command.vmaddr = vmAddr; command.vmsize = vmSize
    command.fileoff = fileOffset; command.filesize = fileSize
    command.maxprot = maxProt; command.initprot = initProt
    command.flags = flags
    command.nsects = UInt32(sections.count)
    var out = Data(fromObject: command)
    for section in sections { out.appendGeneric(value: section) }
    return out
}
