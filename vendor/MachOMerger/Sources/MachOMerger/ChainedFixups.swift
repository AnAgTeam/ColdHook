//
//  ChainedFixups.swift
//  MachOMerger
//
//  Created by Linus Henze.
//

import Foundation
import SwiftMachO

// ColdHook: разобранная import-запись chained fixups (SwiftMachO отдаёт только имена,
// а нам нужны lib_ordinal/weak для ремапа dylib-ordinals при merge внешних импортов B).
struct ColdhookImport {
    let libOrd: UInt16   // dylib ordinal (8 бит у format 1/2, 16 бит у format 3)
    let weak: Bool
    let name: String
}

func coldhookImportSize(_ format: UInt32) -> Int {
    return format == 1 ? 4 : (format == 2 ? 8 : 16)
}

// Все команды загрузки dylib — все они входят в dylib-ordinal пространство биндов
// (LC_ID_DYLIB сюда НЕ входит). Считать только LC_LOAD_DYLIB было бы неверно для
// бинарей с weak/reexport/lazy/upward-зависимостями.
let coldhookDylibLCs: Set<UInt32> = [
    UInt32(LC_LOAD_DYLIB),
    0x80000018, // LC_LOAD_WEAK_DYLIB
    0x8000001f, // LC_REEXPORT_DYLIB
    0x20,       // LC_LAZY_LOAD_DYLIB
    0x80000023, // LC_LOAD_UPWARD_DYLIB
]

func coldhookDylibName(_ op: OpaqueLoadCommand) -> String {
    // op.data — тело команды без 8-байтного заголовка; name_offset считается от начала
    // команды (включая заголовок), поэтому в op.data строка лежит по nameOff-8.
    guard let nameOff = op.data.tryGetGeneric(type: UInt32.self, offset: 0) else { return "" }
    let strStart = Int(nameOff) - 8
    if strStart >= 0, strStart < op.data.count,
       let s = try? op.data.advanced(by: strStart).toString(encoding: .utf8, nullTerminated: true) {
        return s
    }
    return ""
}

// Упорядоченный список путей dylib-зависимостей (1-based ordinal = index+1).
func coldhookDylibPaths(_ machO: MachO) -> [String] {
    var paths: [String] = []
    for cmd in machO.cmds where coldhookDylibLCs.contains(cmd.type.rawValue) {
        if let op = cmd as? OpaqueLoadCommand {
            paths.append(coldhookDylibName(op))
        } else {
            paths.append("")
        }
    }
    return paths
}

// Сырые байты команды загрузки dylib `name` (cmd+cmdsize+тело) — чтобы переэмитить её
// в таргет вербатимом (с настоящими версиями/таймстампом B).
func coldhookDylibCmdData(_ machO: MachO, _ name: String) -> Data? {
    for cmd in machO.cmds where coldhookDylibLCs.contains(cmd.type.rawValue) {
        if let op = cmd as? OpaqueLoadCommand, coldhookDylibName(op) == name {
            return Data(fromObject: op.type.rawValue)
                 + Data(fromObject: UInt32(op.data.count + 8))
                 + op.data
        }
    }
    return nil
}

// Разбор import-таблицы chained fixups. Поддержаны форматы 1/2 (u32: lib_ordinal:8,
// weak:1, name_offset:23) и 3 (u64: lib_ordinal:16, weak:1, reserved:15, name_offset:32).
func coldhookParseImports(importsBlob: Data, count: UInt32, format: UInt32, symbolsBlob: Data) -> [ColdhookImport] {
    guard count > 0 else { return [] }
    let size = coldhookImportSize(format)
    var res: [ColdhookImport] = []
    for i in 0..<Int(count) {
        let libOrd: UInt16, weak: Bool, nameOff: Int
        if format == 1 || format == 2 {
            let raw = importsBlob.getGeneric(type: UInt32.self, offset: UInt(i * size))
            libOrd  = UInt16(raw & 0xFF)
            weak    = ((raw >> 8) & 1) == 1
            nameOff = Int(raw >> 9)
        } else { // format 3
            let raw = importsBlob.getGeneric(type: UInt64.self, offset: UInt(i * size))
            libOrd  = UInt16(raw & 0xFFFF)
            weak    = ((raw >> 16) & 1) == 1
            nameOff = Int(raw >> 32)
        }
        let name = (try? symbolsBlob.advanced(by: nameOff).toString(encoding: .utf8, nullTerminated: true)) ?? ""
        res.append(ColdhookImport(libOrd: libOrd, weak: weak, name: name))
    }
    return res
}

func mergeChainedFixups(infoA: MachOMergeData, infoB: MachOMergeData, relocInfo: RelocInfo, machOA: MachO, machOB: MachO) -> Data {
    guard let cfA = infoA.chainedFixups else {
        print("No chained fixups! [A]")
        exit(-1)
    }
    
    let versionA = cfA.getGeneric(type: UInt32.self, offset: 0)
    guard versionA == 0 else {
        print("Can only support version 0 chained fixups! [A]")
        exit(-1)
    }
    
    let startsOffA     = cfA.getGeneric(type: UInt32.self, offset: 4)
    let importsOffA    = cfA.getGeneric(type: UInt32.self, offset: 8)
    let symsOffA       = cfA.getGeneric(type: UInt32.self, offset: 12)
    let importsCountA  = cfA.getGeneric(type: UInt32.self, offset: 16)
    let importsFormatA = cfA.getGeneric(type: UInt32.self, offset: 20)
    let symsFormatA    = cfA.getGeneric(type: UInt32.self, offset: 24)
    guard symsFormatA == 0 else {
        print("Can only support symbol format 0 for chained fixups!")
        exit(-1)
    }
    
    guard let cfB = infoB.chainedFixups else {
        print("No chained fixups! [B]")
        exit(-1)
    }
    
    let versionB = cfB.getGeneric(type: UInt32.self, offset: 0)
    guard versionB == 0 else {
        print("Can only support version 0 chained fixups! [A]")
        exit(-1)
    }
    
    let startsOffB     = cfB.getGeneric(type: UInt32.self, offset: 4)
    let importsOffB    = cfB.getGeneric(type: UInt32.self, offset: 8)
    let symsOffB       = cfB.getGeneric(type: UInt32.self, offset: 12)
    let importsCountB  = cfB.getGeneric(type: UInt32.self, offset: 16)
    let importsFormatB = cfB.getGeneric(type: UInt32.self, offset: 20)
    let symsFormatB    = cfB.getGeneric(type: UInt32.self, offset: 24)
    guard symsFormatB == 0 else {
        print("Can only support symbol format 0 for chained fixups!")
        exit(-1)
    }
    
    // ColdHook: форматы импортов должны совпадать ТОЛЬКО если у хука B реально есть импорты
    // для дозаписи. Если у B импортов нет (importsCountB == 0, частый случай — хук по оффсету
    // без внешних вызовов), выход берёт таблицу импортов A вербатим в её формате (1/2/3),
    // дописывать нечего — формат A неважен. Это снимает ложный отказ на реальных Swift-таргетах
    // с форматом импортов 2/3.
    guard importsCountB == 0 || importsFormatA == importsFormatB else {
        print("Chained fixups imports format must be the same for both binaries (B has imports)!")
        exit(-1)
    }
    
    // For our limited usecase, assume these binaries imports nothing
    /*guard importsCountA == 0 && importsCountB == 0 else {
        print("XXX: Can only support zero imports right now!")
        exit(-1)
    }*/
    
    // ColdHook Step 1: импорты A сохраняются. Бинды A указывают на imports-таблицу A по
    // ordinal'у; переносим её и symbols-пул A в выход вербатимом (бинды A не трогаем —
    // слайд сегментов на них не влияет, rebase'ы A чинит fixupViaSplitInfo).
    let importsSizeA   = coldhookImportSize(importsFormatA)
    let importsBlobA   = (importsCountA == 0)
        ? Data()
        : cfA.subdata(in: Int(importsOffA)..<(Int(importsOffA) + Int(importsCountA) * importsSizeA))
    let symbolsBlobA   = cfA.subdata(in: Int(symsOffA)..<cfA.count)

    // ColdHook Step 2: внешние импорты B, которые НЕ резолвятся внутрь образа, остаются
    // реальными биндами. Их dylib-ordinal ремапим на LC_LOAD_DYLIB таргета A (общий кейс:
    // libSystem/Foundation/UIKit, которые A уже грузит), а import-запись + имя дописываем.
    let aImports = coldhookParseImports(importsBlob: importsBlobA, count: importsCountA, format: importsFormatA, symbolsBlob: symbolsBlobA)
    let aDylibs  = coldhookDylibPaths(machOA)
    let bDylibs  = coldhookDylibPaths(machOB)

    let importsSizeB = coldhookImportSize(importsFormatB)
    let importsBlobB = (importsCountB == 0)
        ? Data()
        : cfB.subdata(in: Int(importsOffB)..<(Int(importsOffB) + Int(importsCountB) * importsSizeB))
    let symbolsBlobB = cfB.subdata(in: Int(symsOffB)..<cfB.count)
    let bImports = coldhookParseImports(importsBlob: importsBlobB, count: importsCountB, format: importsFormatB, symbolsBlob: symbolsBlobB)

    // Состояние дозаписи merged-импортов (после import-таблицы A).
    var appendedImports = Data()
    var appendedSymbols = Data()
    var appendedCount: UInt32 = 0
    // dedup по ключу "dylibOrd|name" -> ordinal в merged-таблице (сидим импортами A).
    var importIndex: [String: UInt32] = [:]
    for (i, imp) in aImports.enumerated() {
        importIndex["\(imp.libOrd)|\(imp.name)"] = UInt32(i)
    }
    // Новые dylib, которых нет в A: имя -> назначенный dylib-ordinal (после dylib A).
    var newDylibOrd: [String: UInt8] = [:]

    // Маппинг внешнего импорта B (по ordinal'у его фиксапа) -> ordinal в merged-таблице.
    func mapExternalImport(bOrdinal: UInt32) -> UInt32? {
        guard Int(bOrdinal) < bImports.count else { return nil }
        let imp = bImports[Int(bOrdinal)]

        // dylib-ordinal в merged.
        let dylibOrd: UInt8
        if imp.libOrd == 0 || imp.libOrd >= 0xFD {
            // Спец-ординалы chained fixups: 0=main-executable, 0xFD=weak, 0xFE=flat, 0xFF=self
            // lookup. Их НЕ маппим на конкретный dylib — оставляем как есть, загрузчик резолвит
            // символ глобально по имени. Swift/C++ рантайм тянет такие (напр. operator delete
            // __ZdlPv через flat lookup). Дедуп по (спец-ординал|имя).
            dylibOrd = UInt8(imp.libOrd & 0xFF)
        } else if Int(imp.libOrd) <= bDylibs.count {
            let dylibName = bDylibs[Int(imp.libOrd) - 1]
            // либо существующий dylib таргета, либо новый (по опции).
            if let aIdx = aDylibs.firstIndex(of: dylibName) {
                dylibOrd = UInt8(aIdx + 1)
            } else if coldhookAllowNewDylibs {
                if let existing = newDylibOrd[dylibName] {
                    dylibOrd = existing
                } else {
                    guard let cmdData = coldhookDylibCmdData(machOB, dylibName) else {
                        print("ColdHook: не нашёл команду загрузки '\(dylibName)' в хуке")
                        exit(-1)
                    }
                    // dylib A занимают 1..aDylibs.count, новые идут следом.
                    let ord = UInt8(aDylibs.count + coldhookNewDylibCmds.count + 1)
                    newDylibOrd[dylibName] = ord
                    coldhookNewDylibCmds.append(cmdData)   // main.swift доэмитит LC_LOAD_DYLIB
                    dylibOrd = ord
                }
            } else {
                print("ColdHook: импорт B '\(imp.name)' тянет dylib '\(dylibName)', которого НЕТ в "
                    + "LC_LOAD_DYLIB таргета. Разреши --allow-new-dylibs (вставит LC_LOAD_DYLIB) "
                    + "или убери эту зависимость из хука.")
                exit(-1)
            }
        } else {
            return nil  // ordinal вне диапазона
        }

        let key = "\(dylibOrd)|\(imp.name)"
        if let existing = importIndex[key] { return existing }
        guard importsFormatA == 1 else {
            print("ColdHook: дозапись импортов поддержана только для format 1")
            return nil
        }
        let newNameOff = UInt32(symbolsBlobA.count + appendedSymbols.count)
        let raw = UInt32(dylibOrd) | (imp.weak ? 0x100 : 0) | (newNameOff << 9)
        appendedImports.appendGeneric(value: raw)
        appendedSymbols.append(imp.name.data(using: .utf8)!)
        appendedSymbols.append(0) // null terminator
        let newOrd = importsCountA + appendedCount
        appendedCount += 1
        importIndex[key] = newOrd
        return newOrd
    }

    if importsCountB != 0 {
        let cf = try! b.getChainedFixups()
        // symtab таргета A — ОПЦИОНАЛЬНО: SwiftMachO не всегда разбирает symtab реальных
        // бинарей (Swift/стрипнутые) -> BadFormat. Для дозаписи импортов он нужен лишь чтобы
        // отличить импорт B, резолвящийся ВНУТРЬ A (defined-символ), от внешнего. Если symtab
        // недоступен — все импорты B (кроме магик-символов) считаем внешними и дедупим/биндим.
        let symTable = try? a.getSymbolTable()

        // Резолв импорта B внутрь образа (магик-символ или symtab таргета A).
        // ВАЖНО: матчим в symtab A только DEFINED-символы (N_SECT, n_type & 0x0e == 0x0e).
        // Undefined-символы A (n_type N_UNDF == 0) — это САМИ импорты таргета (напр. _write),
        // их нельзя трактовать как внутренний адрес: иначе общий с таргетом импорт B
        // отребейзится в мусор вместо bind. Такой символ уйдёт в mapExternalImport и
        // сдедупится с импортом A по (dylib|имя).
        func resolveInternal(_ sym: String) -> (addr: UInt64, isB: Bool)? {
            if let d = getMagicSymbolVal(sym) { return (d.0, d.1) }
            if let d = symTable?.symbol(forName: sym), (d.type & 0x0e) == 0x0e {
                return (d.value, false)
            }
            return nil
        }
        func writeFixup(loc: UInt64, raw: UInt64) {
            let segment = relocInfo.segment(forOrigAddress: loc, isB: true)!
            let off = Int(segment.3)
            var data = segment.1
            data = data.subdata(in: 0..<off) + Data(fromObject: raw) + data.subdata(in: (off + 8)..<data.count)
            relocInfo.replaceSegment(name: segment.0, isB: true, data: data)
        }

        // Семейство формата (берём из первого сегмента со стартами).
        let fmt = cf.startsInSegment.compactMap { $0 }.first?.pointerFormat ?? 0

        if fmt == 1 || fmt == 12 {
            // --- arm64e (1, 12): обход и кодировка через SwiftMachO ChainTarget, шаг 8 ---
            try! cf.forEachFixup({ location, vAddr, content in
                if case .authBind(ordinal: let ord, diversity: let diversity, addrDiv: let addrDiv, key: let key, next: let next) = content {
                    let sym = cf.symbol(forFixup: content)!
                    let nr: UInt64
                    if let r = resolveInternal(sym) {
                        nr = ChainedFixups.ChainedStartsInSegment.ChainTarget.authRebase(target: UInt32(relocInfo.translate(address: r.addr, isB: r.isB)), diversity: diversity, addrDiv: addrDiv, key: key, next: next).rawValue
                    } else if let newOrd = mapExternalImport(bOrdinal: ord) {
                        nr = ChainedFixups.ChainedStartsInSegment.ChainTarget.authBind(ordinal: newOrd, diversity: diversity, addrDiv: addrDiv, key: key, next: next).rawValue
                    } else { print("ColdHook: импорт B '\(sym)' не резолвится/не мерджится"); exit(-1) }
                    writeFixup(loc: location, raw: nr)
                } else if case .bind(ordinal: let ord, addend: let addend, next: let next) = content {
                    let sym = cf.symbol(forFixup: content)!
                    let nr: UInt64
                    if let r = resolveInternal(sym) {
                        nr = ChainedFixups.ChainedStartsInSegment.ChainTarget.rebase(target: relocInfo.translate(address: r.addr, isB: r.isB), high8: 0, next: next).rawValue
                    } else if let newOrd = mapExternalImport(bOrdinal: ord) {
                        nr = ChainedFixups.ChainedStartsInSegment.ChainTarget.bind(ordinal: newOrd, addend: addend, next: next).rawValue
                    } else { print("ColdHook: импорт B '\(sym)' не резолвится/не мерджится"); exit(-1) }
                    writeFixup(loc: location, raw: nr)
                }
                // rebase/authRebase B чинит fixupViaSplitInfo — здесь не трогаем
            })
        } else if fmt == 2 || fmt == 6 {
            // --- arm64 (2 = DYLD_CHAINED_PTR_64, 6 = _64_OFFSET): свой обход, шаг 4 байта ---
            // Структуру цепочки читаем из ОРИГИНАЛА B (бинды split-info не трогает),
            // переписанные бинды пишем в выходной сегмент через relocInfo.
            let bSegs = machOB.cmds.compactMap { $0 as? Segment64LoadCommand }
            for (segIdx, startsOpt) in cf.startsInSegment.enumerated() {
                guard let starts = startsOpt, segIdx < bSegs.count else { continue }
                let segLC = bSegs[segIdx]
                let pageSize = Int(starts.pageSize)
                for pageIndex in 0..<starts.pageStarts.count {
                    let ps = starts.pageStarts[pageIndex]
                    if ps == 0xFFFF { continue }                       // START_NONE
                    guard ps & 0x8000 == 0 else { print("ColdHook: multi-chain страницы не поддержаны"); exit(-1) }
                    var curFileOff = Int(starts.segOffset) + pageIndex * pageSize + Int(ps)
                    while true {
                        let content = machOB.data.getGeneric(type: UInt64.self, offset: UInt(curFileOff))
                        let next  = (content >> 51) & 0x7FF
                        let isBnd = (content >> 63) & 1 == 1
                        if isBnd {
                            let ord    = UInt32(content & 0xFFFFFF)     // ordinal: 24 бита
                            let addend = UInt32((content >> 24) & 0xFF) // addend: 8 бит
                            guard Int(ord) < cf.imports.count else { print("ColdHook: bind ordinal \(ord) вне imports B"); exit(-1) }
                            let sym = cf.imports[Int(ord)]
                            let loc = segLC.vmAddr &+ UInt64(curFileOff) &- segLC.fileOffset
                            let nr: UInt64
                            if let r = resolveInternal(sym) {
                                // внутренний резолв -> rebase (формат 64: target = offset от базы, база 0)
                                let t = relocInfo.translate(address: r.addr, isB: r.isB)
                                nr = (t & 0xFFFFFFFFF) | (((t >> 36) & 0xFF) << 36) | (next << 51) // bit63=0
                            } else if let newOrd = mapExternalImport(bOrdinal: ord) {
                                // внешний импорт -> bind с merged-ordinal (формат 64 bind layout)
                                nr = (UInt64(newOrd) & 0xFFFFFF) | (UInt64(addend) << 24) | (next << 51) | (UInt64(1) << 63)
                            } else { print("ColdHook: импорт B '\(sym)' не резолвится/не мерджится"); exit(-1) }
                            writeFixup(loc: loc, raw: nr)
                        }
                        if next == 0 { break }
                        curFileOff += Int(next) * 4
                    }
                }
            }
        } else {
            print("ColdHook: неподдержанный pointer_format \(fmt) у B")
            exit(-1)
        }
    }
    
    // Okay, we only have to fix the starts
    let startsA = cfA.advanced(by: Int(startsOffA))
    let startsB = cfB.advanced(by: Int(startsOffB))
    
    let segCountA = startsA.getGeneric(type: UInt32.self)
    let segCountB = startsB.getGeneric(type: UInt32.self)
    
    var segsA: [Data?] = []
    var segsB: [Data?] = []
    
    for i in 0..<UInt(segCountA) {
        let off  = Int(startsA.getGeneric(type: UInt32.self, offset: 4 + (4 * i))) + 4
        if off == 4 {
            segsA.append(nil)
            continue
        }
        
        let size = Int(startsA.getGeneric(type: UInt32.self, offset: UInt(off - 4)))
        
        var data = startsA.subdata(in: off..<(off + size))
        
        // Get matching segment
        let seg = relocInfo.segment(forIndex: Int(i), isB: false)
        
        // Change segment offset
        let segmentOff = data.getGeneric(type: UInt64.self, offset: 0x4)
        
        data = data.subdata(in: 0..<4) + Data(fromObject: segmentOff &+ seg.2) + data.subdata(in: 12..<data.count)
        
        segsA.append(data)
    }
    
    for i in 0..<UInt(segCountB) {
        let off = Int(startsB.getGeneric(type: UInt32.self, offset: 4 + (4 * i))) + 4
        if off == 4 {
            segsB.append(nil)
            continue
        }
        
        let size = Int(startsB.getGeneric(type: UInt32.self, offset: UInt(off - 4)))
        
        var data = startsB.subdata(in: off..<(off + size))
        
        // Get matching segment
        let seg = relocInfo.segment(forIndex: Int(i), isB: true)

        // Change segment offset
        // segment_offset — это vmaddr-смещение сегмента от БАЗЫ ОБРАЗА. У B (dylib, база 0)
        // оно считалось бы от 0, давая абсолютный merged vmaddr; для исполняемого (база
        // 0x100000000) вычитаем coldhookBase, чтобы получить смещение от базы. dylib: 0 -> no-op.
        let segmentOff = data.getGeneric(type: UInt64.self, offset: 0x4)

        data = data.subdata(in: 0..<4) + Data(fromObject: segmentOff &+ seg.2 &- coldhookBase) + data.subdata(in: 12..<data.count)

        segsB.append(data)
    }
    
    // Now merge them
    var segsMerged: [Data?] = []
    var curA = 0
    var curB = 0
    for seg in relocInfo.segRel {
        if !seg.1[0].isB && seg.1.count == 1 {
            // Only A
            segsMerged.append(segsA[curA])
            curA += 1
        } else if seg.1[0].isB {
            // Only B
            segsMerged.append(segsB[curB])
            curB += 1
        } else {
            // Merge
            if let a = segsA[curA],
               let b = segsB[curB] {
                let offA = a.getGeneric(type: UInt64.self, offset: 0x4)
                let offB = b.getGeneric(type: UInt64.self, offset: 0x4)
                
                let pgSizeA = a.getGeneric(type: UInt16.self, offset: 0x0)
                let pgSizeB = b.getGeneric(type: UInt16.self, offset: 0x0)
                guard pgSizeA == pgSizeB else {
                    print("mergeChainedFixups: Page Size not equal!")
                    exit(-1)
                }
                
                let pageOffMask = UInt64(pgSizeA) - 1
                let diff = offB - offA
                guard diff & pageOffMask == 0 else {
                    print("mergeChainedFixups: Distance not multiple of page size!")
                    exit(-1)
                }
                
                let pageDiff = diff / UInt64(pgSizeA)
                guard pageDiff < UInt16.max else {
                    print("mergeChainedFixups: Distance too large!")
                    exit(-1)
                }
                
                // Emit A with additional pages
                let countA = a.getGeneric(type: UInt16.self, offset: 0x10)
                let countB = b.getGeneric(type: UInt16.self, offset: 0x10)
                var offs = Data()
                for _ in 0..<UInt(pageDiff - UInt64(countA)) {
                    offs += Data(fromObject: UInt16(0xFFFF))
                }
                
                for i in 0..<UInt(countB) {
                    offs += Data(fromObject: b.getGeneric(type: UInt16.self, offset: 0x12 + (2 * i)))
                }
                
                let data = a.subdata(in: 0..<0x10) + Data(fromObject: countA + countB + (UInt16(pageDiff) - countA)) + a.subdata(in: 0x12..<(0x12 + (2 * Int(countA)))) + offs
                segsMerged.append(data)
            } else if segsB[curB] == nil {
                // Effectively only A (maybe)
                segsMerged.append(segsA[curA])
            } else {
                // Effectively only B (maybe)
                segsMerged.append(segsB[curB])
            }
            
            curA += 1
            curB += 1
        }
    }
    
    // Generate the starts header
    var starts  = Data()
    var segData = Data()
    starts.appendGeneric(value: UInt32(segsMerged.count + 1))
    
    let needsAdjust = segsMerged.count & 1 == 1
    let theOff = segsMerged.count + 1 + (needsAdjust ? 1 : 0)
    for i in 0..<segsMerged.count {
        if let s = segsMerged[i] {
            let off = 4 + (4 * theOff) + segData.count
            starts.appendGeneric(value: UInt32(off))
            
            let toAppend = Data(fromObject: UInt32(s.count) + 4) + s
            segData += toAppend
        } else {
            starts.appendGeneric(value: 0 as UInt32)
        }
    }
    
    starts.appendGeneric(value: 0 as UInt32) // LINKEDIT
    
    // Is this needed?
    if needsAdjust {
        starts.appendGeneric(value: 0 as UInt32)
    }
    
    var startsSegData = starts + segData

    // ColdHook: merged imports = import-таблица A (вербатим, ordinal'ы 0..countA-1)
    // + дозаписанные внешние импорты B (ordinal'ы countA..). merged symbols = пул A
    // + имена дозаписанных импортов. name_offset'ы считаются от symsOff, поэтому пул A
    // переносится как есть, а новые имена идут после него.
    let importsBlobOut  = importsBlobA + appendedImports
    let symbolsBlobOut  = symbolsBlobA + appendedSymbols
    let importsCountOut = importsCountA + appendedCount

    // imports выравниваем на 8 байт (покрывает все import-форматы, включая addend64).
    let baseOff     = 32 + startsSegData.count
    let importsOff  = (baseOff + 7) & ~7
    if importsOff > baseOff {
        startsSegData.append(Data(repeating: 0, count: importsOff - baseOff))
    }
    let symsOff = importsOff + importsBlobOut.count

    var newChainedFixups = Data()

    // Emit header
    newChainedFixups.appendGeneric(value:  0 as UInt32)            // fixups_version
    newChainedFixups.appendGeneric(value: 32 as UInt32)            // startsOff
    newChainedFixups.appendGeneric(value: UInt32(importsOff))      // importsOff
    newChainedFixups.appendGeneric(value: UInt32(symsOff))         // symsOff
    newChainedFixups.appendGeneric(value: importsCountOut)         // importsCount (A + внешние B)
    newChainedFixups.appendGeneric(value: importsFormatA)          // importsFormat
    newChainedFixups.appendGeneric(value: symsFormatA)             // symsFormat
    newChainedFixups.appendGeneric(value: 0 as UInt32)             // pad

    // Emit data: starts(+pad) -> imports(A+B) -> symbols(A+B)
    newChainedFixups.append(startsSegData)
    newChainedFixups.append(importsBlobOut)
    newChainedFixups.append(symbolsBlobOut)

    // Выравниваем весь блок до 8 байт: иначе следующая за ним в __LINKEDIT symtab
    // окажется mis-aligned (dyld терпит, но dyld_info/строгие загрузчики ругаются).
    while newChainedFixups.count % 8 != 0 {
        newChainedFixups.append(0)
    }

    return newChainedFixups
}
