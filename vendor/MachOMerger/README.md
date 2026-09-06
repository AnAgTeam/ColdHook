# MachOMerger

Merge two MachO binaries into one. The only supported use case at this moment is merging a dylib into dyld.

# Requirements
- The dylib to be injected *must* be compiled with `-Xlinker -add_split_seg_info -Xlinker -no_auth_data`
# Cross-platform byte-level build

MachOMerger no longer imports Apple's SDK-only `MachO` module. The executable
uses the bundled `MachOCompat.swift` wire-format declarations and can therefore
be compiled wherever Swift Foundation and the pure-Swift dependencies are
available. FAT32/FAT64 files are accepted; the arm64 slice is merged and all
other slices are copied into the output unchanged.

The tool only rewrites Mach-O bytes. Signing, loading, and execution remain
macOS-only operations and are intentionally not performed by the merger.
