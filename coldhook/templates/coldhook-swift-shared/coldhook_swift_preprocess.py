#!/usr/bin/env python3
from pathlib import Path
import re, shutil, sys

src = Path(sys.argv[1]); out = Path(sys.argv[2]); glue = Path(sys.argv[3])
pat = re.compile(r'@ColdHookMangled\(\s*binary:\s*"([^"]+)"\s*,\s*target:\s*"([^"]+)"\s*\)'
                 r'|@ColdHookOffset\(\s*binary:\s*"([^"]+)"\s*,\s*offset:\s*(0x[0-9a-fA-F]+|[0-9]+)\s*\)')
func_pat = re.compile(r'(?P<prefix>(?:public\s+|internal\s+|private\s+|fileprivate\s+|)func\s+)'
                       r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<sig>\([^\{]*\)\s*(?:->\s*[^\{]+)?)\s*\{')
found = []
for p in sorted(src.rglob('*.swift')):
    text = p.read_text()
    for match in re.finditer(r'(?:' + pat.pattern + r')\s*(?:(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^\n]*\))?)\s*)*'
                            r'(?:public\s+|internal\s+|private\s+|fileprivate\s+)?func\s+([A-Za-z_][A-Za-z0-9_]*)', text):
        found.append(("sym", match.group(1), match.group(2), match.group(5), None) if match.group(1)
                     else ("addr", match.group(3), None, match.group(5), match.group(4)))
    dst = out / p.relative_to(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cleaned = pat.sub('', text)
    def add_orig(match):
        name = match.group('name')
        if name not in {item[3] for item in found}:
            return match.group(0)
        sig = match.group('sig').strip()
        orig_name = f'orig_{name}'
        orig = f'@_silgen_name("{orig_name}")\nprivate func {orig_name}{sig}\n\n'
        return orig + f'@_silgen_name("{name}")\ninternal func {name}{sig} {{'
    cleaned = func_pat.sub(add_orig, cleaned)
    dst.write_text(cleaned)
if not found:
    raise SystemExit('no ColdHookMangled or ColdHookOffset declarations found')
lines = ['#include <coldhook.h>', '']
for i, (kind, binary, target, handler, offset) in enumerate(found, 1):
    lines += [f'extern void {handler}(void);',
              f'__attribute__((used)) static void *keep_{i} = (void *)&{handler};',
              (f'CH_DYN_SYM("{binary}", "{target}", {handler});' if kind == "sym"
               else f'CH_DYN_ADDR("{binary}", {offset}, {handler});'), '']
glue.parent.mkdir(parents=True, exist_ok=True)
glue.write_text('\n'.join(lines))
exports = []
for kind, binary, target, handler, offset in found:
    locator = target if kind == "sym" else f"COLDHOOK_ADDR_{offset}"
    suffix = f"{kind.upper()}_{binary}__CH__{locator}__CH__{handler}"
    exports += [f"_COLDHOOK_DYN_{suffix}", f"_COLDHOOK_ORIG_{suffix}"]
glue.with_suffix('.exports').write_text('\n'.join(exports) + '\n')
