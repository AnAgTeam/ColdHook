"""CLI ColdHook: info / merge (одиночный) / patch (по конфигу)."""
from __future__ import annotations

import argparse
import sys
import logging
import importlib
import re

from .diagnostics import log, stage
from . import toolchain

from . import __version__, config, macho
from .build import C_RED, C_RST, PatchError, patch_all, patch_target
from .config import Signing, Target
from .toolchain import ToolError


def _add_sign_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sign", default="-", metavar="ID",
                   help="codesign identity ('-' = adhoc, по умолчанию) или имя серта")
    p.add_argument("--ldid", action="store_true", help="подписывать через ldid вместо codesign")
    p.add_argument("--ent", metavar="FILE", help="entitlements для подписи")


def cmd_info(args) -> int:
    toolchain.require_tools("lipo", "otool")
    info = macho.inspect(args.binary)
    print(f"path:     {info.path}")
    print(f"archs:    {', '.join(info.archs)}{'  (FAT)' if info.is_fat else ''}")
    print(f"slice:    {info.arch}")
    print(f"filetype: {info.filetype}")
    print(f"platform: {info.platform} {info.minos}")
    print(f"cryptid:  {info.cryptid}{'  (ЗАШИФРОВАН)' if info.encrypted else ''}")
    return 0


def cmd_merge(args) -> int:
    if args.dylib and args.src:
        print("укажи либо --src, либо --dylib, не оба", file=sys.stderr)
        return 2
    if not args.dylib and not args.src:
        print("нужен хук: --src <файл> (повторяемо) или --dylib <готовый>", file=sys.stderr)
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
    print(f"конфиг: {args.config}  ({len(cfg.targets)} таргет(ов))")
    _check_patch_tools(cfg.targets, cfg.signing, not args.no_sign)
    patch_all(cfg, do_sign=not args.no_sign)
    return 0


def cmd_ipa(args) -> int:
    from . import ipa
    cfg = config.load(args.config)
    print(f"конфиг: {args.config}  ({len(cfg.targets)} таргет(ов))")
    # для бандла подпись по умолчанию ВЫКЛ; включается явным --sign-bundle
    _check_patch_tools(cfg.targets, cfg.signing, args.sign_bundle)
    ipa.patch_bundle(args.input, cfg, args.out, do_sign=args.sign_bundle)
    return 0


def cmd_shared(args) -> int:
    from . import ipa
    toolchain.ensure_merger()
    toolchain.require_tools("lipo", "otool", *(["codesign"] if args.sign_bundle else []))
    return 0 if ipa.patch_shared_bundle(args.input, args.dylib, args.out,
                                        do_sign=args.sign_bundle,
                                        import_path=args.import_path,
                                        runtime=args.runtime,
                                        verbose=args.verbose,
                                        skip_unsupported=args.skip_unsupported) else 1


def _check_python_dependencies():
    with stage("Проверка Python-зависимостей"):
        try:
            module = importlib.import_module("lief")
            version = getattr(module, "__version__", "unknown")
            match = re.match(r"(\d+)\.(\d+)", version)
            if not match or tuple(map(int, match.groups())) < (0, 17):
                raise ImportError(f"нужен lief>=0.17, установлен {version}")
            if not hasattr(module, "MachO"):
                raise ImportError("LIEF собран без поддержки Mach-O")
        except (ImportError, OSError) as exc:
            raise ToolError(f"LIEF недоступен: {exc}. Установи в используемый Python "
                            f"({sys.executable}): python -m pip install --upgrade 'lief>=0.17'") from exc
        log.info("Python: %s; LIEF: %s", sys.executable, version)


def _check_patch_tools(targets, signing, do_sign):
    with stage("Проверка инструментов"):
        toolchain.ensure_merger()
        names = ["lipo", "otool"]
        if any(t.sources for t in targets):
            names.append("xcrun")
        if do_sign:
            names.append("ldid" if signing.use_ldid else "codesign")
        toolchain.require_tools(*names)


def cmd_doctor(args):
    failures = []
    checks = [("Python / LIEF", _check_python_dependencies),
              ("MachOMerger (файл и права)", toolchain.ensure_merger),
              ("Mach-O инструменты", lambda: toolchain.require_tools("lipo", "otool"))]
    for name, check in checks:
        try:
            result = check()
            print(f"OK: {name}" + (f": {result}" if result else ""))
        except Exception as exc:
            failures.append(name)
            print(f"FAIL: {name}: {exc}", file=sys.stderr)
    print("Для сборки исходников дополнительно нужен xcrun/SDK; для подписи — codesign или ldid.")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coldhook",
                                description="Статический merge-патчер Mach-O (ColdHook)")
    p.add_argument("--version", action="version", version=f"coldhook {__version__}")
    p.add_argument("--debug", action="store_true", help="команды и полный traceback")
    p.add_argument("--log-file", metavar="FILE", help="записать подробный журнал в файл")
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("doctor", help="проверить зависимости и поиск мерджера")
    pd.set_defaults(func=cmd_doctor)

    pi = sub.add_parser("info", help="показать метаданные Mach-O")
    pi.add_argument("binary")
    pi.set_defaults(func=cmd_info)

    pm = sub.add_parser("merge", help="смерджить хук в один бинарь")
    pm.add_argument("--target", required=True, help="целевой Mach-O")
    pm.add_argument("--src", action="append", metavar="FILE", help="исходник хука (повторяемо)")
    pm.add_argument("--dylib", metavar="FILE", help="готовый хук-dylib (вместо --src)")
    pm.add_argument("--out", help="путь результата (по умолч. <target>.coldhook)")
    pm.add_argument("--name", help="метка для логов")
    pm.add_argument("--ldflags", action="append", metavar="FLAG",
                    help="доп. флаг линковки хука, напр. -lz (повторяемо)")
    pm.add_argument("--allow-new-dylibs", action="store_true",
                    help="разрешить хуку тянуть dylib, которых нет в таргете")
    pm.add_argument("--no-sign", action="store_true", help="не подписывать результат")
    _add_sign_args(pm)
    pm.set_defaults(func=cmd_merge)

    pp = sub.add_parser("patch", help="пропатчить все таргеты из конфига (отдельные бинари)")
    pp.add_argument("--config", "-c", required=True, help="coldhook.toml")
    pp.add_argument("--no-sign", action="store_true", help="не подписывать результаты")
    pp.set_defaults(func=cmd_patch)

    pb = sub.add_parser("ipa", help="пропатчить .ipa или .app (merge in-place, БЕЗ подписи)")
    pb.add_argument("input", help="входной .ipa или .app-каталог")
    pb.add_argument("--config", "-c", required=True, help="coldhook.toml")
    pb.add_argument("--out", "-o", required=True, help="выходной .ipa или .app")
    pb.add_argument("--sign-bundle", action="store_true",
                    help="подписать бинари в бандле (по умолчанию НЕТ — твоя забота)")
    pb.set_defaults(func=cmd_ipa)

    ps = sub.add_parser("shared", help="применить один shared hook-dylib ко всем Mach-O в .app/.ipa")
    ps.add_argument("input", help="входной .app-каталог или .ipa-файл")
    ps.add_argument("--dylib", required=True, help="общий hook-dylib")
    ps.add_argument("--runtime", help="libcoldhook.dylib для помещения в Frameworks (по умолчанию рядом с hook)")
    ps.add_argument("--import-path", help="путь загрузки hook dylib (по умолчанию @executable_path/Frameworks/<name>)")
    ps.add_argument("--verbose", action="store_true", help="печатать обработанные бинарники")
    ps.add_argument("--skip-unsupported", action="store_true",
                    help="пропускать неподдерживаемые служебные Mach-O (например FAT XCTest)")
    ps.add_argument("--out", "-o", required=True, help="выходной .app-каталог")
    ps.add_argument("--sign-bundle", action="store_true",
                    help="подписать каждый обработанный Mach-O через ad-hoc codesign")
    ps.set_defaults(func=cmd_shared)

    pt = sub.add_parser("install-theos", help="поставить NIC-шаблон «ColdHook Tweak» в $THEOS")
    pt.add_argument("--theos", help="путь к theos (по умолчанию $THEOS или ~/theos)")
    pt.set_defaults(func=_cmd_install_theos)

    return p


def _cmd_install_theos(args) -> int:
    from .theos_install import cmd_install_theos
    return cmd_install_theos(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = []
    try:
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG if args.debug else logging.INFO)
        handlers.append(console)
        if args.log_file:
            handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
        for handler in handlers:
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        log.propagate = False
        with stage(f"Команда {args.cmd}"):
            if args.cmd in {"info", "merge", "patch", "ipa", "shared"}:
                _check_python_dependencies()
            return args.func(args)
    except KeyboardInterrupt:
        print("Остановлено пользователем (Ctrl+C).", file=sys.stderr)
        return 130
    except Exception as exc:
        if handlers and log.handlers:
            log.error("%s", exc)
            log.debug("Подробности ошибки", exc_info=True)
        else:
            print(f"Не удалось открыть журнал: {exc}", file=sys.stderr)
        if not args.debug:
            print("Подробности: добавь --debug или --log-file coldhook.log перед командой.", file=sys.stderr)
        return 1
    finally:
        for handler in handlers:
            log.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    sys.exit(main())
