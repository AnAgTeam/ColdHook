#!/usr/bin/env python3
from pathlib import Path
import re, sys
root = Path(sys.argv[1]); out = Path(sys.argv[sys.argv.index('-o') + 1])
pat = re.compile(r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)')
found = [x for p in sorted(root.rglob('*.swift')) for x in pat.findall(p.read_text())]
if not found: raise SystemExit('no @ColdHookMangled declarations found')
lines = ['#include <coldhook.h>', '']
for i, (binary, target) in enumerate(found, 1):
    h = f'coldhook_handler_{i}'
    lines += [f'extern void {h}(void);', f'__attribute__((used)) static void *keep_{i} = (void *)&{h};', f'CH_DYN_SYM("{binary}", "{target}", {h});', '']
out.parent.mkdir(parents=True, exist_ok=True); out.write_text('\n'.join(lines))
