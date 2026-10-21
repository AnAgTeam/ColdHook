"""CLI ColdHook: info / merge (одиночный) / patch (по конфигу)."""
from __future__ import annotations

import argparse
import sys
import logging
import importlib
import re

from .diagnostics import DiagnosticError, log, stage
from . import console, toolchain

from . import __version__, config, macho
from .build import PatchError, patch_all, patch_target
from .config import Signing, Target
from .toolchain import ToolError


def _add_sign_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sign", default="-", metavar="ID",
                   help="codesign identity ('-' = ad hoc, default) or certificate name")
    p.add_argument("--ldid", action="store_true", help="sign using ldid instead of codesign")
    p.add_argument("--ent", metavar="FILE", help="signing entitlements")


def cmd_info(args) -> int:
    info = macho.inspect(args.binary)
    print(f"path:     {info.path}")
    print(f"archs:    {', '.join(info.archs)}{'  (FAT)' if info.is_fat else ''}")
    print(f"slice:    {info.arch}")
    print(f"filetype: {info.filetype}")
    print(f"platform: {info.platform} {info.minos}")
    print(f"cryptid:  {info.cryptid}{'  (ENCRYPTED)' if info.encrypted else ''}")
    return 0


def cmd_merge(args) -> int:
    if args.dylib and args.src:
        print("Specify either --src or --dylib, not both", file=sys.stderr)
        return 2
    if not args.dylib and not args.src:
        print("A hook is required: --src <file> (repeatable) or --dylib <prebuilt>", file=sys.stderr)
        return 2
    target = Target(name=args.name or "merge", binary=args.target,
                    sources=args.src or [], dylib=args.dylib, out=args.out,
                    ldflags=args.ldflags or [], allow_new_dylibs=args.allow_new_dylibs)
    signing = Signing(identity=args.sign, entitlements=args.ent, use_ldid=args.ldid)
    out = args.out or (args.target + ".coldhook")
    _check_patch_tools([target], signing, not args.no_sign)
    patch_target(target, signing, args.target, out, do_sign=not args.no_sign)
    return 0


def cmd_patch(args) -> int:
    cfg = config.load(args.config)
    print(f"Config: {args.config}  ({len(cfg.targets)} targets)")
    _check_patch_tools(cfg.targets, cfg.signing, not args.no_sign)
    patch_all(cfg, do_sign=not args.no_sign)
    return 0


def cmd_ipa(args) -> int:
    from . import ipa
    cfg = config.load(args.config)
    print(f"Config: {args.config}  ({len(cfg.targets)} targets)")
    # для бандла подпись по умолчанию ВЫКЛ; включается явным --sign-bundle
    _check_patch_tools(cfg.targets, cfg.signing, args.sign_bundle)
    ipa.patch_bundle(args.input, cfg, args.out, do_sign=args.sign_bundle)
    return 0


def cmd_shared(args) -> int:
    from . import ipa
    toolchain.ensure_merger()
    if args.sign_bundle:
        toolchain.require_tools("codesign")
    return 0 if ipa.patch_shared_bundle(args.input, args.dylib, args.out,
                                        do_sign=args.sign_bundle,
                                        import_path=args.import_path,
                                        runtime=args.runtime,
                                        verbose=args.verbose,
                                        skip_unsupported=args.skip_unsupported) else 1


def _check_python_dependencies():
    with stage("Checking Python dependencies"):
        try:
            module = importlib.import_module("lief")
            version = getattr(module, "__version__", "unknown")
            match = re.match(r"(\d+)\.(\d+)", version)
            if not match or tuple(map(int, match.groups())) < (0, 17):
                raise ImportError(f"Requires lief>=0.17; installed: {version}")
            if not hasattr(module, "MachO"):
                raise ImportError("LIEF was built without Mach-O support")
        except (ImportError, OSError) as exc:
            raise ToolError(f"LIEF is unavailable: {exc}. Install it for the active Python interpreter "
                            f"({sys.executable}): python -m pip install --upgrade 'lief>=0.17'") from exc
        log.debug("Python: %s; LIEF: %s", sys.executable, version)


def _check_patch_tools(targets, signing, do_sign):
    with stage("Checking tools"):
        toolchain.ensure_merger()
        names = []
        if any(t.sources for t in targets):
            names.append("xcrun")
        if do_sign:
            names.append("ldid" if signing.use_ldid else "codesign")
        toolchain.require_tools(*names)


def cmd_doctor(args):
    failures = []
    checks = [("Python / LIEF", _check_python_dependencies),
              ("MachOMerger (file and permissions)", toolchain.ensure_merger)]
    for name, check in checks:
        try:
            result = check()
            print(f"OK: {name}" + (f": {result}" if result else ""))
        except Exception as exc:
            failures.append(name)
            print(f"FAIL: {name}: {exc}", file=sys.stderr)
    print("Source builds currently require xcrun/SDK; signing requires codesign or ldid.")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coldhook",
                                description="Static Mach-O merge patcher (ColdHook)")
    p.add_argument("--version", action="version", version=f"coldhook {__version__}")
    p.add_argument("--debug", action="store_true",
                   help="show internal stages, commands, and full traceback")
    p.add_argument("--log-file", metavar="FILE",
                   help="write the complete diagnostic log to a file")
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("doctor", help="check dependencies and merger discovery")
    pd.set_defaults(func=cmd_doctor)

    pi = sub.add_parser("info", help="show Mach-O metadata")
    pi.add_argument("binary")
    pi.set_defaults(func=cmd_info)

    pm = sub.add_parser("merge", help="merge a hook into one binary")
    pm.add_argument("--target", required=True, help="target Mach-O")
    pm.add_argument("--src", action="append", metavar="FILE", help="hook source file (repeatable)")
    pm.add_argument("--dylib", metavar="FILE", help="prebuilt hook dylib (instead of --src)")
    pm.add_argument("--out", help="output path (default: <target>.coldhook)")
    pm.add_argument("--name", help="label for logs")
    pm.add_argument("--ldflags", action="append", metavar="FLAG",
                    help="extra hook linker flag, e.g. -lz (repeatable)")
    pm.add_argument("--allow-new-dylibs", action="store_true",
                    help="allow hook dependencies absent from the target")
    pm.add_argument("--no-sign", action="store_true", help="skip output signing")
    _add_sign_args(pm)
    pm.set_defaults(func=cmd_merge)

    pp = sub.add_parser("patch", help="patch all configured targets (individual binaries)")
    pp.add_argument("--config", "-c", required=True, help="coldhook.toml")
    pp.add_argument("--no-sign", action="store_true", help="skip output signing")
    pp.set_defaults(func=cmd_patch)

    pb = sub.add_parser("ipa", help="patch an .ipa or .app (signing disabled by default)")
    pb.add_argument("input", help="input .ipa or .app directory")
    pb.add_argument("--config", "-c", required=True, help="coldhook.toml")
    pb.add_argument("--out", "-o", required=True, help="output .ipa or .app")
    pb.add_argument("--sign-bundle", action="store_true",
                    help="sign bundle binaries (disabled by default)")
    pb.set_defaults(func=cmd_ipa)

    ps = sub.add_parser("shared", help="apply one shared hook dylib to Mach-O images in an .app/.ipa")
    ps.add_argument("input", help="input .app directory or .ipa file")
    ps.add_argument("--dylib", required=True, help="shared hook dylib")
    ps.add_argument("--runtime", help="libcoldhook.dylib to place in Frameworks (default: next to the hook)")
    ps.add_argument("--import-path", help="hook dylib load path (default: @executable_path/Frameworks/<name>)")
    ps.add_argument("--verbose", action="store_true",
                    help="show hook declarations and per-binary results")
    ps.add_argument("--skip-unsupported", action="store_true",
                    help="skip unsupported auxiliary Mach-O images")
    ps.add_argument("--out", "-o", required=True, help="output .app directory or .ipa file")
    ps.add_argument("--sign-bundle", action="store_true",
                    help="sign each processed Mach-O using ad hoc codesign")
    ps.set_defaults(func=cmd_shared)

    pt = sub.add_parser("install-theos", help="install ColdHook Tweak NIC templates into $THEOS")
    pt.add_argument("--theos", help="Theos path (default: $THEOS or ~/theos)")
    pt.set_defaults(func=_cmd_install_theos)

    return p


def _cmd_install_theos(args) -> int:
    from .theos_install import cmd_install_theos
    return cmd_install_theos(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = []
    log_file_active = False
    try:
        if args.debug:
            debug_console = logging.StreamHandler()
            debug_console.setLevel(logging.DEBUG)
            debug_console.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"))
            handlers.append(debug_console)
        if args.log_file:
            log_file = logging.FileHandler(args.log_file, encoding="utf-8")
            log_file.setLevel(logging.DEBUG)
            log_file.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"))
            handlers.append(log_file)
            log_file_active = True
        for handler in handlers:
            log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        log.propagate = False
        with stage(f"Command {args.cmd}"):
            if args.cmd in {"info", "merge", "patch", "ipa", "shared"}:
                _check_python_dependencies()
            return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted by user (Ctrl+C).", file=sys.stderr)
        return 130
    except Exception as exc:
        cause = exc
        while isinstance(cause, DiagnosticError) and cause.__cause__ is not None:
            cause = cause.__cause__
        message = str(cause).splitlines()[0] if str(cause) else type(cause).__name__
        console.error(message)
        if handlers:
            log.debug("Error details", exc_info=True)
        if log_file_active and not args.debug:
            print(f"Detailed log: {args.log_file}", file=sys.stderr)
        elif not args.debug and not args.log_file:
            print("For details, add --debug or --log-file coldhook.log before the command.", file=sys.stderr)
        return 1
    finally:
        for handler in handlers:
            log.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    sys.exit(main())
