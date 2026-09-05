#!/usr/bin/env python3
"""Generate ColdHook C glue from prototype @ColdHookMangled annotations."""
from __future__ import annotations
import argparse
import re
from pathlib import Path

PATTERN = re.compile(
    r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)'
    r'\s*(?:@[^\n]+\n\s*)*(?:public\s+)?func\s+([A-Za-z_]\w*)'
)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", type=Path)
    ap.add_argument("--output", "-o", type=Path, required=True)
    ns = ap.parse_args()
    hooks = []
    for path in sorted(ns.sources.rglob("*.swift")):
        text = path.read_text()
        for index, (binary, target, fn) in enumerate(PATTERN.findall(text), 1):
            hooks.append((binary, target, fn, index))
    if not hooks:
        raise SystemExit("coldhook-swift: no @ColdHookMangled declarations found")
    lines = ["#include <coldhook.h>", ""]
    for binary, target, fn, index in hooks:
        handler = f"coldhook_handler_{index}"
        lines += [f"extern void {handler}(void);",
                  f"__attribute__((used)) static void *keep_{index} = (void *)&{handler};",
                  f'CH_DYN_SYM("{binary}", "{target}", {handler});', ""]
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text("\n".join(lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
