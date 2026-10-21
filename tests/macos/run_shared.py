#!/usr/bin/env python3
"""End-to-end smoke test for MachOMerger's shared-table backend."""
import json
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from coldhook.toolchain import ensure_merger

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = ensure_merger()
BUILD = os.path.join(HERE, "build", "shared_mode")

LC_SEGMENT_64 = 0x19
LC_DYLD_CHAINED_FIXUPS = 0x80000034


def macho_metadata(path):
    data = open(path, "rb").read()
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0xfeedfacf:
        raise RuntimeError(f"not a little-endian Mach-O 64 binary: {path}")
    command_count = struct.unpack_from("<I", data, 16)[0]
    position = 32
    segments = []
    sections = {}
    chained = None
    for _ in range(command_count):
        if position + 8 > len(data):
            raise RuntimeError("truncated Mach-O load commands")
        command, size = struct.unpack_from("<II", data, position)
        if size < 8 or position + size > len(data):
            raise RuntimeError("invalid Mach-O load command size")
        if command == LC_SEGMENT_64:
            segment_name = data[position + 8:position + 24].rstrip(b"\0").decode("ascii")
            section_count = struct.unpack_from("<I", data, position + 64)[0]
            segments.append(segment_name)
            for index in range(section_count):
                section = position + 72 + index * 80
                if section + 80 > position + size:
                    raise RuntimeError("truncated Mach-O section table")
                section_name = data[section:section + 16].rstrip(b"\0").decode("ascii")
                section_segment = data[section + 16:section + 32].rstrip(b"\0").decode("ascii")
                alignment = struct.unpack_from("<I", data, section + 52)[0]
                sections[(section_segment, section_name)] = alignment
        elif command == LC_DYLD_CHAINED_FIXUPS:
            data_offset, data_size = struct.unpack_from("<II", data, position + 8)
            blob = data[data_offset:data_offset + data_size]
            if len(blob) != data_size or len(blob) < 28:
                raise RuntimeError("truncated chained-fixups payload")
            starts_offset, imports_offset, symbols_offset = struct.unpack_from("<III", blob, 4)
            segment_count = struct.unpack_from("<I", blob, starts_offset)[0]
            offsets = list(struct.unpack_from(
                f"<{segment_count}I", blob, starts_offset + 4))
            chained = {
                "data_size": data_size,
                "starts_offset": starts_offset,
                "imports_offset": imports_offset,
                "symbols_offset": symbols_offset,
                "segment_count": segment_count,
                "offsets": offsets,
            }
        position += size
    if chained is None:
        raise RuntimeError("LC_DYLD_CHAINED_FIXUPS is missing")
    return {"segments": segments, "sections": sections, "chained": chained}


def verify_shared_metadata(target, merged):
    before = macho_metadata(target)
    after = macho_metadata(merged)
    old = before["chained"]
    new = after["chained"]

    if len(after["segments"]) != len(before["segments"]) + 2:
        raise RuntimeError("shared output did not add exactly two segment commands")
    if new["segment_count"] != len(after["segments"]):
        raise RuntimeError("chained-fixups segment count does not match LC_SEGMENT_64 count")
    if new["data_size"] != old["data_size"] + 8:
        raise RuntimeError("chained-fixups payload was not expanded for two segments")
    if new["offsets"][-2:] != [0, 0]:
        raise RuntimeError("new chained-fixups segment offsets are not empty")

    insertion = old["starts_offset"] + 4 + old["segment_count"] * 4
    expected_offsets = [value + 8 if value and old["starts_offset"] + value >= insertion else value
                        for value in old["offsets"]] + [0, 0]
    if new["offsets"] != expected_offsets:
        raise RuntimeError("chained-fixups segment offsets were not relocated correctly")
    for field in ("imports_offset", "symbols_offset"):
        expected = old[field] + (8 if old[field] >= insertion else 0)
        if new[field] != expected:
            raise RuntimeError(f"chained-fixups {field} was not relocated correctly")

    probe = ("__DATA", "__coldhook_probe")
    if before["sections"].get(probe) != 4:
        raise RuntimeError("fixture's 16-byte section name/alignment is invalid")
    if after["sections"].get(probe) != before["sections"][probe]:
        raise RuntimeError("shared output corrupted a 16-byte section name or alignment")

def run(cmd, **kw):
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kw)

def check(cmd, what):
    if run(cmd, capture_output=True).returncode:
        raise RuntimeError(what)

def cc(*args):
    return ["xcrun", "clang", "-arch", "arm64", *args]

def main():
    os.makedirs(BUILD, exist_ok=True)
    for name in os.listdir(BUILD):
        os.remove(os.path.join(BUILD, name))

    target = os.path.join(BUILD, "libtarget.dylib")
    other_target = os.path.join(BUILD, "libother.dylib")
    other_merged = os.path.join(BUILD, "libother.shared.dylib")
    runtime = os.path.join(BUILD, "libcoldhook.dylib")
    hooks = os.path.join(BUILD, "libhooks.dylib")
    merged = os.path.join(BUILD, "libtarget.shared.dylib")
    report_path = os.path.join(BUILD, "shared-report.json")
    other_report_path = os.path.join(BUILD, "other-shared-report.json")
    driver = os.path.join(BUILD, "driver")
    target_src = os.path.join(BUILD, "target.c")
    hooks_src = os.path.join(BUILD, "hooks.c")
    driver_src = os.path.join(BUILD, "driver.c")

    with open(target_src, "w") as f:
        f.write('#include <unistd.h>\n'
                'const char *domain_for(int);\n'
                'void *coldhook_writable_anchor = (void *)domain_for;\n'
                '__attribute__((used, visibility("default"), aligned(16), '
                'section("__DATA,__coldhook_probe"))) unsigned char coldhook_probe[16];\n'
                '__attribute__((visibility("default"))) const char *domain_for(int n){\n'
                '  if (getpid() > 0 && n == 0) return "ORIG"; __builtin_trap(); }\n'
                '__attribute__((visibility("default"))) const char *other_for(int n){\n'
                '  if (getpid() > 0 && n == 0) return "OTHER-ORIG"; __builtin_trap(); }\n'
                '__attribute__((visibility("default"))) const char *offset_for(int n){\n'
                '  if (getpid() > 0 && n == 0) return "OFFSET-ORIG"; __builtin_trap(); }\n')
    with open(hooks_src, "w") as f:
        f.write('#include "coldhook_shared.h"\n#include "coldhook.h"\n'
                '#include <stdlib.h>\nextern void *coldhook_shared_orig_lookup(unsigned long long);\n'
                'CH_DECLARE_ORIG(domain_for_hook, const char *, int);\n'
                'CH_DECLARE_GATE(domain_for_hook);\n'
                'const char *domain_for_hook(int);\n'
                '__attribute__((constructor)) static void boot(void){\n'
                '  if(getenv("CH_ON")) CH_GATE_ENABLE(domain_for_hook);\n'
                '  if(getenv("CH_OFF")) CH_GATE_DISABLE(domain_for_hook);\n}\n'
                '__attribute__((visibility("default"))) const char *domain_for_hook(int n){\n'
                '  if (coldhook_orig_domain_for_hook(n)[0] != \'O\') return "BAD-ORIG";\n'
                '  return "SHARED-HOOK";\n}\n')
    with open(hooks_src, "a") as f:
        # The shared backend matches a target by its filename.  Keep the
        # selector aligned with libtarget.dylib, while libother.dylib below
        # exercises the intentional no-op path.
        f.write('CH_DYN_SYM_GATED("libtarget.dylib", "domain_for", domain_for_hook);\n'
                'CH_DECLARE_ORIG(other_for_hook, const char *, int);\n'
                '__attribute__((visibility("default"))) const char *other_for_hook(int n){\n'
                '  if (!coldhook_shared_find_orig((void *)&other_for_hook)) return "BAD-LOOKUP";\n'
                '  if (coldhook_orig_other_for_hook(n)[0] != \'O\') return "BAD-OTHER-ORIG";\n'
                '  return "OTHER-HOOK";\n}\n'
                'CH_DYN_SYM("libtarget.dylib", "other_for", other_for_hook);\n')
    with open(driver_src, "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*name=c>2?v[2]:"domain_for";const char*(*fn)(int)=dlsym(h,name);'
                'if(!fn){fprintf(stderr,"dlsym failed\\n");return 2;}'
                'printf("%s=%s\\n",name,fn(0));return 0;}\n')

    split = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
    # Build the runtime beside the fixture.  This makes the harness independent
    # of an unrelated /tmp/libcoldhook.dylib (which may be absent or built for
    # iOS rather than macOS).
    check(cc("-dynamiclib", "-I", os.path.join(ROOT, "coldhook", "include"),
             "-install_name", "@loader_path/libcoldhook.dylib",
             "-o", runtime, os.path.join(ROOT, "coldhook", "shared_runtime.c")),
          "shared runtime build")
    check(cc("-dynamiclib", *split, "-Wl,-headerpad,0x4000", "-install_name", "@loader_path/libtarget.dylib",
              "-o", target, target_src), "target build")
    target_nm = subprocess.check_output(["nm", "-gU", target], text=True)
    offset_line = next((line for line in target_nm.splitlines()
                        if line.split()[-1:] == ["_offset_for"]), None)
    if not offset_line:
        raise RuntimeError("offset_for address was not found")
    offset = "0x" + offset_line.split()[0]
    with open(hooks_src, "a") as f:
        f.write('CH_DECLARE_ORIG(offset_for_hook, const char *, int);\n'
                '__attribute__((visibility("default"))) const char *offset_for_hook(int n){\n'
                '  if (coldhook_orig_offset_for_hook(n)[0] != \'O\') return "BAD-OFFSET-ORIG";\n'
                '  return "OFFSET-HOOK";\n}\n'
                f'CH_DYN_ADDR("libtarget.dylib", {offset}, offset_for_hook);\n')
    check(cc("-dynamiclib", *split, "-I", os.path.join(ROOT, "coldhook", "include"),
              "-L", BUILD, "-lcoldhook",
              "-Wl,-not_for_dyld_shared_cache",
              "-install_name", "@loader_path/libhooks.dylib", "-o", hooks, hooks_src),
          "hooks build")
    exported = {line.split()[-1] for line in subprocess.check_output(
        ["nm", "-gU", hooks], text=True).splitlines() if line.split()}
    expected_exports = {
        "_COLDHOOK_DYN_SYM_libtarget.dylib__CH__domain_for__CH__coldhook_gate_domain_for_hook",
        "_COLDHOOK_ORIG_SYM_libtarget.dylib__CH__domain_for__CH__coldhook_gate_domain_for_hook",
        "_COLDHOOK_DYN_SYM_libtarget.dylib__CH__other_for__CH__other_for_hook",
        "_COLDHOOK_ORIG_SYM_libtarget.dylib__CH__other_for__CH__other_for_hook",
        f"_COLDHOOK_DYN_ADDR_libtarget.dylib__CH__COLDHOOK_ADDR_{offset}__CH__offset_for_hook",
        f"_COLDHOOK_ORIG_ADDR_libtarget.dylib__CH__COLDHOOK_ADDR_{offset}__CH__offset_for_hook",
    }
    if exported != expected_exports:
        raise RuntimeError(f"unexpected hook exports: {sorted(exported)}")
    result = run([MERGER, target, hooks, merged, "--mode", "shared",
                  "--report-json", report_path],
                 capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode:
        raise RuntimeError("shared merge failed")
    report = json.load(open(report_path))
    if (report.get("version") != 1 or report.get("status") != "patched"
            or {hook["locator"] for hook in report.get("hooks", [])}
            != {"domain_for", "other_for", f"COLDHOOK_ADDR_{offset}"}):
        raise RuntimeError(f"unexpected shared JSON report: {report}")
    if {hook["handler"] for hook in report["hooks"]} != {
            "coldhook_gate_domain_for_hook", "other_for_hook", "offset_for_hook"}:
        raise RuntimeError(f"unexpected handlers in shared JSON report: {report}")
    verify_shared_metadata(target, merged)
    # The very same dylib is deliberately offered to another Mach-O.  Its
    # CH_DYN selector is libtarget, so MachOMerger must leave libother untouched.
    shutil.copyfile(target, other_target)
    result = run([MERGER, other_target, hooks, other_merged, "--mode", "shared",
                  "--report-json", other_report_path],
                 capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "no applicable hooks" not in result.stdout:
        raise RuntimeError("shared selector no-op failed")
    other_report = json.load(open(other_report_path))
    if other_report.get("status") != "no-applicable-hooks" or other_report.get("hooks") != []:
        raise RuntimeError(f"unexpected shared no-op JSON report: {other_report}")
    if open(other_target, "rb").read() != open(other_merged, "rb").read():
        raise RuntimeError("shared no-op changed target bytes")
    check(["codesign", "-f", "-s", "-", merged], "codesign shared output")
    load = subprocess.check_output(["otool", "-l", merged], text=True)
    if "__coldhook" not in load or "libhooks.dylib" not in load:
        raise RuntimeError("shared metadata section or hooks dependency missing")
    check(cc("-o", driver, driver_src), "driver build")
    result = run([driver, merged], capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "domain_for=ORIG" not in result.stdout:
        raise RuntimeError("shared gated hook did not default to ORIG")
    result = run([driver, merged], capture_output=True, text=True,
                 env={**os.environ, "CH_ON": "1"})
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "SHARED-HOOK" not in result.stdout:
        raise RuntimeError("shared gated hook did not enable")
    result = run([driver, merged], capture_output=True, text=True,
                 env={**os.environ, "CH_ON": "1", "CH_OFF": "1"})
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "domain_for=ORIG" not in result.stdout:
        raise RuntimeError("shared gated hook did not disable")
    result = run([driver, merged, "offset_for"], capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "offset_for=OFFSET-HOOK" not in result.stdout:
        raise RuntimeError("shared CH_DYN_ADDR + ORIG failed")
    result = run([driver, merged, "other_for"], capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "other_for=OTHER-HOOK" not in result.stdout:
        raise RuntimeError("shared handler-address orig lookup failed")
    print("OK: shared table bootstrap + scoped exports + gated dispatch + address ORIG")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        sys.exit(1)
