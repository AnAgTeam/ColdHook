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


def _build_or_get_hook(target: Target, info: macho.MachOInfo, workdir: str) -> str:
    """Собрать хук из исходников под арку/платформу слайса либо вернуть готовый dylib."""
    if target.sources:
        os.makedirs(workdir, exist_ok=True)
        hook = os.path.join(workdir, "libhook.dylib")
        _say(f"[{target.name}] собираю хук под {info.arch}/{info.platform or 'macos'}")
        # -I с coldhook.h (HOOK_ADDR/ORIG) + пользовательские ldflags (напр. -lz)
        toolchain.build_hook(target.sources, hook, info.arch,
                             info.platform or "macos", info.minos,
                             extra=["-I", INCLUDE_DIR, *target.ldflags])
        return hook
    hook = target.dylib
    _say(f"[{target.name}] готовый хук: {os.path.basename(hook)}")
    if not os.path.exists(hook):
        raise PatchError(f"[{target.name}] хук-dylib не найден: {hook}")
    return hook


def _merge_thin(target: Target, info_thin: macho.MachOInfo, binary_thin: str,
                out_thin: str, workdir: str) -> None:
    """Смёрджить хук в один тонкий (single-arch) бинарь."""
    if info_thin.encrypted:
        raise PatchError(f"[{target.name}] слайс {info_thin.arch} зашифрован "
                         f"(cryptid={info_thin.cryptid}); нужен расшифрованный дамп")
    hook = _build_or_get_hook(target, info_thin, workdir)
    toolchain.merge(binary_thin, hook, out_thin, allow_new_dylibs=target.allow_new_dylibs)


def _patch_fat(target: Target, info: macho.MachOInfo, binary: str,
               out_fat: str, tmp: str) -> None:
    """FAT: смёрджить поддерживаемые слайсы под свою арку, остальные оставить, собрать lipo."""
    patchable = [a for a in info.archs if a in macho.MERGER_ARCHS]
    kept = [a for a in info.archs if a not in macho.MERGER_ARCHS]
    if not patchable:
        raise PatchError(f"[{target.name}] FAT {info.archs}: нет слайса, который умеет "
                         f"мёрджер (поддержаны {sorted(macho.MERGER_ARCHS)})")
    _say(f"[{target.name}] FAT: патчу [{', '.join(patchable)}]"
         + (f", оставляю [{', '.join(kept)}]" if kept else ""))

    replacements: dict[str, str] = {}
    for a in patchable:
        thin = os.path.join(tmp, f"slice_{a}")
        macho.thin(binary, a, thin)
        info_a = macho.inspect(thin)
        patched = os.path.join(tmp, f"patched_{a}")
        _merge_thin(target, info_a, thin, patched, os.path.join(tmp, f"hook_{a}"))
        replacements[a] = patched

    macho.replace_slices(binary, replacements, out_fat)


def patch_target(target: Target, signing: Signing, binary: str, out: str,
                 do_sign: bool = True) -> str:
    """Пропатчить бинарь `binary`, результат в `out`. Подпись опциональна.

    Если out == binary — патчим in-place (через временный файл, затем замена).
    """
    if not os.path.exists(binary):
        raise PatchError(f"[{target.name}] таргет не найден: {binary}")

    info = macho.inspect(binary)
    archs_disp = ", ".join(info.archs) if info.is_fat else info.arch
    _say(f"[{target.name}] {os.path.basename(binary)}: {info.filetype} "
         f"[{archs_disp}] {info.platform or '?'}{info.minos and ' ' + info.minos}"
         f"{'' if info.is_fat else f' cryptid={info.cryptid}'}")

    in_place = os.path.realpath(out) == os.path.realpath(binary)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="coldhook_")
    try:
        merged = os.path.join(tmp, "merged") if in_place else out
        _say(f"[{target.name}] merge -> {os.path.basename(out)}"
             f"{' (in-place)' if in_place else ''}")
        if info.is_fat:
            _patch_fat(target, info, binary, merged, tmp)
        else:
            _merge_thin(target, info, binary, merged, os.path.join(tmp, "hook"))

        if do_sign:
            how = "ldid" if signing.use_ldid else f"codesign '{signing.identity}'"
            _say(f"[{target.name}] подпись ({how})")
            toolchain.sign(merged, identity=signing.identity,
                           entitlements=signing.entitlements, use_ldid=signing.use_ldid)
        else:
            _say(f"[{target.name}] {C_YELL}подпись пропущена{C_CYAN}")

        # Переносим режим оригинала на результат (исполняемый должен сохранить +x).
        shutil.copymode(binary, merged)
        if in_place:
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
