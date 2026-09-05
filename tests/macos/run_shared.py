#!/usr/bin/env python3
"""End-to-end smoke test for MachOMerger's shared-table backend."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", "MachOMerger")
RUNTIME = "/tmp/libcoldhook.dylib"
BUILD = os.path.join(HERE, "build_shared_mode")

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
    hooks = os.path.join(BUILD, "libhooks.dylib")
    merged = os.path.join(BUILD, "libtarget.shared.dylib")
    driver = os.path.join(BUILD, "driver")
    target_src = os.path.join(BUILD, "target.c")
    hooks_src = os.path.join(BUILD, "hooks.c")
    driver_src = os.path.join(BUILD, "driver.c")

    with open(target_src, "w") as f:
        f.write('#include <unistd.h>\n'
                'const char *domain_for(int);\n'
                'void *coldhook_writable_anchor = (void *)domain_for;\n'
                '__attribute__((visibility("default"))) const char *domain_for(int n){\n'
                '  if (getpid() > 0 && n == 0) return "ORIG"; __builtin_trap(); }\n')
    with open(hooks_src, "w") as f:
        f.write('#include "coldhook_shared.h"\n'
                'extern void *coldhook_shared_orig_lookup(unsigned long long);\n'
                '__attribute__((constructor)) static void boot(void){ (void)coldhook_shared_orig_lookup; }\n'
                '__attribute__((visibility("default"))) const char *MACHOMERGER_HOOK_domain_for(int n){\n'
                '  (void)n; return "SHARED-HOOK";\n}\n')
    with open(driver_src, "w") as f:
        f.write('#include <dlfcn.h>\n#include <stdio.h>\n'
                'int main(int c,char**v){void*h=dlopen(v[1],RTLD_NOW);'
                'if(!h){fprintf(stderr,"dlopen: %s\\n",dlerror());return 1;}'
                'const char*(*fn)(int)=dlsym(h,"domain_for");'
                'if(!fn){fprintf(stderr,"dlsym failed\\n");return 2;}'
                'printf("domain_for=%s\\n",fn(0));return 0;}\n')

    split = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]
    check(cc("-dynamiclib", *split, "-Wl,-headerpad,0x4000", "-install_name", "@loader_path/libtarget.dylib",
              "-o", target, target_src), "target build")
    check(cc("-dynamiclib", *split, "-I", os.path.join(ROOT, "coldhook", "include"),
              "-L", "/tmp", "-lcoldhook", "-Wl,-rpath,/tmp",
              "-Wl,-not_for_dyld_shared_cache",
              "-install_name", "@loader_path/libhooks.dylib", "-o", hooks, hooks_src),
          "hooks build")
    result = run([MERGER, target, hooks, merged, "--mode", "shared"],
                 capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode:
        raise RuntimeError("shared merge failed")
    load = subprocess.check_output(["otool", "-l", merged], text=True)
    if "__coldhook" not in load or "libhooks.dylib" not in load:
        raise RuntimeError("shared metadata section or hooks dependency missing")
    check(cc("-o", driver, driver_src), "driver build")
    result = run([driver, merged], capture_output=True, text=True)
    sys.stdout.write(result.stdout); sys.stderr.write(result.stderr)
    if result.returncode or "SHARED-HOOK" not in result.stdout:
        raise RuntimeError("shared hook did not execute")
    print("OK: shared table bootstrap + hook dispatch")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        sys.exit(1)
