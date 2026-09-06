// Cross-platform Mach-O wire-format definitions.
// The Apple `MachO` Clang module is part of Darwin SDKs and is unavailable on
// Windows/Linux. These declarations intentionally mirror the 64-bit layouts
// from <mach-o/loader.h> and the numeric constants from <mach/machine.h>.

import Foundation

let MH_MAGIC_64: UInt32 = 0xfeedfacf
let CPU_TYPE_ARM64: UInt32 = 0x0100000c

let LC_SEGMENT_64: UInt32 = 0x19
let LC_SYMTAB: UInt32 = 0x2
let LC_DYSYMTAB: UInt32 = 0xb
let LC_LOAD_DYLIB: UInt32 = 0xc
let LC_ID_DYLIB: UInt32 = 0xd
let LC_LOAD_DYLINKER: UInt32 = 0xe
let LC_ID_DYLINKER: UInt32 = 0xf
let LC_PREBOUND_DYLIB: UInt32 = 0x10
let LC_UUID: UInt32 = 0x1b
let LC_LOAD_WEAK_DYLIB: UInt32 = 0x18 | 0x80000000
let LC_RPATH: UInt32 = 0x1c | 0x80000000
let LC_CODE_SIGNATURE: UInt32 = 0x1d
let LC_ENCRYPTION_INFO_64: UInt32 = 0x2c
let LC_DYLD_INFO: UInt32 = 0x22
let LC_DYLD_INFO_ONLY: UInt32 = 0x22 | 0x80000000
let LC_VERSION_MIN_IPHONEOS: UInt32 = 0x25
let LC_FUNCTION_STARTS: UInt32 = 0x26 | 0x80000000
let LC_DYLD_ENVIRONMENT: UInt32 = 0x27
let LC_DATA_IN_CODE: UInt32 = 0x29 | 0x80000000
let LC_SOURCE_VERSION: UInt32 = 0x2a | 0x80000000
let LC_DYLIB_CODE_SIGN_DRS: UInt32 = 0x2b | 0x80000000
let LC_MAIN: UInt32 = 0x28 | 0x80000000
let LC_DYLD_EXPORTS_TRIE: UInt32 = 0x33 | 0x80000000
let LC_DYLD_CHAINED_FIXUPS: UInt32 = 0x34 | 0x80000000
let LC_FILESET_ENTRY: UInt32 = 0x35 | 0x80000000
let LC_BUILD_VERSION: UInt32 = 0x32 | 0x80000000
let LC_SEGMENT_SPLIT_INFO: UInt32 = 0x1e | 0x80000000
let LC_ENCRYPTION_INFO: UInt32 = 0x21
let LC_LOAD_UPWARD_DYLIB: UInt32 = 0x23 | 0x80000000
let LC_VERSION_MIN_MACOSX: UInt32 = 0x24
let LC_REEXPORT_DYLIB: UInt32 = 0x1f | 0x80000000
let LC_LAZY_LOAD_DYLIB: UInt32 = 0x20
let LC_UNIXTHREAD: UInt32 = 0x5

let VM_PROT_READ: Int32 = 1
let VM_PROT_WRITE: Int32 = 2
let VM_PROT_EXECUTE: Int32 = 4

struct mach_header_64 {
    var magic: UInt32 = 0; var cputype: UInt32 = 0; var cpusubtype: Int32 = 0
    var filetype: UInt32 = 0; var ncmds: UInt32 = 0; var sizeofcmds: UInt32 = 0
    var flags: UInt32 = 0; var reserved: UInt32 = 0
}

struct segment_command_64 {
    var cmd: UInt32 = 0; var cmdsize: UInt32 = 0
    var segname = (Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0))
    var vmaddr: UInt64 = 0; var vmsize: UInt64 = 0; var fileoff: UInt64 = 0; var filesize: UInt64 = 0
    var maxprot: Int32 = 0; var initprot: Int32 = 0; var nsects: UInt32 = 0; var flags: UInt32 = 0
}

struct section_64 {
    var sectname = (Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0))
    var segname = (Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0), Int8(0))
    var addr: UInt64 = 0; var size: UInt64 = 0; var offset: UInt32 = 0; var align: UInt32 = 0
    var reloff: UInt32 = 0; var nreloc: UInt32 = 0; var flags: UInt32 = 0
    var reserved1: UInt32 = 0; var reserved2: UInt32 = 0; var reserved3: UInt32 = 0
}
