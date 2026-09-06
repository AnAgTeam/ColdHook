#!/usr/bin/env python3
from pathlib import Path
import re, sys
root = Path(sys.argv[1]); out = Path(sys.argv[sys.argv.index('-o') + 1])
pat = re.compile(r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)'
                 r'|@ColdHookOffset\(\s*binary:\s*"([^"]+)"\s*,\s*offset:\s*(0x[0-9a-fA-F]+|[0-9]+)\s*\)')
found = [("sym", a, b) if a else ("addr", c, d)
         for p in sorted(root.rglob('*.swift')) for a, b, c, d in pat.findall(p.read_text())]
if not found: raise SystemExit('no @ColdHookMangled or @ColdHookOffset declarations found')
lines = ['#include <coldhook.h>', '']
for i, (kind, binary, target) in enumerate(found, 1):
    h = f'coldhook_handler_{i}'
    macro = f'CH_DYN_SYM("{binary}", "{target}", {h});' if kind == "sym" else f'CH_DYN_ADDR("{binary}", {target}, {h});'
    lines += [f'extern void {h}(void);', f'__attribute__((used)) static void *keep_{i} = (void *)&{h};', macro, '']
out.parent.mkdir(parents=True, exist_ok=True); out.write_text('\n'.join(lines))
