"""CLI ColdHook: info / merge (одиночный) / patch (по конфигу)."""
from __future__ import annotations

import argparse
import sys

from . import __version__, config, ipa, macho
from .build import C_RED, C_RST, PatchError, patch_all, patch_target
from .config import Signing, Target
from .toolchain import ToolError


def _add_sign_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sign", default="-", metavar="ID",
                   help="codesign identity ('-' = adhoc, по умолчанию) или имя серта")
    p.add_argument("--ldid", action="store_true", help="подписывать через ldid вместо codesign")
    p.add_argument("--ent", metavar="FILE", help="entitlements для подписи")


def cmd_info(args) -> int:
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
                    sources=args.src or [], dylib=args.dylib, out=args.out)
    signing = Signing(identity=args.sign, entitlements=args.ent, use_ldid=args.ldid)
    out = args.out or (args.target + ".coldhook")
    patch_target(target, signing, args.target, out, do_sign=not args.no_sign)
    return 0


def cmd_patch(args) -> int:
    cfg = config.load(args.config)
    print(f"конфиг: {args.config}  ({len(cfg.targets)} таргет(ов))")
    patch_all(cfg, do_sign=not args.no_sign)
    return 0


def cmd_ipa(args) -> int:
    cfg = config.load(args.config)
    print(f"конфиг: {args.config}  ({len(cfg.targets)} таргет(ов))")
    # для бандла подпись по умолчанию ВЫКЛ; включается явным --sign-bundle
    ipa.patch_bundle(args.input, cfg, args.out, do_sign=args.sign_bundle)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coldhook",
                                description="Статический merge-патчер Mach-O (ColdHook)")
    p.add_argument("--version", action="version", version=f"coldhook {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("info", help="показать метаданные Mach-O")
    pi.add_argument("binary")
    pi.set_defaults(func=cmd_info)

    pm = sub.add_parser("merge", help="смерджить хук в один бинарь")
    pm.add_argument("--target", required=True, help="целевой Mach-O")
    pm.add_argument("--src", action="append", metavar="FILE", help="исходник хука (повторяемо)")
    pm.add_argument("--dylib", metavar="FILE", help="готовый хук-dylib (вместо --src)")
    pm.add_argument("--out", help="путь результата (по умолч. <target>.coldhook)")
    pm.add_argument("--name", help="метка для логов")
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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (PatchError, ToolError, ValueError, FileNotFoundError) as e:
        print(f"{C_RED}ОШИБКА: {e}{C_RST}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
