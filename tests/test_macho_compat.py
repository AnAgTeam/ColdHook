from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_non_required_load_commands_do_not_set_lc_req_dyld():
    source = (ROOT / "vendor/MachOMerger/Sources/MachOMerger/MachOCompat.swift").read_text()
    expected = {
        "LC_SEGMENT_SPLIT_INFO": "0x1e",
        "LC_FUNCTION_STARTS": "0x26",
        "LC_DATA_IN_CODE": "0x29",
        "LC_SOURCE_VERSION": "0x2a",
        "LC_DYLIB_CODE_SIGN_DRS": "0x2b",
        "LC_BUILD_VERSION": "0x32",
    }
    for name, value in expected.items():
        assert f"let {name}: UInt32 = {value}\n" in source


def test_required_dyld_load_commands_keep_lc_req_dyld():
    source = (ROOT / "vendor/MachOMerger/Sources/MachOMerger/MachOCompat.swift").read_text()
    assert "let LC_DYLD_EXPORTS_TRIE: UInt32 = 0x33 | 0x80000000" in source
    assert "let LC_DYLD_CHAINED_FIXUPS: UInt32 = 0x34 | 0x80000000" in source
