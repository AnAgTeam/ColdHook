#!/usr/bin/env python3
from pathlib import Path
import re, shutil, sys

src = Path(sys.argv[1]); out = Path(sys.argv[2]); glue = Path(sys.argv[3])
pat = re.compile(r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)')
found = []
for p in sorted(src.rglob('*.swift')):
    text = p.read_text()
    found += pat.findall(text)
    dst = out / p.relative_to(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(pat.sub('', text))
if not found:
    raise SystemExit('no ColdHookMangled declarations found')
lines = ['#include <coldhook.h>', '']
for i, (binary, target) in enumerate(found, 1):
    handler = f'coldhook_handler_{i}'
    lines += [f'extern void {handler}(void);',
              f'__attribute__((used)) static void *keep_{i} = (void *)&{handler};',
              f'CH_DYN_SYM("{binary}", "{target}", {handler});', '']
glue.parent.mkdir(parents=True, exist_ok=True)
glue.write_text('\n'.join(lines))
