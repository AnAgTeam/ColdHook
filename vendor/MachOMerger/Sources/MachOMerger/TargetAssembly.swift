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

func makeColdhookSharedPlacements(_ plan: ColdhookSharedTargetPlan) -> [ColdhookFilePlacement] {
    [
        ColdhookFilePlacement(fileOffset: Int(plan.layout.stubFileOffset),
                              data: materializeColdhookSharedStubs(plan)),
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
