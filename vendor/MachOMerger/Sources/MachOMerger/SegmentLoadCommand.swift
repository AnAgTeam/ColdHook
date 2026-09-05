//
//  SegmentLoadCommand.swift
//  MachOMerger
//
//  Created by Linus Henze on 2023-03-16.
//

import Foundation
import MachO

func generateSegmentLoadCommands(infoA: MachOMergeData, infoB: MachOMergeData, relocInfo: RelocInfo,
                                 extraSections: [String: [section_64]] = [:],
                                 segmentGrowth: [String: (vmSize: UInt64, fileSize: UInt64)] = [:],
                                 reserveHeader: Bool = true,
                                 extraSegments: [Data] = []) -> (Int, Data) {
    var result = Data()
    // ColdHook: «заголовочный» сегмент (туда резервируется 0x4000 под mach header) — первый
    // НЕ-__PAGEZERO. Для dylib это index 0; для исполняемого — index 1 (после __PAGEZERO).
    let headerIdx = relocInfo.segRel.firstIndex(where: { $0.0 != "__PAGEZERO" }) ?? 0
    for i in 0..<relocInfo.segRel.count {
        let seg = relocInfo.segRel[i]

        // Emit it
        let base = seg.1[0].origCommand.vmAddr &+ seg.1[0].offset

        var sects = seg.1[0].origCommand.sections.count
        if seg.1.count > 1 {
            sects += seg.1[1].origCommand.sections.count
        }
        sects += extraSections[seg.0]?.count ?? 0

        var slc = segment_command_64()
        slc.cmd = UInt32(LC_SEGMENT_64)
        slc.cmdsize = UInt32(MemoryLayout<segment_command_64>.size + (MemoryLayout<section_64>.size * sects))
        _ = withUnsafeMutableBytes(of: &slc.segname) { ptr in
            strcpy(ptr.baseAddress!, seg.0)
        }

        if seg.0 == "__PAGEZERO" {
            // ColdHook: вербатим — vmaddr 0, vmsize 4ГБ, без файлового контента, prot 0.
            slc.vmaddr = seg.1[0].origCommand.vmAddr
            slc.vmsize = seg.1[0].origCommand.vmSize
            slc.fileoff = seg.1[0].origCommand.fileOffset
            slc.filesize = seg.1[0].origCommand.fileSize
            slc.maxprot = Int32(bitPattern: seg.1[0].origCommand.maximumProt.rawValue)
            slc.initprot = Int32(bitPattern: seg.1[0].origCommand.protection.rawValue)
        } else if reserveHeader && i == headerIdx {
            // base &- 0x4000: для dylib даёт 0, для исполняемого — образную базу (0x100000000).
            slc.vmaddr = base &- 0x4000
            if seg.1.count == 1 {
                slc.vmsize = seg.1[0].origCommand.vmSize + 0x4000
                slc.filesize = seg.1[0].origCommand.fileSize + 0x4000
            } else {
                slc.vmsize = seg.1[0].origCommand.vmSize + seg.1[1].origCommand.vmSize + 0x4000
                slc.filesize = seg.1[0].origCommand.fileSize + seg.1[1].origCommand.fileSize + 0x4000
            }

            slc.fileoff = 0
            slc.maxprot = VM_PROT_READ | VM_PROT_EXECUTE
            slc.initprot = VM_PROT_READ | VM_PROT_EXECUTE
        } else {
            slc.vmaddr = base
            if seg.1.count == 1 {
                slc.vmsize = seg.1[0].origCommand.vmSize
                slc.filesize = seg.1[0].origCommand.fileSize
            } else {
                slc.vmsize = seg.1[0].origCommand.vmSize + seg.1[1].origCommand.vmSize
                slc.filesize = seg.1[0].origCommand.fileSize + seg.1[1].origCommand.fileSize
            }
            
            slc.fileoff = seg.1[0].origCommand.fileOffset + seg.1[0].offset
            slc.maxprot = Int32(bitPattern: seg.1[0].origCommand.maximumProt.rawValue)
            slc.initprot = Int32(bitPattern: seg.1[0].origCommand.protection.rawValue)
        }

        // Shared backend appends synthetic payload to an existing A segment.  Keep
        // the default zero-growth path byte-for-byte compatible with embedded modes.
        if let growth = segmentGrowth[seg.0] {
            slc.vmsize += growth.vmSize
            slc.filesize += growth.fileSize
        }
        
        slc.nsects = UInt32(sects)
        slc.flags = seg.1[0].origCommand.flags
        // ColdHook: dyld требует SG_READ_ONLY (0x10) на const-сегментах данных, иначе
        // "__DATA_CONST segment missing SG_READ_ONLY flag" при загрузке слитого образа.
        if seg.0 == "__DATA_CONST" || seg.0 == "__AUTH_CONST" {
            slc.flags |= 0x10
        }
        
        var sectsData = Data()
        for sect in seg.1[0].origCommand.sections {
            var sectLC = section_64()
            _ = withUnsafeMutableBytes(of: &sectLC.sectname) { ptr in
                strcpy(ptr.baseAddress!, sect.section)
            }
            _ = withUnsafeMutableBytes(of: &sectLC.segname) { ptr in
                strcpy(ptr.baseAddress!, seg.0)
            }
            
            sectLC.addr = sect.address + seg.1[0].offset
            sectLC.size = sect.size
            // ColdHook: file-offset = merged vmaddr - база образа (раскладка контигуальна:
            // vmaddr V -> file V-base). Через vmaddr-offset было неверно при разной базе A/B
            // (исполняемый: A@0x100000000, B@0 -> переполнение UInt32). zerofill оставляем 0.
            sectLC.offset = (sect.offset == 0) ? 0 : UInt32(sectLC.addr &- coldhookBase)
            sectLC.align = sect.alignment
            sectLC.flags = sect.flags.rawValue
            sectLC.reserved1 = sect.reserved1
            sectLC.reserved2 = sect.reserved2
            sectLC.reserved3 = sect.reserved3

            // ColdHook: если сливаем __init_offsets A+B — перенацеливаем секцию A на
            // объединённый массив (он лежит в мёртвой области заголовка B). См. main.swift.
            if let im = coldhookInitMerge,
               sect.section == "__init_offsets", (sect.flags.rawValue & 0xff) == 0x16 {
                sectLC.addr = im.combinedVMAddr
                sectLC.size = im.combinedSize
                sectLC.offset = UInt32(im.combinedVMAddr &- coldhookBase)
            }

            sectsData.appendGeneric(value: sectLC)
        }

        if seg.1.count > 1 {
            for sect in seg.1[1].origCommand.sections {
                var sectLC = section_64()
                _ = withUnsafeMutableBytes(of: &sectLC.sectname) { ptr in
                    if sect.section != "__jbinfo" {
                        // Special case, "__DATA:__jbinfo" section should not be appended with "_2"
                        // Ideally I would have added a check here to only add _2 if the section already exists in file a
                        // But then again this is Swift
                        strcpy(ptr.baseAddress!, sect.section + "_2")
                    }
                    else {
                        strcpy(ptr.baseAddress!, sect.section)
                    }
                }
                _ = withUnsafeMutableBytes(of: &sectLC.segname) { ptr in
                    strcpy(ptr.baseAddress!, seg.0)
                }
                
                sectLC.addr = sect.address + seg.1[1].offset
                sectLC.size = sect.size
                sectLC.offset = (sect.offset == 0) ? 0 : UInt32(sectLC.addr &- coldhookBase)
                sectLC.align = sect.alignment
                sectLC.flags = sect.flags.rawValue
                sectLC.reserved1 = sect.reserved1
                sectLC.reserved2 = sect.reserved2
                sectLC.reserved3 = sect.reserved3

                // ColdHook: если сливаем __init_offsets A+B — секцию B нейтрализуем
                // (тип -> S_REGULAR), чтобы dyld её не считал второй init-секцией. Её записи
                // уже скопированы в объединённый массив, на который смотрит секция A.
                if coldhookInitMerge != nil,
                   sect.section == "__init_offsets", (sect.flags.rawValue & 0xff) == 0x16 {
                    sectLC.flags = sect.flags.rawValue & ~UInt32(0xff)
                }

                sectsData.appendGeneric(value: sectLC)
            }
        }

        // Shared backend supplies synthetic sections after the original A/B sections.
        // Their payload and addresses are planned separately; this function only emits
        // their section_64 descriptors into the segment load command.
        if let extras = extraSections[seg.0] {
            for section in extras { sectsData.appendGeneric(value: section) }
        }
        
        result.appendGeneric(value: slc)
        result.append(sectsData)
    }
    
    for segment in extraSegments { result.append(segment) }
    return (relocInfo.segRel.count + extraSegments.count, result)
}
