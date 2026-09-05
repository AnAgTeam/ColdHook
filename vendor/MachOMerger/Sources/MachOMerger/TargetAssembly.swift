import Foundation

struct ColdhookFilePlacement {
    let fileOffset: Int
    let data: Data
}

struct ColdhookMachOOutputPayload {
    let header: Data
    let targetData: Data
    let secondaryPlacements: [ColdhookFilePlacement]
    let linkedit: Data
}

func assembleColdhookSegmentData(_ relocInfo: RelocInfo) -> Data {
    var output = Data()
    for segment in relocInfo.segRel {
        output.append(segment.1[0].data)
        if segment.1.count > 1 { output.append(segment.1[1].data) }
    }
    return output
}

/// Writes non-overlapping payloads at their requested file offsets.
func assembleColdhookPlacements(_ placements: [ColdhookFilePlacement]) -> Data {
    var output = Data()
    for placement in placements {
        precondition(placement.fileOffset >= 0, "negative file placement")
        precondition(output.count <= placement.fileOffset, "overlapping file placements")
        if output.count < placement.fileOffset {
            output.append(Data(repeating: 0, count: placement.fileOffset - output.count))
        }
        output.append(placement.data)
    }
    return output
}

func replaceColdhookHeader(_ output: inout Data, header: Data, limit: Int) {
    precondition(header.count <= limit, "Mach-O header exceeds reserved header padding")
    if output.count < limit {
        output.append(Data(repeating: 0, count: limit - output.count))
    }
    output.replaceSubrange(0..<limit, with: header + Data(repeating: 0, count: limit - header.count))
}

func makeColdhookSharedPlacements(_ plan: ColdhookSharedTargetPlan,
                                  originalTargetData: MachOMergeData? = nil) throws -> [ColdhookFilePlacement] {
    var stubs = Data()
    for hook in plan.hooks {
        stubs.append(hook.stub.bytes)
        var original = Data(repeating: 0, count: 8)
        if let originalTargetData,
           let source = originalTargetData.segments.first(where: {
               hook.entryAddress >= $0.0.vmAddr && hook.entryAddress + 4 <= $0.0.vmAddr + $0.0.fileSize
           }) {
            let sourceOffset = Int(hook.entryAddress - source.0.vmAddr)
            let instruction = source.1.withUnsafeBytes {
                $0.load(fromByteOffset: sourceOffset, as: UInt32.self)
            }
            let branch = try encodeColdhookB(from: hook.origAddress + 4, to: hook.entryAddress + 4)
            original.replaceSubrange(0..<4, with: Data(fromObject: instruction))
            original.replaceSubrange(4..<8, with: Data(fromObject: branch))
        }
        stubs.append(original)
    }
    return [
        ColdhookFilePlacement(fileOffset: Int(plan.layout.stubFileOffset),
                              data: stubs),
        ColdhookFilePlacement(fileOffset: Int(plan.layout.tableFileOffset),
                              data: plan.metadata.data)
    ].sorted { $0.fileOffset < $1.fileOffset }
}

func assembleColdhookFinalOutput(header: Data, segmentData: Data, linkedit: Data,
                                 headerLimit: Int = 0x4000) -> Data {
    precondition(header.count <= headerLimit, "Mach-O header too large")
    let paddedHeader = header + Data(repeating: 0, count: headerLimit - header.count)
    return paddedHeader + segmentData + linkedit
}

func assembleColdhookMachO(_ payload: ColdhookMachOOutputPayload,
                           headerLimit: Int = 0x4000) -> Data {
    var body = payload.targetData
    for placement in payload.secondaryPlacements {
        precondition(placement.fileOffset >= body.count,
                     "secondary placement overlaps target payload")
        if body.count < placement.fileOffset {
            body.append(Data(repeating: 0, count: placement.fileOffset - body.count))
        }
        body.append(placement.data)
    }
    return assembleColdhookFinalOutput(header: payload.header, segmentData: body,
                                       linkedit: payload.linkedit, headerLimit: headerLimit)
}
