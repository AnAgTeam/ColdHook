#!/usr/bin/env python3
"""Regression coverage for the public shared Logos template/prepass contract."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coldhook.logos_prepass import prepass


def main():
    root = ROOT
    template = root / "coldhook" / "templates" / "coldhook-shared"
    makefile = (template / "Makefile").read_text()
    tweak = (template / "Tweak.x").read_text()
    readme = (template / "README.md").read_text()
    assert "coldhook_shared.h" in tweak
    assert "-lcoldhook" in makefile and "COLDHOOK_RUNTIME_DIR" in makefile
    assert "0x1234" in readme and "%group" in readme

    source = '''
%hookf_shared("MainBinary", int, by_name, int x) { return %orig(x); }
%hookf_shared("MainBinary", int, 0x1234, int x) { return %orig(x); }
%group Optional
%hookf_shared("MainBinary", int, grouped, int x) { return %orig(x); }
%end
%init(Optional)
'''
    out = prepass(source)
    assert 'CH_DYN_SYM("MainBinary", "by_name", _chf_by_name);' in out
    assert 'CH_DYN_ADDR("MainBinary", 0x1234, _chf_addr_1234);' in out
    assert 'CH_DYN_SYM_GATED("MainBinary", "grouped", _chf_grouped);' in out
    assert 'coldhook_disp__chf_grouped = (void*)&_chf_grouped;' in out
    print("OK: shared Logos template + symbol/address/group/orig contract")


if __name__ == "__main__":
    main()
