//
//  main.swift
//  MachOMerger
//
//  Created by Linus Henze.
//

import Foundation
import SwiftMachO

typealias SegRelocInfo = [(String, [(isB: Bool, origCommand: Segment64LoadCommand, data: Data, offset: UInt64)])]

let pageSize: UInt64    = 0x4000
let pageMaskOff: UInt64 = pageSize - 1
let pageMask: UInt64    = ~pageMaskOff

// ColdHook: --allow-new-dylibs разрешает B тянуть dylib, которых нет в таргете A
// (мёрджер допишет их LC_LOAD_DYLIB). По умолчанию выключено — чужой импорт = ошибка.
let coldhookAllowNewDylibs = CommandLine.arguments.contains("--allow-new-dylibs")
var coldhookNewDylibCmds: [Data] = []   // сырые LC_LOAD_DYLIB для дозаписи (заполняет merge)

// ColdHook: --mode auto|append|interleave (дефолт auto). Резолв в coldhookAppendMode ниже
// (после разбора A), здесь — только вытащить значение. Поддержаны обе формы: --mode append и
// --mode=append. В первой значение НЕ должно попасть в позиционные args — съедаем его явно.
func coldhookFlagValue(_ name: String) -> String? {
    let args = Array(CommandLine.arguments)
    for (i, arg) in args.enumerated() {
        if arg == name && i + 1 < args.count { return args[i + 1] }            // --mode append
        if arg.hasPrefix(name + "=") { return String(arg.dropFirst(name.count + 1)) } // --mode=append
    }
    return nil
}
let coldhookModeArg = (coldhookFlagValue("--mode") ?? "auto").lowercased()
let coldhookImportPath = coldhookFlagValue("--import-path")
let coldhookReportPath = coldhookFlagValue("--report-json")
let coldhookTargetPath = coldhookFlagValue("--target-path")
guard ["auto", "append", "interleave", "shared"].contains(coldhookModeArg) else {
    print("Unknown --mode '\(coldhookModeArg)'. Use: auto | append | interleave | shared")
    exit(-1)
}
if coldhookReportPath != nil && coldhookModeArg != "shared" {
    print("--report-json is only supported with --mode shared")
    exit(-1)
}

var coldhookPosArgs: [String] = []
var coldhookSkipNext = false
for arg in CommandLine.arguments.dropFirst() {
    if coldhookSkipNext { coldhookSkipNext = false; continue }   // значение --mode <val>
    if arg == "--mode" || arg == "--import-path" || arg == "--report-json"
        || arg == "--target-path" { coldhookSkipNext = true; continue }
    if arg.hasPrefix("--") { continue }                         // прочие флаги (--allow-new-dylibs)
    coldhookPosArgs.append(arg)
}
guard coldhookPosArgs.count == 3 else {
    print("Usage: MachOMerger <a> <b> <out> [--allow-new-dylibs] [--mode auto|append|interleave|shared] [--import-path PATH] [--report-json PATH]")
    exit(-1)
}

let a = try loadMachO(coldhookPosArgs[0])
let b = try loadMachO(coldhookPosArgs[1])

var newMachO = Data()

struct MachOMergeData {
    var segments: [(Segment64LoadCommand, Data)] = []
    var linkedit: Data?
    var dylibs: [String] = []
    var chainedFixups: Data?
    var unixthread: [(flavor: UInt32, state: Data)]?
    var mainCmd: MainLoadCommand?   // ColdHook: LC_MAIN исполняемого (entry point)
    var exportsTrie: Data?
    var symtab: (symbols: Data, strings: Data)?
    var dysymtab: (localStart: Int, localCount: Int, externalStart: Int, externalCount: Int, undefStart: Int, undefCount: Int, indirect: Data)?
    var splitInfo: Data?
    var functionStarts: Data?
    var dataInCode: Data?
    var otherCommands: [LoadCommand] = []
}

func collectData(fromMachO machO: MachO) -> MachOMergeData {
    // Iterate over all load commands
    var result = MachOMergeData()
    for cmd in machO.cmds {
        if let seg = cmd as? Segment64LoadCommand {
            let start = Int(seg.fileOffset)
            let end   = start + Int(seg.fileSize)
            guard let data = machO.data.trySubdata(in: start..<end) else {
                print("Failed to get segment \(seg.name) of a!")
                exit(-1)
            }
            
            if seg.name == "__LINKEDIT" {
                result.linkedit = data
            } else {
                result.segments.append((seg, data))
            }
        }
    }
    
    func extract(_ data: Data, _ off: Int, _ size: Int) -> Data {
        if size == 0 {
            return Data()
        }
        
        guard let res = data.trySubdata(in: off..<(off + size)) else {
            print("extract: Failed to get data!")
            exit(-1)
        }
        
        return res
    }
    
    func machOExtract(_ off: Int, _ size: Int) -> Data {
        extract(machO.data, off, size)
    }
    
    func getLECmdData(_ cmd: LoadCommand, name: String) -> Data {
        guard let cmdRaw = cmd as? OpaqueLoadCommand else {
            print("XXX: Not compatible with this version of SwiftMachO!")
            exit(-1)
        }
        
        guard let off = cmdRaw.data.tryGetGeneric(type: UInt32.self, offset: 0) else {
            print("\(name): Couldn't get offset!")
            exit(-1)
        }
        
        guard let size = cmdRaw.data.tryGetGeneric(type: UInt32.self, offset: 4) else {
            print("\(name): Couldn't get size!")
            exit(-1)
        }
        
        return machOExtract(Int(off), Int(size))
    }
    
    for cmd in machO.cmds {
        let cmdNum = cmd.type.rawValue
        if cmdNum == LC_SEGMENT_64 {
            // Already parsed
        } else if let chainLC = cmd as? ChainedFixupsLoadCommand {
            result.chainedFixups = machOExtract(Int(chainLC.fixupOffset), Int(chainLC.fixupSize))
        } else if cmdNum == LC_DYLD_EXPORTS_TRIE {
            result.exportsTrie = getLECmdData(cmd, name: "LC_DYLD_EXPORTS_TRIE")
        } else if let symtab = cmd as? SymTabLoadCommand {
            let dataSym = machOExtract(Int(symtab.symOff), 16 * Int(symtab.symCount))
            let dataStr = machOExtract(Int(symtab.strOff), Int(symtab.strSize))
            
            result.symtab = (symbols: dataSym, strings: dataStr)
        } else if cmd is DSymTabLoadCommand {
            // Will be handled later
        } else if let unixthread = cmd as? UnixThreadLoadCommand {
            result.unixthread = unixthread.threadStates
        } else if let mainCmd = cmd as? MainLoadCommand {
            result.mainCmd = mainCmd   // ColdHook: entry point исполняемого (MH_EXECUTE)
        } else if cmdNum == LC_SEGMENT_SPLIT_INFO {
            result.splitInfo = getLECmdData(cmd, name: "LC_SEGMENT_SPLIT_INFO")
        } else if cmdNum == LC_FUNCTION_STARTS {
            result.functionStarts = getLECmdData(cmd, name: "LC_FUNCTION_STARTS")
        } else if cmdNum == LC_DATA_IN_CODE {
            result.dataInCode = getLECmdData(cmd, name: "LC_DATA_IN_CODE")
        } else if cmdNum == LC_LOAD_DYLIB || cmdNum == LC_LOAD_WEAK_DYLIB || cmdNum == LC_REEXPORT_DYLIB || cmdNum == LC_LAZY_LOAD_DYLIB || cmdNum == LC_LOAD_UPWARD_DYLIB {
            // ColdHook: сохраняем всё семейство LC_*_DYLIB вербатим. weak в т.ч. — Swift-рантайм
            // (libswiftCoreFoundation/CoreImage/Darwin/Dispatch/Metal...) грузится как
            // LC_LOAD_WEAK_DYLIB; без сохранения dyld не грузит результат. Эмитится через
            // otherCommands (только A). Merge dylib-списка B и правка ordinals — отложенная задача.
            result.otherCommands.append(cmd)
        } else if cmdNum == LC_ID_DYLIB || cmdNum == LC_UUID || cmdNum == LC_ID_DYLINKER || cmdNum == LC_BUILD_VERSION || cmdNum == LC_SOURCE_VERSION || cmdNum == LC_LOAD_DYLINKER || cmdNum == LC_RPATH {
            // ColdHook: LC_LOAD_DYLINKER (исполняемый грузит /usr/lib/dyld) — сохранить вербатим.
            // LC_RPATH (@executable_path/Frameworks и т.п.) — только строка пути, релоцировать
            // нечего, сохраняем как есть, иначе приложение не найдёт свои фреймворки.
            result.otherCommands.append(cmd)
        } else if cmdNum == LC_DYLD_INFO || cmdNum == LC_DYLD_INFO_ONLY {
            // Classic dyld info is still emitted by simulator binaries.
            // Its five offset fields point into __LINKEDIT and are relocated
            // when shared mode moves that segment.
            result.otherCommands.append(cmd)
        } else if cmdNum == LC_CODE_SIGNATURE || cmdNum == LC_ENCRYPTION_INFO_64 {
        } else {
            print("Unhandled command \(cmd.type)")
            exit(-1)
        }
    }
    
    for cmd in machO.cmds {
        if let dysym = cmd as? DSymTabLoadCommand {
            guard result.symtab != nil else {
                print("DYSYMTAB without SYMTAB!")
                exit(-1)
            }
            
            let `indirect` = machOExtract(Int(dysym.indirectOff), 4 * Int(dysym.indirectCount))
            
            guard dysym.tocCount == 0 else {
                print("DYSYMTAB: TOC not supported!")
                exit(-1)
            }
            
            guard dysym.moduleTblCount == 0 else {
                print("DYSYMTAB: Module Tables not supported!")
                exit(-1)
            }
            
            guard dysym.extSymTblCount == 0 else {
                print("DYSYMTAB: External symbol tables not supported!")
                exit(-1)
            }
            
            guard dysym.extRelCount == 0 else {
                print("DYSYMTAB: External relocation not supported!")
                exit(-1)
            }
            
            guard dysym.localRelCount == 0 else {
                print("DYSYMTAB: Local relocation not supported!")
                exit(-1)
            }
            
            result.dysymtab = (localStart: Int(dysym.localSymOff), localCount: Int(dysym.localSymCount), externalStart: Int(dysym.externalSymOff), externalCount: Int(dysym.externalSymCount), undefStart: Int(dysym.undefSymOff), undefCount: Int(dysym.undefSymCount), indirect: `indirect`)
            
            break
        }
    }
    
    return result
}

// Collect data from both MachOs
var dataA = collectData(fromMachO: a)
var dataB = collectData(fromMachO: b)

// ColdHook: исполняемый (MH_EXECUTE) имеет __PAGEZERO (segment 0, vmaddr 0, vmsize 4ГБ) и
// базируется на 0x100000000. Его нельзя ребейзить к 0 (как dylib) — __PAGEZERO остаётся на
// vmaddr 0, контент пакуется от базы, заголовок резервируется в __TEXT (первом контент-сегменте).
let coldhookHasPageZero = (dataA.segments.first?.0.name == "__PAGEZERO")
let coldhookBase: UInt64 = coldhookHasPageZero
    ? (dataA.segments.first(where: { $0.0.name != "__PAGEZERO" })?.0.vmAddr ?? 0)
    : 0

if coldhookModeArg == "shared" {
    func writeSharedReport(status: String, hooks: [ColdhookSharedHookPlan]) throws {
        guard let path = coldhookReportPath else { return }
        let rows: [[String: Any]] = hooks.map { hook in
            let declaration = hook.spec.handlerName
            let handler = declaration.components(separatedBy: "__CH__").last ?? declaration
            return [
                "kind": hook.spec.kind == .symbol ? "symbol" : "address",
                "selector": hook.spec.binarySelector ?? "",
                "locator": hook.spec.locator,
                "handler": handler,
                "declaration": declaration,
                "target_address": String(format: "0x%llx", hook.entryAddress),
            ]
        }
        let report: [String: Any] = [
            "version": 1,
            "status": status,
            "target": coldhookTargetPath ?? coldhookPosArgs[0],
            "hooks": rows,
        ]
        let data = try JSONSerialization.data(withJSONObject: report,
                                              options: [.prettyPrinted, .sortedKeys])
        try data.write(to: URL(fileURLWithPath: path), options: .atomic)
    }

    func sharedDylibCommand(from image: MachO) -> Data? {
        var pos = 0x20
        let count = image.data.getGeneric(type: UInt32.self, offset: 0x10)
        for _ in 0..<count {
            let type = image.data.getGeneric(type: UInt32.self, offset: UInt(pos))
            let size = Int(image.data.getGeneric(type: UInt32.self, offset: UInt(pos + 4)))
            if type == UInt32(LC_ID_DYLIB), size >= 24 {
                var raw = image.data.subdata(in: pos..<(pos + size))
                raw.replaceSubrange(0..<4, with: Data(fromObject: UInt32(LC_LOAD_DYLIB)))
                // Shared hooks are bundled for sideloading.  Resolve the copied
                // runtime dylib relative to the application executable instead
                // of retaining Theos' jailbreak path (/Library/MobileSubstrate/...).
                let pathBytes = Array(raw.dropFirst(24))
                let end = pathBytes.firstIndex(of: 0) ?? pathBytes.count
                let fileName = String(bytes: pathBytes[..<end], encoding: .utf8) ?? "libcoldhook.dylib"
                let baseName = (fileName as NSString).lastPathComponent
                let bundledPath = coldhookImportPath ?? "@executable_path/Frameworks/\(baseName)"
                var encoded = Array(bundledPath.utf8) + [0]
                let capacity = size - 24
                if encoded.count <= capacity {
                    encoded += Array(repeating: 0, count: capacity - encoded.count)
                    raw.replaceSubrange(24..<size, with: Data(encoded))
                }
                return raw
            }
            pos += size
        }
        return nil
    }

    do {
        let assembly = try prepareColdhookSharedTarget(
            targetData: dataA,
            targetResolver: makeColdhookSymbolResolver(dataA.symtab),
            userHooksData: dataB,
            userHooksResolver: makeColdhookSymbolResolver(dataB.symtab),
            targetSelectors: coldhookBinarySelectors(
                path: coldhookTargetPath ?? coldhookPosArgs[0]))
        if assembly.plan.hooks.isEmpty {
            try writeMachO(a.data, to: coldhookPosArgs[2])
            try writeSharedReport(status: "no-applicable-hooks", hooks: [])
            print("Done! (shared-режим: no applicable hooks)")
            exit(0)
        }
        let sharedSections = try makeColdhookSharedSections(assembly.plan)
        let stubSegment = try makeColdhookSharedSegmentCommand(
            name: "__COLDHOOK_TEXT", vmAddr: assembly.plan.layout.stubVMAddr,
            fileOffset: assembly.plan.layout.stubFileOffset,
            vmSize: (assembly.plan.layout.stubSize + 0x3fff) & ~0x3fff, fileSize: assembly.plan.layout.stubSize,
            maxProt: VM_PROT_READ | VM_PROT_EXECUTE, initProt: VM_PROT_READ | VM_PROT_EXECUTE,
            sections: sharedSections["__COLDHOOK_TEXT"] ?? [])
        let dataSegment = try makeColdhookSharedSegmentCommand(
            name: "__COLDHOOK_DATA", vmAddr: assembly.plan.layout.tableVMAddr,
            fileOffset: assembly.plan.layout.tableFileOffset,
            vmSize: (assembly.plan.layout.tableSize + 0x3fff) & ~0x3fff, fileSize: assembly.plan.layout.tableSize,
            maxProt: VM_PROT_READ | VM_PROT_WRITE, initProt: VM_PROT_READ | VM_PROT_WRITE,
            sections: sharedSections["__COLDHOOK_DATA"] ?? [])
        let (segmentCount, segmentBytes) = generateColdhookSharedSegmentLoadCommands(assembly)
        let aFile = a.data
        guard let linkeditCommand = a.cmds.compactMap({ $0 as? Segment64LoadCommand }).first(where: { $0.name == "__LINKEDIT" }),
              let linkeditData = dataA.linkedit else {
            throw ColdhookSharedAssemblerError.missingSegment("__LINKEDIT")
        }
        let oldLinkeditOff = Int(linkeditCommand.fileOffset)
        let oldLinkeditEnd = oldLinkeditOff + Int(linkeditCommand.fileSize)
        var linkeditBytes = linkeditData

        // Two synthetic LC_SEGMENT_64 commands are inserted before the rebuilt
        // __LINKEDIT.  dyld requires chained_starts_in_image.seg_count to match
        // the complete segment-command count, even though neither new segment
        // contains fixups.  Expand the offset array and retain the growth point
        // so every later __LINKEDIT payload is shifted consistently below.
        var chainedFixupsOldEnd: Int? = nil
        var chainedFixupsGrowth = 0
        var scanPos = 0x20
        let scanCount = Int(aFile.getGeneric(type: UInt32.self, offset: 0x10))
        for _ in 0..<scanCount {
            let type = aFile.getGeneric(type: UInt32.self, offset: UInt(scanPos))
            let size = Int(aFile.getGeneric(type: UInt32.self, offset: UInt(scanPos + 4)))
            if type == UInt32(LC_DYLD_CHAINED_FIXUPS) {
                let dataOff = Int(aFile.getGeneric(type: UInt32.self, offset: UInt(scanPos + 8)))
                let dataSize = Int(aFile.getGeneric(type: UInt32.self, offset: UInt(scanPos + 12)))
                let relative = dataOff - oldLinkeditOff
                guard relative >= 0, relative + dataSize <= linkeditBytes.count,
                      let expanded = coldhookExpandChainedFixupsForSegments(
                          linkeditBytes.subdata(in: relative..<(relative + dataSize)),
                          addedSegments: 2) else {
                    throw ColdhookSharedAssemblerError.payloadNotContiguous("chained fixups")
                }
                linkeditBytes.replaceSubrange(relative..<(relative + dataSize), with: expanded)
                chainedFixupsGrowth = expanded.count - dataSize
                chainedFixupsOldEnd = dataOff + dataSize
                break
            }
            scanPos += size
        }
        let materializedEnd = assembly.targetData.segments.map { Int($0.0.fileOffset) + $0.1.count }.max() ?? aFile.count
        let payloadEnd = max(Int(assembly.plan.layout.stubFileOffset + assembly.plan.layout.stubSize),
                             Int(assembly.plan.layout.tableFileOffset + assembly.plan.layout.tableSize))
        let targetFileEnd = max(materializedEnd, payloadEnd)
        let linkeditOff = (max(targetFileEnd, aFile.count) + 0x3fff) & ~0x3fff
        let oldCount = Int(aFile.getGeneric(type: UInt32.self, offset: 0x10))
        var commands = Data(); var nonSegmentCommands = Data(); var ncmds = 0
        var pos = 0x20
        for _ in 0..<oldCount {
            let type = aFile.getGeneric(type: UInt32.self, offset: UInt(pos))
            let size = Int(aFile.getGeneric(type: UInt32.self, offset: UInt(pos + 4)))
            let raw = aFile.subdata(in: pos..<(pos + size))
            if type == UInt32(LC_SEGMENT_64) {
                var nameBytes = [UInt8](raw.subdata(in: 8..<24)); nameBytes.append(0)
                let name = String(cString: nameBytes)
                if name == "__LINKEDIT" { pos += size; continue }
                pos += size; continue
            }
            if type == UInt32(LC_RPATH) {
                // build-for-testing injects a runpath into BUILT_PRODUCTS_DIR;
                // retaining it makes dyld load the unpatched framework beside
                // the build products instead of the copy embedded in the app.
                let pathOffset = Int(raw.getGeneric(type: UInt32.self, offset: 8))
                if pathOffset >= 0 && pathOffset < raw.count {
                    let bytes = raw[pathOffset..<raw.count]
                    let end = bytes.firstIndex(of: 0) ?? raw.count
                    let path = String(decoding: raw[pathOffset..<end], as: UTF8.self)
                    if path.contains("Build/Products") {
                        pos += size
                        continue
                    }
                }
            }
            if type != UInt32(LC_CODE_SIGNATURE) && type != UInt32(LC_SEGMENT_SPLIT_INFO) {
                var patched = raw
                func shift(_ at: Int) {
                    let value = patched.getGeneric(type: UInt32.self, offset: UInt(at))
                    if Int(value) >= oldLinkeditOff && Int(value) < oldLinkeditEnd {
                        var relative = Int(value) - oldLinkeditOff
                        if let chainedFixupsOldEnd, Int(value) >= chainedFixupsOldEnd {
                            relative += chainedFixupsGrowth
                        }
                        patched.replaceSubrange(at..<(at + 4),
                                                with: Data(fromObject: UInt32(linkeditOff + relative)))
                    }
                }
                if type == UInt32(LC_DYLD_CHAINED_FIXUPS) {
                    shift(8)
                    if chainedFixupsGrowth != 0 {
                        let oldSize = patched.getGeneric(type: UInt32.self, offset: 12)
                        patched.replaceSubrange(12..<16,
                                                with: Data(fromObject: oldSize + UInt32(chainedFixupsGrowth)))
                    }
                } else if type == UInt32(LC_DYLD_EXPORTS_TRIE) ||
                          type == UInt32(LC_FUNCTION_STARTS) || type == UInt32(LC_DATA_IN_CODE) {
                    shift(8)
                }
                if type == UInt32(LC_DYLD_INFO) || type == UInt32(LC_DYLD_INFO_ONLY) {
                    shift(8); shift(16); shift(24); shift(32); shift(40)
                }
                if type == UInt32(LC_SYMTAB) { shift(8); shift(16) }
                // LC_DYSYMTAB contains file offsets into __LINKEDIT as well.
                // Shared mode keeps the target's existing symbol/indirect tables
                // verbatim, so every offset field must follow the relocated
                // __LINKEDIT.  The first four fields are symbol indexes/counts;
                // only the *_off fields below are file offsets.
                if type == UInt32(LC_DYSYMTAB) {
                    shift(32) // tocoff
                    shift(40) // modtaboff
                    shift(48) // extrefsymoff
                    shift(56) // indirectsymoff
                    shift(64) // extreloff
                    shift(72) // locreloff
                }
                nonSegmentCommands.append(patched); ncmds += 1
            }
            pos += size
        }
        var linkeditLC = segment_command_64(); linkeditLC.cmd = UInt32(LC_SEGMENT_64)
        linkeditLC.cmdsize = UInt32(MemoryLayout<segment_command_64>.size)
        setMachOName(&linkeditLC.segname, "__LINKEDIT")
		let vmEnd = assembly.targetData.segments.map { $0.0.vmAddr + $0.0.vmSize }.max() ?? 0
		// The newly synthesized segments are not part of targetData.segments.
		// Include their reserved VM ranges before placing __LINKEDIT; otherwise
		// dylibs/frameworks whose original __LINKEDIT ends at the next page get
		// an overlapping __LINKEDIT and __COLDHOOK_DATA.
		let coldhookVMEnd = max(
			assembly.plan.layout.stubVMAddr + ((assembly.plan.layout.stubSize + 0x3fff) & ~0x3fff),
			assembly.plan.layout.tableVMAddr + ((assembly.plan.layout.tableSize + 0x3fff) & ~0x3fff))
		let allVMEnd = max(vmEnd, coldhookVMEnd)
		linkeditLC.vmaddr = max(coldhookBase + UInt64(linkeditOff), (allVMEnd + 0x3fff) & ~0x3fff)
        linkeditLC.vmsize = UInt64((linkeditBytes.count + 0x3fff) & ~0x3fff)
        linkeditLC.fileoff = UInt64(linkeditOff); linkeditLC.filesize = UInt64(linkeditBytes.count)
        linkeditLC.maxprot = VM_PROT_READ; linkeditLC.initprot = VM_PROT_READ
        commands.append(segmentBytes); ncmds += segmentCount
        commands.append(stubSegment); commands.append(dataSegment); ncmds += 2
        commands.append(Data(fromObject: linkeditLC)); ncmds += 1
        if let dylib = sharedDylibCommand(from: b) { nonSegmentCommands.append(dylib); ncmds += 1 }
        commands.append(nonSegmentCommands)
        var header = mach_header_64(); header.magic = MH_MAGIC_64; header.cputype = CPU_TYPE_ARM64
        header.cpusubtype = Int32(bitPattern: a.cpuSubType); header.filetype = a.filetype.rawValue
        header.flags = aFile.getGeneric(type: UInt32.self, offset: 0x18)
        header.ncmds = UInt32(ncmds); header.sizeofcmds = UInt32(commands.count)
        var headerData = Data(fromObject: header); headerData.append(commands)
        let limit = Int(dataA.segments.first(where: { $0.0.name == "__TEXT" })?.0.sections.compactMap { $0.offset == 0 ? nil : UInt64($0.offset) }.min() ?? 0x4000)
        guard headerData.count <= limit else { throw ColdhookSharedAssemblerError.payloadNotContiguous("header") }
        var output = aFile
        if output.count < limit { output.append(Data(repeating: 0, count: limit - output.count)) }
        for (command, bytes) in assembly.targetData.segments where command.fileSize > 0 {
            // Segment bytes are written at the command's original file offset.
            let off = Int(command.fileOffset), end = off + bytes.count
            if output.count < end { output.append(Data(repeating: 0, count: end - output.count)) }
            output.replaceSubrange(off..<end, with: bytes)
        }
        for placement in try makeColdhookSharedPlacements(assembly.plan, originalTargetData: dataA) {
            let off = placement.fileOffset, end = off + placement.data.count
            if output.count < end { output.append(Data(repeating: 0, count: end - output.count)) }
            output.replaceSubrange(off..<end, with: placement.data)
        }
        if output.count < linkeditOff { output.append(Data(repeating: 0, count: linkeditOff - output.count)) }
        output.append(linkeditBytes)
        // __TEXT's segment bytes include the old header; install the new header last.
        output.replaceSubrange(0..<limit, with: headerData + Data(repeating: 0, count: limit - headerData.count))
        try writeMachO(output, to: coldhookPosArgs[2])
        try writeSharedReport(status: "patched", hooks: assembly.plan.hooks)
        print("Done! (shared-режим: \(assembly.plan.hooks.count) hook(s))")
    } catch ColdhookSharedAssemblerError.noApplicableHooks {
        do {
            try writeMachO(a.data, to: coldhookPosArgs[2])
            try writeSharedReport(status: "no-applicable-hooks", hooks: [])
            print("Done! (shared-режим: no applicable hooks)")
        } catch { print("shared report: \(error)"); exit(-1) }
    } catch { print("shared: \(error)"); exit(-1) }
    exit(0)
}

// ColdHook: APPEND-режим. Реальный таргет A (приложение или framework-dylib) идёт БЕЗ
// LC_SEGMENT_SPLIT_INFO — мёрджер не может его релоцировать. Поэтому A НЕ двигаем (offset 0,
// фиксапы/symtab/entry валидны как есть), а сегменты хука B аппендим ПОСЛЕ A на новые vmaddr'ы.
// Заголовок переписываем в пределах существующего padding A (между LC и первой секцией).
// B (наш хук) собираем сами и ВСЕГДА со split-info — его релоцируем штатно.
// ColdHook: режим слияния. auto -> по split-info цели (нет split-info => append, иначе interleave).
// append форсит дозапись (работает на любой цели). interleave форсит стелс-слияние и ПАДАЕТ, если
// у цели нет split-info — релоцировать её сегменты нечем (тихий фолбэк маскировал бы ошибку выбора).
let coldhookAppendMode: Bool
switch coldhookModeArg {
case "append":
    coldhookAppendMode = true
case "interleave":
    guard dataA.splitInfo != nil else {
        print("--mode interleave невозможен: у цели нет LC_SEGMENT_SPLIT_INFO (релоцировать нечем). "
            + "Используй --mode auto или --mode append.")
        exit(-1)
    }
    coldhookAppendMode = false
default:   // auto
    coldhookAppendMode = (dataA.splitInfo == nil)
}
if coldhookAppendMode && dataB.splitInfo == nil {
    print("ColdHook: append-режим (таргет A без split-info), но и у хука B нет split-info. "
        + "Пересобери хук с -Xlinker -add_split_seg_info.")
    exit(-1)
}

// Patch out magic of both MachOs
// Fixes issues with some third party software (e.g. Frida) finding the wrong place and mistaking it for the header
// Of course the root issue is in third party software, but I guess we can make their life easier
let magicReplacement = UInt32(0xd0d0d0d0)

/*
 * Now comes the real magic: Merging the MachOs.
 * To do this, the following steps have to be performed:
 * 1. Merge all the segments and generate appropriate reloc information
 *    Relocation information will simply be section -> offset
 */

// Segments with the same name will be merged
// We will output segments in the following order: r-x r-- rw-

var segments: [(String, [(isB: Bool, origCommand: Segment64LoadCommand, data: Data, offset: UInt64)])] = []
for seg in dataA.segments {
    guard !segments.contains(where: { $0.0 == seg.0.name }) else {
        print("Found duplicate segment! [A]")
        exit(-1)
    }

    var data = seg.1

    if seg.0.name == "__TEXT" {
        data = Data(fromObject:magicReplacement) + data.subdata(in: 4..<data.count)
    }
    
    segments.append((seg.0.name, [(isB: false, origCommand: seg.0, data: data, offset: 0)]))
}

var sortingRequired = false

for seg in dataB.segments {
    var data = seg.1

    if seg.0.name == "__TEXT" {
        data = Data(fromObject:magicReplacement) + data.subdata(in: 4..<data.count)
    }

    let newEntry = [(isB: true, origCommand: seg.0, data: data, offset: 0 as UInt64)]

    if coldhookAppendMode {
        // A не трогаем — сегменты B идут ОТДЕЛЬНЫМИ записями после A (не мёрджим по имени).
        // Переименовываем (__TEXT -> __BTEXT и т.п.): имена сегментов косметические (код B
        // адресуется по vmaddr), но уникальность нужна — иначе replaceSegment/forName по имени
        // находят сегмент A. Длина +1 символ, влезает в 16.
        let renamed = "__B" + seg.0.name.dropFirst(2)
        segments.append((String(renamed), newEntry))
        continue
    }

    var found = false
    var new: [(String, [(isB: Bool, origCommand: Segment64LoadCommand, data: Data, offset: UInt64)])] = []
    for s in segments {
        if s.0 == seg.0.name {
            new.append((s.0, s.1 + newEntry))
            found = true
        } else {
            new.append(s)
        }
    }

    if !found {
        new.append((seg.0.name, newEntry))
        sortingRequired = true
    }

    segments = new
}

func compareProt(_ a: VMProt, b: VMProt) -> Bool? {
    if a.rawValue == b.rawValue {
        return nil
    } else if a.rawValue == (VM_PROT_READ | VM_PROT_EXECUTE) {
        return true
    } else if a.rawValue == VM_PROT_READ && b.rawValue == (VM_PROT_READ | VM_PROT_WRITE) {
        return true
    }
    
    return false
}

guard !sortingRequired else {
    print("FIXME: sortingRequired not implemented!")
    exit(-1)
}

// Relocate segments
// ColdHook: для исполняемого пакуем контент от базы (0x100000000) + 0x4000 под заголовок;
// __PAGEZERO остаётся на vmaddr 0 и в упаковке не участвует. Для dylib — как было (с 0x4000).
var nSegments: [(String, [(isB: Bool, origCommand: Segment64LoadCommand, data: Data, offset: UInt64)])] = []
if coldhookAppendMode {
    // A не двигаем (offset 0). B пакуем на новые vmaddr'ы после максимального конца сегмента A
    // (контент остаётся base+fileoff-контигуальным, поэтому fileoff B = vmaddr B - base).
    var aMaxEnd: UInt64 = coldhookBase + 0x4000
    for seg in segments where !seg.1[0].isB && seg.0 != "__PAGEZERO" {
        aMaxEnd = max(aMaxEnd, seg.1[0].origCommand.vmAddr &+ seg.1[0].origCommand.vmSize)
    }
    var curReloc = (aMaxEnd + pageMaskOff) & pageMask
    for var seg in segments {
        if !seg.1[0].isB {
            seg.1[0].offset = 0   // сегмент A остаётся на исходном vmaddr
        } else {
            seg.1[0].offset = curReloc &- seg.1[0].origCommand.vmAddr
            curReloc += seg.1[0].origCommand.vmSize
            curReloc = (curReloc + pageMaskOff) & pageMask
        }
        nSegments.append(seg)
    }
} else {
    var curReloc: UInt64 = coldhookBase + 0x4000 // Reserve some space for our new header
    for var seg in segments {
        if seg.0 == "__PAGEZERO" {
            seg.1[0].offset = 0   // остаётся на vmaddr 0, контент не двигаем
            nSegments.append(seg)
            continue
        }
        let origVM = seg.1[0].origCommand.vmAddr
        seg.1[0].offset = curReloc &- origVM

        curReloc += seg.1[0].origCommand.vmSize
        curReloc = (curReloc + pageMaskOff) & pageMask

        if seg.1.count == 2 {
            let origVM = seg.1[1].origCommand.vmAddr
            seg.1[1].offset = curReloc &- origVM

            curReloc += seg.1[1].origCommand.vmSize
            curReloc = (curReloc + pageMaskOff) & pageMask
        }

        nSegments.append(seg)
    }
}

let relocInfo = RelocInfo(segRel: nSegments)

// Okay, we've relocated the segments
// Now we'll need to fix them
fixupViaSplitInfo(infoA: dataA, infoB: dataB, relocInfo: relocInfo)

// The segments themselfes are fixed now
// What's left is essentially chained fixups and a few others
let newChainedFixups = mergeChainedFixups(infoA: dataA, infoB: dataB, relocInfo: relocInfo, machOA: a, machOB: b)

// ColdHook: первая инструкция цели сохраняется в ORIG-слот (чтобы хук мог звать оригинал).
// Если она PC-relative (cbz/cbnz/tbz/b.cond/b/adr/adrp — частые прологи Swift на guard'ах
// первого аргумента), её НАДО переэнкодить под адрес слота: относительный таргет иначе
// уедет. Возвращает переэнкоженную инструкцию; не-PC-relative — без изменений. Таргет ветки
// транслируется A->merged (для append A не двигается -> tr тождественна). Если новый offset
// не влезает в формат — оставляем как есть (лучше, чем мусор; такой пролог редок).
func coldhookReencodeForSlot(_ insn: UInt32, fromAddr: UInt64, slot: UInt64) -> UInt32 {
    func sx(_ v: UInt32, _ bits: Int) -> Int64 { let s = 64 - bits; return Int64(bitPattern: UInt64(v) << s) >> s }
    func tr(_ a: UInt64) -> Int64 { Int64(bitPattern: relocInfo.translate(address: a, isB: false)) }
    let pc = Int64(bitPattern: fromAddr), slotI = Int64(bitPattern: slot)

    if insn & 0xFC000000 == 0x14000000 || insn & 0xFC000000 == 0x94000000 {   // B / BL (imm26*4)
        let d = tr(UInt64(bitPattern: pc + sx(insn & 0x03FFFFFF, 26) * 4)) - slotI
        guard d & 3 == 0, (d >> 2) >= -(1 << 25), (d >> 2) < (1 << 25) else { return insn }
        return (insn & 0xFC000000) | UInt32(UInt64(bitPattern: d >> 2) & 0x03FFFFFF)
    }
    if insn & 0xFF000010 == 0x54000000 || insn & 0x7E000000 == 0x34000000 || insn & 0x3B000000 == 0x18000000 {
        // B.cond / CBZ / CBNZ / LDR-literal (imm19 в [23:5], *4)
        let d = tr(UInt64(bitPattern: pc + sx((insn >> 5) & 0x7FFFF, 19) * 4)) - slotI
        guard d & 3 == 0, (d >> 2) >= -(1 << 18), (d >> 2) < (1 << 18) else { return insn }
        return (insn & ~(UInt32(0x7FFFF) << 5)) | (UInt32(UInt64(bitPattern: d >> 2) & 0x7FFFF) << 5)
    }
    if insn & 0x7E000000 == 0x36000000 {   // TBZ / TBNZ (imm14 в [18:5], *4)
        let d = tr(UInt64(bitPattern: pc + sx((insn >> 5) & 0x3FFF, 14) * 4)) - slotI
        guard d & 3 == 0, (d >> 2) >= -(1 << 13), (d >> 2) < (1 << 13) else { return insn }
        return (insn & ~(UInt32(0x3FFF) << 5)) | (UInt32(UInt64(bitPattern: d >> 2) & 0x3FFF) << 5)
    }
    if insn & 0x9F000000 == 0x10000000 || insn & 0x9F000000 == 0x90000000 {   // ADR / ADRP
        let isAdrp = insn & 0x80000000 != 0
        let imm21 = (((insn >> 5) & 0x7FFFF) << 2) | ((insn >> 29) & 0x3)
        let target = (isAdrp ? (pc & ~0xFFF) : pc) + (sx(imm21, 21) << (isAdrp ? 12 : 0))
        let tm = tr(UInt64(bitPattern: target))
        let d = isAdrp ? (((tm & ~0xFFF) - (slotI & ~0xFFF)) >> 12) : (tm - slotI)
        guard d >= -(1 << 20), d < (1 << 20) else { return insn }
        let v = UInt32(UInt64(bitPattern: d) & 0x1FFFFF)
        return (insn & ~((UInt32(0x3) << 29) | (UInt32(0x7FFFF) << 5))) | ((v & 0x3) << 29) | (((v >> 2) & 0x7FFFF) << 5)
    }
    return insn
}

// Generate trampolines
// Магик-символы хука и резолв по имени — через СЫРОЙ разбор symtab (nlist_64), а НЕ через
// SwiftMachO.getSymbolTable: тот падает (BadFormat) на symtab реальных и Swift-бинарей, из-за
// чего magic-символы `_COLDHOOK_*` не находились и патч молча не применялся.
// Резолв имени A учитывает только DEFINED-символы (N_SECT); by-offset (_COLDHOOK_ADDR) его не требует.
let bSymbolResolver = makeColdhookSymbolResolver(dataB.symtab)
let aSymbolResolver = makeColdhookSymbolResolver(dataA.symtab)
let bSyms = bSymbolResolver.symbols
let aSyms = aSymbolResolver.symbols
func aSym(_ name: String) -> ColdhookSym? { aSymbolResolver.first(name, definedOnly: true) }
if !bSyms.isEmpty {
    for sym in bSyms {
        if sym.name.starts(with: "_MACHOMERGER_TRAMPOLINE_") {
            let dstName = sym.name.replacingOccurrences(of: "_MACHOMERGER_TRAMPOLINE", with: "")
            
            var dstAddr: UInt64!
            if let d = getMagicSymbolVal(dstName) {
                dstAddr = d.0
            } else if let d = aSym(dstName) {
                dstAddr = d.value
            }
            
            guard dstAddr != nil else {
                print("Cannot resolve symbol \(dstName)")
                exit(-1)
            }
            
            // Generate instruction
            let at = relocInfo.translate(address: sym.value, isB: true)
            let to = relocInfo.translate(address: dstAddr, isB: false)
            
            let instr: UInt32
            do { instr = try encodeColdhookB(from: at, to: to) }
            catch { print("Cannot generate trampoline: \(error)"); exit(-1) }
            
            // Write it
            let seg = relocInfo.segment(forOrigAddress: sym.value, isB: true)!
            let off = Int(seg.3)
            var data = seg.1
            data = data.subdata(in: 0..<off) + Data(fromObject: instr) + data.subdata(in: (off + 4)..<data.count)
            relocInfo.replaceSegment(name: seg.0, isB: true, data: data)
        } else if sym.name.starts(with: "_COLDHOOK_TRAMPOLINE_SYM_") || sym.name.starts(with: "_COLDHOOK_TRAMPOLINE_ADDR_") {
            let dstName: String
            if sym.name.starts(with: "_COLDHOOK_TRAMPOLINE_SYM_") {
                dstName = "_" + String(sym.name.dropFirst("_COLDHOOK_TRAMPOLINE_SYM_".count))
            } else {
                dstName = "_COLDHOOK_ADDR_" + String(sym.name.dropFirst("_COLDHOOK_TRAMPOLINE_ADDR_".count))
            }
            
            var dstAddr: UInt64!
            if let d = getMagicSymbolVal(dstName) {
                dstAddr = d.0
            } else if let d = aSym(dstName) {
                dstAddr = d.value
            }
            
            guard dstAddr != nil else {
                print("Cannot resolve symbol \(dstName)")
                exit(-1)
            }
            
            // Generate instruction
            let at = relocInfo.translate(address: sym.value, isB: true)
            let to = relocInfo.translate(address: dstAddr, isB: false) + 4
            
            let instr: UInt32
            do { instr = try encodeColdhookB(from: at, to: to) }
            catch { print("Cannot generate trampoline: \(error)"); exit(-1) }
            
            // Write it
            let seg = relocInfo.segment(forOrigAddress: sym.value, isB: true)!
            let off = Int(seg.3)
            var data = seg.1
            data = data.subdata(in: 0..<off) + Data(fromObject: instr) + data.subdata(in: (off + 4)..<data.count)
            relocInfo.replaceSegment(name: seg.0, isB: true, data: data)
        } else if sym.name.starts(with: "_COLDHOOK_SYM_") || sym.name.starts(with: "_COLDHOOK_ADDR_") {
            let dstName: String
            let origName: String
            if sym.name.starts(with: "_COLDHOOK_SYM_") {
                let suffix = String(sym.name.dropFirst("_COLDHOOK_SYM_".count))
                dstName = "_" + suffix
                origName = "_COLDHOOK_ORIG_SYM_" + suffix
            } else {
                let suffix = String(sym.name.dropFirst("_COLDHOOK_ADDR_".count))
                dstName = "_COLDHOOK_ADDR_" + suffix
                origName = "_COLDHOOK_ORIG_ADDR_" + suffix
            }
            
            var dstAddr: UInt64!
            if let d = getMagicSymbolVal(dstName) {
                dstAddr = d.0
            } else if let d = aSym(dstName) {
                dstAddr = d.value
            }

            var origAddr: UInt64!
            if let o = bSyms.first(where: { $0.name == origName }) {
                origAddr = o.value
            }
            
            guard dstAddr != nil else {
                print("Cannot resolve symbol \(dstName)")
                exit(-1)
            }
            
            // Generate instruction
            let to = relocInfo.translate(address: sym.value, isB: true)
            let at = relocInfo.translate(address: dstAddr, isB: false)
            
            let instr: UInt32
            do { instr = try encodeColdhookB(from: at, to: to) }
            catch { print("Cannot generate trampoline: \(error)"); exit(-1) }
            
            // Write it
            let seg = relocInfo.segment(forOrigAddress: dstAddr, isB: false)!
            let off = Int(seg.3)
            var data = seg.1
            let origInsn = data.subdata(in: off..<off+4).withUnsafeBytes { $0.load(as: UInt32.self) }
            data = data.subdata(in: 0..<off) + Data(fromObject: instr) + data.subdata(in: (off + 4)..<data.count)
            relocInfo.replaceSegment(name: seg.0, isB: false, data: data)

            if origAddr != nil {
                // Сохраняем первую инструкцию цели в ORIG-слот. PC-relative переэнкодим под
                // адрес слота (coldhookReencodeForSlot) — раньше копировалась как есть и при
                // pc-relative прологе (cbz/cbnz/tbz/...) ORIG уводил не туда.
                let origSeg = relocInfo.segment(forOrigAddress: origAddr, isB: true)!
                let origOff = Int(origSeg.3)
                var origData = origSeg.1

                let slotMerged = relocInfo.translate(address: origAddr, isB: true)
                let savedInsn = coldhookReencodeForSlot(origInsn, fromAddr: dstAddr, slot: slotMerged)
                origData = origData.subdata(in: 0..<origOff) + Data(fromObject: savedInsn) + origData.subdata(in: (origOff + 4)..<origData.count)
                relocInfo.replaceSegment(name: origSeg.0, isB: true, data: origData)
            }
        }
    }
}

// ColdHook: слияние __TEXT,__init_offsets (S_INIT_FUNC_OFFSETS) таргета A и хука B.
// Современный clang кладёт конструкторы (%ctor / __attribute__((constructor))) сюда —
// массив 32-битных image-base offset'ов на init-функции. Если такая секция есть И у A, И у B,
// dyld4 мисхэндлит две секции этого типа (запускает первую, прыгает в мусор -> SIGILL).
// Решение: слить записи B в секцию A, оставив ОДНУ init-секцию. На этом этапе (после
// fixupViaSplitInfo + трамплинов) записи A и B уже содержат корректные merged image-offset'ы.
// Объединённый массив кладём в мёртвую область старого заголовка B (начало __TEXT B,
// затёртое magic'ом и больше нигде не используемое), перенацеливаем заголовок секции A туда
// (см. generateSegmentLoadCommands), а секцию B нейтрализуем (тип -> S_REGULAR).
struct ColdhookInitMerge {
    var combinedVMAddr: UInt64   // merged vmaddr объединённого массива (туда смотрит секция A)
    var combinedSize: UInt64     // размер объединённого массива, байт
}
var coldhookInitMerge: ColdhookInitMerge? = nil

func coldhookFindInitOffsets(isB: Bool) -> (seg: String, dataOff: Int, size: Int)? {
    for seg in relocInfo.segRel {
        let part: (isB: Bool, origCommand: Segment64LoadCommand, data: Data, offset: UInt64)
        if !isB {
            part = seg.1[0]
            guard !part.isB else { continue }
        } else {
            part = (seg.1.count == 2) ? seg.1[1] : seg.1[0]
            guard part.isB else { continue }
        }
        for sect in part.origCommand.sections {
            if sect.section == "__init_offsets" && (sect.flags.rawValue & 0xff) == 0x16 {
                let dataOff = Int(sect.address &- part.origCommand.vmAddr)
                return (seg.0, dataOff, Int(sect.size))
            }
        }
    }
    return nil
}

func coldhookMergeInitOffsets() {
    guard let aInit = coldhookFindInitOffsets(isB: false),
          let bInit = coldhookFindInitOffsets(isB: true) else {
        return  // 0 или 1 init-секция -> сливать нечего, текущее поведение
    }

    guard let (aData, _) = relocInfo.segment(forName: aInit.seg, isB: false),
          let (bData, _) = relocInfo.segment(forName: bInit.seg, isB: true) else {
        print("ColdHook: не нашёл сегменты для слияния __init_offsets"); exit(-1)
    }
    let aEntries = aData.subdata(in: aInit.dataOff..<(aInit.dataOff + aInit.size))
    let bEntries = bData.subdata(in: bInit.dataOff..<(bInit.dataOff + bInit.size))
    let combined = aEntries + bEntries

    // Мёртвая область = старый заголовок B в начале сегмента с её __init_offsets (= __TEXT B).
    // Берём по имени bInit.seg (в append-режиме это переименованный __BTEXT), именно isB-часть.
    guard let bTextPart = relocInfo.segRel
            .first(where: { $0.0 == bInit.seg && $0.1.contains(where: { $0.isB }) })?
            .1.first(where: { $0.isB }) else {
        print("ColdHook: сегмент B '\(bInit.seg)' не найден — не могу слить __init_offsets"); exit(-1)
    }
    let bTextVM = bTextPart.origCommand.vmAddr &+ bTextPart.offset
    let firstSect = bTextPart.origCommand.sections.map { $0.address }.min() ?? bTextPart.origCommand.vmAddr
    let deadSize = Int(firstSect &- bTextPart.origCommand.vmAddr)
    guard combined.count <= deadSize else {
        print("ColdHook: объединённый __init_offsets (\(combined.count) б) не влез в мёртвую область B (\(deadSize) б)")
        exit(-1)
    }

    var nb = bTextPart.data
    nb.replaceSubrange(0..<combined.count, with: combined)
    relocInfo.replaceSegment(name: bInit.seg, isB: true, data: nb)

    coldhookInitMerge = ColdhookInitMerge(combinedVMAddr: bTextVM, combinedSize: UInt64(combined.count))
    print("ColdHook: слил __init_offsets A+B (\(aInit.size + bInit.size) б) в мёртвую область B @ \(String(format: "0x%llx", bTextVM))")
}
// __init_offsets merging belongs to append/interleave assembly. Shared mode
// emits its own metadata segments and must not reuse append's VM-address
// relocation (it can underflow when target and hook use different bases).
if coldhookModeArg != "shared" {
    coldhookMergeInitOffsets()
}

// ColdHook: APPEND-сборка. Таргет A остаётся на месте (vmaddr/fileoff/фиксапы/entry как есть),
// сегменты хука B аппендятся после контента A, новый заголовок переписываем В ПРЕДЕЛАХ padding A
// (между концом LC и первой секцией). Единственный путь для реальных бинарей (они без split-info).
// Стратегия размещения изолирована в этой функции: при нехватке padding — внятная ошибка, точка
// под запасные варианты (отдельный хвостовой сегмент / shared-режим: хук по либе с бОльшим запасом).
func coldhookAppendAssemble(targetDataInput: MachOMergeData = dataA,
                            hookDataInput: MachOMergeData = dataB,
                            relocInfoInput: RelocInfo = relocInfo) -> Data {
    // Keep the historical implementation intact while allowing shared mode to
    // reuse its header/segment/__LINKEDIT rebuild path.
    let dataA = targetDataInput
    let dataB = hookDataInput
    let relocInfo = relocInfoInput
    let aFile = a.data
    let ncmdsA = aFile.getGeneric(type: UInt32.self, offset: 0x10)

    guard let aText = dataA.segments.first(where: { $0.0.name == "__TEXT" }) else {
        print("ColdHook: у таргета нет __TEXT"); exit(-1)
    }
    // header region = [0, headerLimit): до первой ненулевой секции __TEXT (туда пишем новый заголовок)
    let headerLimit = Int(aText.0.sections.compactMap { $0.offset == 0 ? nil : UInt64($0.offset) }.min() ?? 0x4000)
    // конец контента A = где начинался __LINKEDIT (после A аппендим B)
    let aContentEnd = Int(dataA.segments.map { $0.0.fileOffset + $0.0.fileSize }.max() ?? 0)

    // --- Разбор LC таргета A: сегменты (вербатим) + прочее (вербатим); LE-указатели и подпись дропаем ---
    var aSegmentLCs: [Data] = []   // PAGEZERO/TEXT/DATA_CONST/DATA вербатим, в исходном порядке
    var otherLCs: [Data] = []      // LC_MAIN, LC_LOAD_DYLINKER, dylib A, UUID, BUILD_VERSION, RPATH, ID_DYLIB...
    var pos = 0x20
    for _ in 0..<ncmdsA {
        let cmd = aFile.getGeneric(type: UInt32.self, offset: UInt(pos))
        let sz  = Int(aFile.getGeneric(type: UInt32.self, offset: UInt(pos + 4)))
        let raw = aFile.subdata(in: pos..<(pos + sz))
        if cmd == LC_SEGMENT_64 {
            var nameBytes = [UInt8](raw.subdata(in: 8..<24)); nameBytes.append(0)
            if String(cString: nameBytes) != "__LINKEDIT" { aSegmentLCs.append(raw) }  // __LINKEDIT пересоберём
        } else if cmd == LC_SYMTAB || cmd == LC_DYSYMTAB || cmd == LC_DYLD_CHAINED_FIXUPS
               || cmd == LC_FUNCTION_STARTS || cmd == LC_DATA_IN_CODE || cmd == LC_CODE_SIGNATURE
               || cmd == LC_SEGMENT_SPLIT_INFO || cmd == LC_DYLD_EXPORTS_TRIE
               || cmd == 0x80000022 /*LC_DYLD_INFO_ONLY*/ || cmd == 0x22 /*LC_DYLD_INFO*/ {
            // дропаем — пересоберём ниже или не нужно
        } else {
            otherLCs.append(raw)
        }
        pos += sz
    }

    // ColdHook: dyld требует SG_READ_ONLY (0x10) на __DATA_CONST/__AUTH_CONST у ОБЫЧНОГО (не-кэш)
    // образа. Корень бага: таргет линкуется с -add_split_seg_info (нужно мёрджеру) -> ld считает его
    // кандидатом в dyld shared cache и НЕ ставит SG_READ_ONLY (для кэша read-only накладывает сборщик
    // кэша постранично, флаг был бы избыточен). Одиночный split-seg dylib dyld грузит снисходительно.
    // Но мы ВЫБРАСЫВАЕМ LC_SEGMENT_SPLIT_INFO (см. drop-лист LC выше) -> на выходе обычный dylib, у
    // которого __DATA_CONST без флага -> строгая проверка dyld -> отказ ("__DATA_CONST segment missing
    // SG_READ_ONLY flag"). Раз сняли split-info и сделали образ обычным — обязаны вернуть и флаг.
    // Проставляем на сегментах A; у B флаг СНИМАЕТСЯ (~767) -> read-only регион ровно один, ядро не
    // ругается на «второй несмежный». Если у A флаг уже был — |= 0x10 это no-op.
    for i in 0..<aSegmentLCs.count {
        var nb = [UInt8](aSegmentLCs[i].subdata(in: 8..<24)); nb.append(0)
        let name = String(cString: nb)
        if name == "__DATA_CONST" || name == "__AUTH_CONST" {
            var lc = aSegmentLCs[i]
            let flags = lc.getGeneric(type: UInt32.self, offset: 0x44)
            lc.replaceSubrange(0x44..<0x48, with: Data(fromObject: flags | 0x10))
            aSegmentLCs[i] = lc
        }
    }

    // ColdHook: если сливали __init_offsets A+B (оба с конструкторами) — здесь LC сегментов A
    // копируются ВЕРБАТИМ, поэтому секцию __init_offsets A надо перенацелить на объединённый
    // массив РУЧНО (в interleave это делает generateSegmentLoadCommands, который мы не зовём).
    if let im = coldhookInitMerge {
        for i in 0..<aSegmentLCs.count {
            var lc = aSegmentLCs[i]
            let segName = lc.subdata(in: 8..<24)
            guard segName.first(where: { $0 != 0 }) != nil else { continue }
            let nsects = lc.getGeneric(type: UInt32.self, offset: 0x40)
            var patched = false
            for s in 0..<Int(nsects) {
                let so = 0x48 + s * 0x50
                let nm = lc.subdata(in: so..<(so + 16))
                let isInit = nm.prefix("__init_offsets".utf8.count).elementsEqual("__init_offsets".utf8)
                let typ = lc.getGeneric(type: UInt32.self, offset: UInt(so + 64)) & 0xff
                if isInit && typ == 0x16 {
                    lc.replaceSubrange((so + 32)..<(so + 40), with: Data(fromObject: im.combinedVMAddr))   // addr
                    lc.replaceSubrange((so + 40)..<(so + 48), with: Data(fromObject: im.combinedSize))      // size
                    lc.replaceSubrange((so + 48)..<(so + 52), with: Data(fromObject: UInt32(im.combinedVMAddr &- coldhookBase))) // offset
                    patched = true
                }
            }
            if patched { aSegmentLCs[i] = lc }
        }
    }

    // --- LC сегментов B + их размещение в файле ---
    var bSegmentLCs: [Data] = []
    var bPlacements: [(fileOff: Int, data: Data)] = []
    var bodyEnd = aContentEnd
    var bMaxVMEnd = coldhookBase &+ UInt64(aContentEnd)   // макс VM-конец B (для vmaddr __LINKEDIT)
    for entry in relocInfo.segRel where entry.1[0].isB {
        let part = entry.1[0]
        let newVM   = part.origCommand.vmAddr &+ part.offset
        let fileOff = Int(newVM &- coldhookBase)
        bMaxVMEnd = max(bMaxVMEnd, newVM &+ part.origCommand.vmSize)   // vmSize >= filesize (bss)

        var slc = segment_command_64()
        slc.cmd = UInt32(LC_SEGMENT_64)
        let nsects = part.origCommand.sections.count
        slc.cmdsize = UInt32(MemoryLayout<segment_command_64>.size + nsects * MemoryLayout<section_64>.size)
        setMachOName(&slc.segname, entry.0)
        slc.vmaddr   = newVM
        slc.vmsize   = part.origCommand.vmSize
        slc.fileoff  = UInt64(fileOff)
        slc.filesize = UInt64(part.data.count)
        slc.maxprot  = Int32(bitPattern: part.origCommand.maximumProt.rawValue)
        slc.initprot = Int32(bitPattern: part.origCommand.protection.rawValue)
        slc.nsects   = UInt32(nsects)
        // ВАЖНО: снимаем SG_READ_ONLY (0x10) с сегментов B. Ядро/dyld трактуют read-only
        // сегменты как единый непрерывный __DATA_CONST-регион; ВТОРОЙ несмежный SG_READ_ONLY
        // (наш __BDATA_CONST после __BTEXT) ядро отвергает на exec как EBADMACHO. В interleave
        // этого нет — там __DATA_CONST A и B сливаются в один сегмент. Без флага const-данные
        // хука просто не хардненятся read-only; фиксапы применяются как обычно.
        slc.flags    = part.origCommand.flags & ~UInt32(0x10)
        var sectionData: [section_64] = []
        for sect in part.origCommand.sections {
            var s = section_64()
            setMachOName(&s.sectname, sect.section)
            setMachOName(&s.segname, entry.0)
            s.addr   = sect.address &+ part.offset
            s.size   = sect.size
            s.offset = (sect.offset == 0) ? 0 : UInt32(s.addr &- coldhookBase)
            s.align  = coldhookSectionAlignment(sect.alignment)
            s.flags  = sect.flags.rawValue
            s.reserved1 = sect.reserved1
            s.reserved2 = sect.reserved2
            s.reserved3 = sect.reserved3
            // нейтрализация __init_offsets B (записи уже в объединённой секции A — см. coldhookMergeInitOffsets)
            if coldhookInitMerge != nil, sect.section == "__init_offsets", (sect.flags.rawValue & 0xff) == 0x16 {
                s.flags = sect.flags.rawValue & ~UInt32(0xff)
            }
            sectionData.append(s)
        }
        let lc = try! makeAppendedSegmentCommand(
            name: entry.0, vmAddr: newVM, fileOffset: UInt64(fileOff),
            vmSize: part.origCommand.vmSize, fileSize: UInt64(part.data.count),
            maxProt: Int32(bitPattern: part.origCommand.maximumProt.rawValue),
            initProt: Int32(bitPattern: part.origCommand.protection.rawValue),
            sections: sectionData, flags: part.origCommand.flags & ~UInt32(0x10))
        bSegmentLCs.append(lc)
        bPlacements.append((fileOff, part.data))
        bodyEnd = max(bodyEnd, fileOff + part.data.count)
    }

    // --- merged __LINKEDIT (A не двигали -> его trie/function-starts валидны вербатим) ---
    let linkeditFileOff = Int((UInt64(bodyEnd) + pageMaskOff) & pageMask)
    var linkedit = Data()
    func pad8() { let r = linkedit.count & 7; if r != 0 { linkedit.append(Data(repeating: 0, count: 8 - r)) } }

    let cfOff = linkeditFileOff + linkedit.count
    linkedit.append(newChainedFixups); pad8()
    var trieOff = 0, trieSize = 0
    if let trie = dataA.exportsTrie, trie.count > 0 { trieOff = linkeditFileOff + linkedit.count; linkedit.append(trie); trieSize = trie.count; pad8() }
    var fsOff = 0, fsSize = 0
    if let fs = dataA.functionStarts, fs.count > 0 { fsOff = linkeditFileOff + linkedit.count; linkedit.append(fs); fsSize = fs.count; pad8() }
    var dcOff = 0, dcSize = 0
    if let dc = dataA.dataInCode, dc.count > 0 { dcOff = linkeditFileOff + linkedit.count; linkedit.append(dc); dcSize = dc.count; pad8() }
    let (symCount, symCmds) = emitSymtabDysymtab(infoA: dataA, infoB: dataB, relocInfo: relocInfo, linkedit: &linkedit, linkeditStart: linkeditFileOff)

    func leCmd(_ type: UInt32, _ dataoff: Int, _ datasize: Int) -> Data {
        var d = Data(fromObject: type)
        d.appendGeneric(value: UInt32(0x10))
        d.appendGeneric(value: UInt32(dataoff))
        d.appendGeneric(value: UInt32(datasize))
        return d
    }
    var leLCs = Data(); var leCount = 0
    leLCs.append(leCmd(LC_DYLD_CHAINED_FIXUPS, cfOff, newChainedFixups.count)); leCount += 1
    if trieSize > 0 { leLCs.append(leCmd(LC_DYLD_EXPORTS_TRIE, trieOff, trieSize)); leCount += 1 }
    if fsSize   > 0 { leLCs.append(leCmd(UInt32(LC_FUNCTION_STARTS), fsOff, fsSize)); leCount += 1 }
    if dcSize   > 0 { leLCs.append(leCmd(UInt32(LC_DATA_IN_CODE), dcOff, dcSize)); leCount += 1 }
    leLCs.append(symCmds); leCount += symCount

    var leSeg = segment_command_64()
    leSeg.cmd = UInt32(LC_SEGMENT_64)
    leSeg.cmdsize = UInt32(MemoryLayout<segment_command_64>.size)
    setMachOName(&leSeg.segname, "__LINKEDIT")
    // vmaddr linkedit развязан от файлового офсета: кладём ЗА максимальный VM-конец сегментов B.
    // Слайд по сегментам может отличаться (vmaddr-fileoff не обязан быть константой), а у B-данных
    // bss даёт vmsize > filesize — без этого __BDATA по VM налезал на __LINKEDIT ('vm range overlaps').
    leSeg.vmaddr   = max(coldhookBase &+ UInt64(linkeditFileOff), (bMaxVMEnd &+ pageMaskOff) & pageMask)
    leSeg.vmsize   = (UInt64(linkedit.count) + pageMaskOff) & pageMask
    leSeg.fileoff  = UInt64(linkeditFileOff)
    leSeg.filesize = UInt64(linkedit.count)
    leSeg.maxprot  = VM_PROT_READ
    leSeg.initprot = VM_PROT_READ
    leSeg.nsects   = 0
    leSeg.flags    = 0

    // --- LC по порядку: сегменты [A..., B..., __LINKEDIT], затем прочее + новые dylib + LE-указатели ---
    var lcs = Data(); var ncmds = 0
    for d in aSegmentLCs { lcs.append(d); ncmds += 1 }
    for d in bSegmentLCs { lcs.append(d); ncmds += 1 }
    lcs.appendGeneric(value: leSeg); ncmds += 1
    for d in otherLCs { lcs.append(d); ncmds += 1 }
    for d in coldhookNewDylibCmds { lcs.append(d); ncmds += 1 }
    lcs.append(leLCs); ncmds += leCount

    var hdr = mach_header_64()
    hdr.magic = MH_MAGIC_64
    hdr.cputype = CPU_TYPE_ARM64
    hdr.cpusubtype = Int32(bitPattern: a.cpuSubType)
    hdr.filetype = a.filetype.rawValue
    hdr.flags = aFile.getGeneric(type: UInt32.self, offset: 0x18)
    hdr.ncmds = UInt32(ncmds)
    hdr.sizeofcmds = UInt32(lcs.count)
    var header = Data(fromObject: hdr)
    header.append(lcs)

    guard header.count <= headerLimit else {
        print("ColdHook: новый заголовок (\(header.count) б) не влез в padding таргета (\(headerLimit) б). "
            + "Запасные варианты: отдельный хвостовой сегмент или shared-режим (хук по либе с бОльшим запасом).")
        exit(-1)
    }
    header.append(Data(repeating: 0, count: headerLimit - header.count))

    // --- Файл: [новый заголовок + секции A] + сегменты B + __LINKEDIT ---
    // A-контент берём из relocInfo, а НЕ из aFile: там уже патчи хука (HOOK-инструкция в
    // первой инструкции цели, сохранённый ORIG). aFile — оригинал без патчей.
    var targetPlacements: [ColdhookFilePlacement] = []
    for entry in relocInfo.segRel where !entry.1[0].isB {
        let part = entry.1[0]
        if part.data.isEmpty { continue }   // __PAGEZERO (нет файлового контента)
        let fo = Int(part.origCommand.fileOffset)
        targetPlacements.append(ColdhookFilePlacement(fileOffset: fo, data: part.data))
    }
    var out = assembleColdhookPlacements(targetPlacements)
    replaceColdhookHeader(&out, header: header, limit: headerLimit)
    for p in bPlacements {
        let payload = assembleColdhookPlacements([
            ColdhookFilePlacement(fileOffset: p.fileOff, data: p.data)
        ])
        if out.count < payload.count { out.append(payload.suffix(from: out.count)) }
    }
    if out.count < linkeditFileOff { out.append(Data(repeating: 0, count: linkeditFileOff - out.count)) }
    out.append(linkedit)
    return out
}

if coldhookAppendMode {
    let out = coldhookAppendAssemble()
    try writeMachO(out, to: coldhookPosArgs[2])
    print("Done! (append-режим: таргет на месте, хук аппендом)")
    exit(0)
}

// Generate most of the MachO content, except header
let machOData = assembleColdhookSegmentData(relocInfo)

// Generate the MachO itself
var machOHdr = Data()
var loadCommandsSLC = Data()
var loadCommands = Data()
var loadCommandsCount = 0

// Generate segment load commands
let (slcCount, slcs) = generateSegmentLoadCommands(infoA: dataA, infoB: dataB, relocInfo: relocInfo)
loadCommandsSLC.append(slcs)
loadCommandsCount += slcCount

var linkedit = Data()
func emitLinkeditCommand(type: UInt32, data: Data) {
    var res = Data(fromObject: type)
    res.appendGeneric(value: 0x10 as UInt32)
    res.appendGeneric(value: UInt32(linkedit.count + machOData.count + 0x4000))
    res.appendGeneric(value: UInt32(data.count))
    loadCommands.append(res)
    loadCommandsCount += 1
    
    linkedit.append(data)
}

emitLinkeditCommand(type: LC_DYLD_CHAINED_FIXUPS, data: newChainedFixups)

let (symCmdCount, symCmdData) = emitSymtabDysymtab(infoA: dataA, infoB: dataB, relocInfo: relocInfo, linkedit: &linkedit, linkeditStart: machOData.count + 0x4000)
loadCommandsCount += symCmdCount
loadCommands += symCmdData

if let mainCmd = dataA.mainCmd {
    // ColdHook: исполняемый — entry point. entryoff (файловый = vmaddr-base, т.к. __TEXT@fileoff 0)
    // транслируем в новый vmaddr и пересчитываем относительно базы.
    let origEntryVA = coldhookBase &+ mainCmd.entryOffset
    let newEntryVA  = relocInfo.translate(address: origEntryVA, isB: false)
    let newEntryoff = newEntryVA &- coldhookBase
    loadCommands.appendGeneric(value: UInt32(0x80000028)) // LC_MAIN
    loadCommands.appendGeneric(value: UInt32(24))         // cmdsize
    loadCommands.appendGeneric(value: newEntryoff)        // entryoff
    loadCommands.appendGeneric(value: mainCmd.stackSize)  // stacksize
    loadCommandsCount += 1
} else if dataA.unixthread != nil {
    let (count, cmd) = emitUnixthread(info: dataA, relocInfo: relocInfo, isB: false)
    loadCommandsCount += count
    loadCommands += cmd
} else if dataB.unixthread != nil {
    let (count, cmd) = emitUnixthread(info: dataB, relocInfo: relocInfo, isB: true)
    loadCommandsCount += count
    loadCommands += cmd
}

for other in dataA.otherCommands {
    if let opaque = other as? OpaqueLoadCommand {
        let cmd = opaque.type.rawValue
        loadCommands += Data(fromObject: cmd) + Data(fromObject: UInt32(opaque.data.count) + 8) + opaque.data
        loadCommandsCount += 1
    }
    else if let uuidCmd = other as? UUIDLoadCommand {
        let cmd = uuidCmd.type.rawValue
        loadCommands += Data(fromObject: cmd) + Data(fromObject: uuidCmd.cmdSize) + Data(fromObject: uuidCmd.uuid)
        loadCommandsCount += 1
    }
}

// ColdHook: дозаписать LC_LOAD_DYLIB для dylib хука B, которых не было в таргете A
// (--allow-new-dylibs). Идут ПОСЛЕ dylib A, поэтому их ordinals = aDylibs.count+1.. —
// ровно как назначено в mapExternalImport.
for cmdData in coldhookNewDylibCmds {
    loadCommands += cmdData
    loadCommandsCount += 1
}

let lastSegments = relocInfo.segRel.last!
let lastSegment = (lastSegments.1.count == 1) ? lastSegments.1[0] : lastSegments.1[1]
var linkeditLC = segment_command_64()
linkeditLC.cmd = UInt32(LC_SEGMENT_64)
linkeditLC.cmdsize = UInt32(MemoryLayout<segment_command_64>.size)
setMachOName(&linkeditLC.segname, "__LINKEDIT")
linkeditLC.vmaddr = lastSegment.origCommand.vmAddr + lastSegment.offset + lastSegment.origCommand.vmSize
linkeditLC.vmsize = UInt64(linkedit.count)
// ColdHook: fileoff linkedit = сразу после machOData (+0x4000 заголовок). Через vmaddr-offset
// последнего сегмента было неверно при B-в-исполняемом (давало vmaddr вместо file-offset).
linkeditLC.fileoff = UInt64(machOData.count + 0x4000)
linkeditLC.filesize = UInt64(linkedit.count)
linkeditLC.maxprot = VM_PROT_READ
linkeditLC.initprot = VM_PROT_READ
linkeditLC.nsects = 0
linkeditLC.flags = 0
loadCommandsSLC.appendGeneric(value: linkeditLC)
loadCommandsCount += 1

var hdr = mach_header_64()
hdr.magic = MH_MAGIC_64
hdr.cputype = CPU_TYPE_ARM64
hdr.cpusubtype = Int32(bitPattern: a.cpuSubType)
// ColdHook: сохраняем filetype целевого A (MH_DYLIB/MH_EXECUTE), а не хардкодим
// MH_DYLINKER — иначе dlopen/dyld не грузят результат ("unloadable file type 7").
hdr.filetype = a.filetype.rawValue
// ColdHook: сохраняем флаги заголовка A (MH_PIE/TWOLEVEL/DYLDLINK/NOUNDEFS) — мёрджер их
// обнулял, и исполняемый с flags=0 ядро отвергало на exec (SIGKILL). offset 0x18 в mach_header_64.
hdr.flags = a.data.getGeneric(type: UInt32.self, offset: 0x18)
hdr.ncmds = UInt32(loadCommandsCount)
hdr.sizeofcmds = UInt32(loadCommands.count + loadCommandsSLC.count)

machOHdr.appendGeneric(value: hdr)
machOHdr.append(loadCommandsSLC)
machOHdr.append(loadCommands)

guard machOHdr.count < 0x4000 else {
    print("Generated MachO header too large!")
    exit(-1)
}

let out = assembleColdhookMachO(ColdhookMachOOutputPayload(
    header: machOHdr,
    targetData: machOData,
    secondaryPlacements: [],
    linkedit: linkedit
))

try writeMachO(out, to: coldhookPosArgs[2])

/*let resMachO = try MachO(out)

let testCF = try resMachO.getChainedFixups()
try testCF.forEachFixup { location, vAddr, content in
    print("\(pStr(location)) -> \(pStr(vAddr))")
}*/

print("Done!")
