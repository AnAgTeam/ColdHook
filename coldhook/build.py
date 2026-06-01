"""Оркестрация патча одного таргета: introspect -> build hook -> merge -> [sign]."""
from __future__ import annotations

import os
import shutil
import tempfile

from . import macho, toolchain
from .config import Config, Signing, Target

C_CYAN, C_RED, C_GREEN, C_YELL, C_RST = (
    "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m")


INCLUDE_DIR = os.path.join(os.path.dirname(__file__), "include")  # где лежит coldhook.h


def _say(msg: str) -> None:
    print(f"{C_CYAN}== {msg}{C_RST}")


class PatchError(RuntimeError):
    pass


def _build_or_get_hook(target: Target, info: macho.MachOInfo, tmp: str) -> str:
    """Собрать хук из исходников под платформу таргета либо вернуть готовый dylib."""
    if target.sources:
        hook = os.path.join(tmp, "libhook.dylib")
        _say(f"[{target.name}] собираю хук под {info.arch}/{info.platform or 'macos'}")
        # -I с coldhook.h, чтобы исходники могли #include <coldhook.h> (HOOK_ADDR/ORIG)
        toolchain.build_hook(target.sources, hook, info.arch,
                             info.platform or "macos", info.minos,
                             extra=["-I", INCLUDE_DIR])
        return hook
    hook = target.dylib
    _say(f"[{target.name}] готовый хук: {os.path.basename(hook)}")
    if not os.path.exists(hook):
        raise PatchError(f"[{target.name}] хук-dylib не найден: {hook}")
    return hook


def patch_target(target: Target, signing: Signing, binary: str, out: str,
                 do_sign: bool = True) -> str:
    """Пропатчить бинарь `binary`, результат в `out`. Подпись опциональна.

    Если out == binary — патчим in-place (через временный файл, затем замена).
    """
    if not os.path.exists(binary):
        raise PatchError(f"[{target.name}] таргет не найден: {binary}")

    info = macho.inspect(binary)
    _say(f"[{target.name}] {os.path.basename(binary)}: {info.filetype} "
         f"{info.arch} {info.platform or '?'}{info.minos and ' ' + info.minos} "
         f"cryptid={info.cryptid}")

    if info.is_fat:
        raise PatchError(f"[{target.name}] FAT-бинарь ({', '.join(info.archs)}); "
                         f"сначала тонкий слайс: lipo {binary} -thin {info.arch} -output ...")
    if info.encrypted:
        raise PatchError(f"[{target.name}] бинарь зашифрован (cryptid={info.cryptid}); "
                         f"нужен расшифрованный дамп")

    in_place = os.path.realpath(out) == os.path.realpath(binary)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="coldhook_")
    try:
        hook = _build_or_get_hook(target, info, tmp)

        merged = os.path.join(tmp, "merged") if in_place else out
        _say(f"[{target.name}] merge -> {os.path.basename(out)}"
             f"{' (in-place)' if in_place else ''}")
        toolchain.merge(binary, hook, merged)

        if do_sign:
            how = "ldid" if signing.use_ldid else f"codesign '{signing.identity}'"
            _say(f"[{target.name}] подпись ({how})")
            toolchain.sign(merged, identity=signing.identity,
                           entitlements=signing.entitlements, use_ldid=signing.use_ldid)
        else:
            _say(f"[{target.name}] {C_YELL}подпись пропущена{C_CYAN}")

        if in_place:
            shutil.copymode(binary, merged)
            shutil.move(merged, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{C_GREEN}OK [{target.name}] -> {out}{C_RST}")
    return out


def patch_all(config: Config, do_sign: bool = True) -> list[str]:
    """patch-режим: таргеты — реальные файлы относительно конфига."""
    toolchain.ensure_merger()
    results = []
    for t in config.targets:
        binary = config.resolve(t.binary)
        out = t.out or (binary + ".coldhook")
        results.append(patch_target(t, config.signing, binary, out, do_sign=do_sign))
    return results
