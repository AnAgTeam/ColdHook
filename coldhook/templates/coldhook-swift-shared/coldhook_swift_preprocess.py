#!/usr/bin/env python3
from pathlib import Path
import re, shutil, sys

src = Path(sys.argv[1]); out = Path(sys.argv[2]); glue = Path(sys.argv[3])
pat = re.compile(r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)')
func_pat = re.compile(r'(?P<prefix>(?:public\s+|internal\s+|private\s+|fileprivate\s+|)func\s+)'
                       r'(?P<name>coldhook_handler_\d+)\s*(?P<sig>\([^\{]+\)\s*(?:->\s*[^\{]+)?)\s*\{')
found = []
for p in sorted(src.rglob('*.swift')):
    text = p.read_text()
    found += pat.findall(text)
    dst = out / p.relative_to(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cleaned = pat.sub('', text)
    def add_orig(match):
        name = match.group('name')
        sig = match.group('sig').strip()
        orig_name = f'orig_{name}'
        orig = f'@_silgen_name("{orig_name}")\nprivate func {orig_name}{sig}\n\n'
        return orig + f'@_silgen_name("{name}")\n' + match.group(0)
    cleaned = func_pat.sub(add_orig, cleaned)
    dst.write_text(cleaned)
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
