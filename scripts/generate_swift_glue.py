#!/usr/bin/env python3
"""Generate ColdHook C glue from @ColdHookMangled/@ColdHookOffset annotations."""
from __future__ import annotations
import argparse
import re
from pathlib import Path

PATTERN = re.compile(
    r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)'
    r'|@ColdHookOffset\(\s*binary:\s*"([^"]+)"\s*,\s*offset:\s*(0x[0-9a-fA-F]+|[0-9]+)\s*\)'
    r'\s*(?:@[^\n]+\n\s*)*(?:public\s+)?func\s+([A-Za-z_]\w*)'
)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", type=Path)
    ap.add_argument("--output", "-o", type=Path, required=True)
    ns = ap.parse_args()
    hooks = []
    next_index = 1
    for path in sorted(ns.sources.rglob("*.swift")):
        text = path.read_text()
        for sb, st, ab, ao, fn in PATTERN.findall(text):
            index = next_index
            next_index += 1
            hooks.append(("sym", sb, st, fn, index) if sb else ("addr", ab, ao, fn, index))
    if not hooks:
        raise SystemExit("coldhook-swift: no @ColdHookMangled or @ColdHookOffset declarations found")
    lines = ["#include <coldhook.h>", ""]
    for kind, binary, target, fn, index in hooks:
        handler = f"coldhook_handler_{index}"
        lines += [f"extern void {handler}(void);",
                  f"__attribute__((used)) static void *keep_{index} = (void *)&{handler};",
                  (f'CH_DYN_SYM("{binary}", "{target}", {handler});' if kind == "sym"
                   else f'CH_DYN_ADDR("{binary}", {target}, {handler});'), ""]
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text("\n".join(lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
