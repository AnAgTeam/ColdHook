// Shared backend orchestration, deliberately split into planning and emission.
import Foundation
import MachO

struct ColdhookSharedHookPlan {
    let entryAddress: UInt64
    let stub: ColdhookSharedStub
    let origAddress: UInt64
    let spec: ColdhookSharedSpec
}

struct ColdhookSharedTargetPlan {
    let layout: ColdhookSharedLayout
    let metadata: ColdhookSharedEmission
    let hooks: [ColdhookSharedHookPlan]
}

struct ColdhookSharedAssembly {
    let targetData: MachOMergeData
    let relocInfo: RelocInfo
    let plan: ColdhookSharedTargetPlan
    let extraSections: [String: [section_64]]
    let segmentGrowth: [String: (vmSize: UInt64, fileSize: UInt64)]
}

func makeColdhookSharedRelocInfo(_ targetData: MachOMergeData) -> RelocInfo {
    let segments: SegRelocInfo = targetData.segments.map { command, data in
        (command.name, [(isB: false, origCommand: command, data: data, offset: UInt64(0))])
    }
    return RelocInfo(segRel: segments)
}

func generateColdhookSharedSegmentLoadCommands(_ assembly: ColdhookSharedAssembly) -> (Int, Data) {
    generateSegmentLoadCommands(
        infoA: assembly.targetData,
        infoB: MachOMergeData(),
        relocInfo: assembly.relocInfo,
        extraSections: assembly.extraSections,
        segmentGrowth: assembly.segmentGrowth,
        reserveHeader: false
    )
}

func sharedColdhookSegmentGrowth(_ targetData: MachOMergeData,
                                 layout: ColdhookSharedLayout) -> [String: (vmSize: UInt64, fileSize: UInt64)] {
    func growth(_ segmentName: String, newVMEnd: UInt64, newFileEnd: UInt64)
        -> (vmSize: UInt64, fileSize: UInt64)? {
        guard let segment = targetData.segments.first(where: { $0.0.name == segmentName })?.0 else {
            return nil
        }
        let oldVMEnd = segment.vmAddr + segment.vmSize
        let oldFileEnd = segment.fileOffset + segment.fileSize
        guard newVMEnd >= oldVMEnd, newFileEnd >= oldFileEnd else { return nil }
        return (newVMEnd - oldVMEnd, newFileEnd - oldFileEnd)
    }

    var result: [String: (vmSize: UInt64, fileSize: UInt64)] = [:]
    if let value = growth("__TEXT", newVMEnd: layout.stubVMAddr + layout.stubSize,
                          newFileEnd: layout.stubFileOffset + layout.stubSize) {
        result["__TEXT"] = value
    }
    if let value = growth("__DATA", newVMEnd: layout.tableVMAddr + layout.tableSize,
                          newFileEnd: layout.tableFileOffset + layout.tableSize) {
        result["__DATA"] = value
    }
    return result
}

enum ColdhookSharedAssemblerError: Error, CustomStringConvertible {
    case missingSegment(String)
    case targetNotFound(String)
    case payloadNotContiguous(String)

    var description: String {
        switch self {
        case .missingSegment(let name): return "shared: target has no \(name) segment"
        case .targetNotFound(let name): return "shared: target locator not found: \(name)"
        case .payloadNotContiguous(let name): return "shared: payload cannot be appended to \(name)"
        }
    }
}

/// Materializes synthetic shared payload into the target's segment data.  This is
/// intentionally separate from load-command emission: callers can feed the mutated
/// A data into the existing append/header/LINKEDIT assembly path.
func materializeColdhookSharedPayload(_ plan: ColdhookSharedTargetPlan,
                                      into targetData: inout MachOMergeData,
                                      originalTargetData: MachOMergeData? = nil) throws {
    let placements = makeColdhookSharedPlacements(plan)
    for (segmentName, start, end) in [("__TEXT", plan.layout.stubFileOffset,
                                      plan.layout.stubFileOffset + plan.layout.stubSize),
                                     ("__DATA", plan.layout.tableFileOffset,
                                      plan.layout.tableFileOffset + plan.layout.tableSize)] {
        guard let index = targetData.segments.firstIndex(where: { $0.0.name == segmentName }) else {
            throw ColdhookSharedAssemblerError.missingSegment(segmentName)
        }
        let command = targetData.segments[index].0
        var bytes = targetData.segments[index].1
        let fileStart = command.fileOffset
        guard start >= fileStart else { throw ColdhookSharedAssemblerError.payloadNotContiguous(segmentName) }
        let relative = start - fileStart
        guard relative <= UInt64(Int.max) else { throw ColdhookSharedAssemblerError.payloadNotContiguous(segmentName) }
        let off = Int(relative)
        guard off >= bytes.count || off + Int(end - start) <= bytes.count + 0x4000 else {
            throw ColdhookSharedAssemblerError.payloadNotContiguous(segmentName)
        }
        if bytes.count < off { bytes.append(Data(repeating: 0, count: off - bytes.count)) }
        var payload = placements.first { $0.fileOffset == Int(start) }!.data
        if segmentName == "__TEXT", let originalTargetData {
            for hook in plan.hooks {
                guard hook.stub.address >= start,
                      hook.stub.address + 20 <= end,
                      let source = originalTargetData.segments.first(where: {
                          hook.entryAddress >= $0.0.vmAddr && hook.entryAddress + 4 <= $0.0.vmAddr + $0.0.fileSize
                      }) else { continue }
                let sourceOffset = Int(hook.entryAddress - source.0.vmAddr)
                let originalInsn = source.1.withUnsafeBytes {
                    $0.load(fromByteOffset: sourceOffset, as: UInt32.self)
                }
                let origOffset = Int(hook.stub.address - start) + 12
                let returnBranch = try encodeColdhookB(from: hook.origAddress, to: hook.entryAddress + 4)
                payload.replaceSubrange(origOffset..<(origOffset + 4), with: Data(fromObject: originalInsn))
                payload.replaceSubrange((origOffset + 4)..<(origOffset + 8), with: Data(fromObject: returnBranch))
            }
        }
        bytes.append(payload)
        command.fileSize = UInt64(bytes.count)
        command.vmSize = max(command.vmSize,
                             (start - command.fileOffset) + UInt64(payload.count))
        targetData.segments[index] = (command, bytes)
    }
}

private func sharedTargetAddress(_ locator: String,
                                 resolver: ColdhookSymbolResolver) throws -> UInt64 {
    if let magic = getMagicSymbolVal(locator) { return magic.0 }
    guard let symbol = resolver.first(locator, definedOnly: true)
        ?? resolver.first("_" + locator, definedOnly: true) else {
        throw ColdhookSharedAssemblerError.targetNotFound(locator)
    }
    return symbol.value
}

/// Builds the full per-target shared plan without touching Mach-O bytes.  Shared
/// emission consumes this plan to append sections and patch entries.
func planColdhookSharedTarget(
    targetData: MachOMergeData,
    targetResolver: ColdhookSymbolResolver,
    userHooksData: MachOMergeData,
    userHooksResolver: ColdhookSymbolResolver
) throws -> ColdhookSharedTargetPlan {
    let declarations = try extractColdhookSharedSpecs(from: userHooksResolver, data: userHooksData)
    let hookSymbols = userHooksResolver.all(prefix: "_COLDHOOK_").filter {
        $0.name.hasPrefix("_COLDHOOK_DYN_") || $0.name.hasPrefix("_COLDHOOK_SYM_") || $0.name.hasPrefix("_COLDHOOK_ADDR_")
    }
    guard declarations.count == hookSymbols.count else {
        throw ColdhookSharedAssemblerError.targetNotFound("inconsistent hook declarations")
    }
    guard let text = targetData.segments.first(where: { $0.0.name == "__TEXT" })?.0 else {
        throw ColdhookSharedAssemblerError.missingSegment("__TEXT")
    }
    guard let data = targetData.segments.first(where: { $0.0.name == "__DATA" })?.0 else {
        throw ColdhookSharedAssemblerError.missingSegment("__DATA")
    }

    // Each hook owns twelve bytes of local veneer and eight bytes of orig code.
    let initialMetadata = emitColdhookSharedMetadata(declarations)
    let appendVMEnd = targetData.segments.map { $0.0.vmAddr + $0.0.vmSize }.max() ?? (text.vmAddr + text.vmSize)
    let appendFileEnd = targetData.segments.map { $0.0.fileOffset + $0.0.fileSize }.max() ?? (data.fileOffset + data.fileSize)
    let layout = try planColdhookSharedLayout(
        executableVMEnd: appendVMEnd,
        executableFileEnd: appendFileEnd,
        writableVMEnd: appendVMEnd,
        writableFileEnd: appendFileEnd,
        stubSize: UInt64(declarations.count * 20),
        tableSize: UInt64(initialMetadata.data.count)
    )

    var finalSpecs: [ColdhookSharedSpec] = []
    var entries: [UInt64] = []
    for (index, declaration) in declarations.enumerated() {
        let magic = hookSymbols[index]
        let locator: String
        if magic.name.hasPrefix("_COLDHOOK_DYN_") {
            let fields = String(magic.name.dropFirst("_COLDHOOK_DYN_".count)).components(separatedBy: "__CH__")
            guard fields.count == 3 else {
                throw ColdhookSharedAssemblerError.targetNotFound("invalid dynamic declaration \(magic.name)")
            }
            let value = String(fields[1])
            locator = value.hasPrefix("COLDHOOK_ADDR_") ? "_" + value : value
        } else if magic.name.hasPrefix("_COLDHOOK_SYM_") {
            locator = String(magic.name.dropFirst("_COLDHOOK_SYM_".count))
        } else {
            locator = "_COLDHOOK_ADDR_" + String(magic.name.dropFirst("_COLDHOOK_ADDR_".count))
        }
        entries.append(try sharedTargetAddress(locator, resolver: targetResolver))
        let origAddress = layout.stubVMAddr + UInt64(index * 20 + 12)
        finalSpecs.append(ColdhookSharedSpec(
            hookID: declaration.hookID,
            handlerName: declaration.handlerName,
            origImageOffset: origAddress,
            origSlotKey: declaration.origSlotKey,
            flags: declaration.flags
        ))
    }

    let metadata = emitColdhookSharedMetadata(finalSpecs)
    var hooks: [ColdhookSharedHookPlan] = []
    for index in finalSpecs.indices {
        let stubAddress = layout.stubVMAddr + UInt64(index * 20)
        let slotAddress = layout.tableVMAddr + UInt64(metadata.handlerSlotOffsets[index])
        hooks.append(ColdhookSharedHookPlan(
            entryAddress: entries[index],
            stub: emitColdhookSharedStub(address: stubAddress, slotAddress: slotAddress),
            origAddress: stubAddress + 12,
            spec: finalSpecs[index]
        ))
    }
    return ColdhookSharedTargetPlan(layout: layout, metadata: metadata, hooks: hooks)
}

/// Single preparation entry point for the shared output assembler.  It deliberately
/// returns immutable assembly inputs; header/LINKEDIT emission remains in the caller.
func prepareColdhookSharedTarget(
    targetData: MachOMergeData,
    targetResolver: ColdhookSymbolResolver,
    userHooksData: MachOMergeData,
    userHooksResolver: ColdhookSymbolResolver
) throws -> ColdhookSharedAssembly {
    let plan = try planColdhookSharedTarget(targetData: targetData,
                                            targetResolver: targetResolver,
                                            userHooksData: userHooksData,
                                            userHooksResolver: userHooksResolver)
    var materialized = targetData
    for hook in plan.hooks {
        guard let index = materialized.segments.firstIndex(where: {
            hook.entryAddress >= $0.0.vmAddr && hook.entryAddress + 4 <= $0.0.vmAddr + $0.0.fileSize
        }) else {
            throw ColdhookSharedAssemblerError.targetNotFound(
                String(format: "entry 0x%llx", hook.entryAddress))
        }
        let segment = materialized.segments[index].0
        do {
            try patchColdhookSharedEntry(&materialized.segments[index].1,
                                         segmentVMAddr: segment.vmAddr,
                                         entryAddress: hook.entryAddress,
                                         stubAddress: hook.stub.address)
        } catch {
            throw ColdhookSharedAssemblerError.targetNotFound(String(describing: error))
        }
    }
    // Shared payload is emitted as two append segments by the output assembler;
    // do not extend target __TEXT/__DATA here.
    let sections = try makeColdhookSharedSections(plan)
    // `materializeColdhookSharedPayload` updates the segment command sizes in-place;
    // passing growth again would double-count the synthetic tail in load commands.
    let growth: [String: (vmSize: UInt64, fileSize: UInt64)] = [:]
    return ColdhookSharedAssembly(targetData: materialized,
                                  relocInfo: makeColdhookSharedRelocInfo(materialized), plan: plan,
                                  extraSections: sections, segmentGrowth: growth)
}
