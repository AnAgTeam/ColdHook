// Single symbol source for all ColdHook backends.  Keep symtab/export-trie
// handling here so embedded and shared modes cannot drift apart.
import Foundation

struct ColdhookSym { let name: String; let value: UInt64; let type: UInt8 }

struct ColdhookSymbolResolver {
    let symbols: [ColdhookSym]

    func first(_ name: String, definedOnly: Bool = false) -> ColdhookSym? {
        symbols.first { sym in
            sym.name == name && (!definedOnly || (sym.type & 0x0e) == 0x0e)
        }
    }

    func all(prefix: String) -> [ColdhookSym] {
        symbols.filter { $0.name.starts(with: prefix) }
    }
}

func makeColdhookSymbolResolver(_ st: (symbols: Data, strings: Data)?) -> ColdhookSymbolResolver {
    guard let st else { return ColdhookSymbolResolver(symbols: []) }
    var result: [ColdhookSym] = []
    for i in 0..<(st.symbols.count / 16) {
        let base = UInt(i * 16)
        let strx = st.symbols.getGeneric(type: UInt32.self, offset: base)
        let type = st.symbols.getGeneric(type: UInt8.self, offset: base + 4)
        let value = st.symbols.getGeneric(type: UInt64.self, offset: base + 8)
        // STABS/debug entries are not linkable symbols and may duplicate real names.
        guard (type & 0xe0) == 0, Int(strx) < st.strings.count else { continue }
        let name = (try? st.strings.advanced(by: Int(strx)).toString(encoding: .utf8,
                                                                       nullTerminated: true)) ?? ""
        if !name.isEmpty { result.append(ColdhookSym(name: name, value: value, type: type)) }
    }
    return ColdhookSymbolResolver(symbols: result)
}
