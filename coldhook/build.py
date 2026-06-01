"""Оркестрация патча одного таргета: introspect -> build hook -> merge -> sign."""
from __future__ import annotations

import os
import shutil
import tempfile

from . import macho, toolchain
from .config import Config, Signing, Target

C_CYAN, C_RED, C_GREEN, C_YELL, C_RST = (
    "\033[1;36m", "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[0m")


def _say(msg: str) -> None:
    print(f"{C_CYAN}== {msg}{C_RST}")


class PatchError(RuntimeError):
    pass


def patch_target(target: Target, signing: Signing) -> str:
    """Пропатчить один таргет, вернуть путь результата."""
    binary = target.binary
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
                         f"нужен расшифрованный (decrypted) дамп")

    out = target.resolved_out()
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="coldhook_")
    try:
        # 1. хук-dylib: либо собираем из исходников под платформу таргета, либо готовый
        if target.sources:
            hook = os.path.join(tmp, "libhook.dylib")
            _say(f"[{target.name}] собираю хук под {info.arch}/{info.platform or 'macos'}")
            toolchain.build_hook(target.sources, hook, info.arch,
                                 info.platform or "macos", info.minos)
        else:
            hook = target.dylib
            _say(f"[{target.name}] готовый хук: {os.path.basename(hook)}")
            if not os.path.exists(hook):
                raise PatchError(f"[{target.name}] хук-dylib не найден: {hook}")

        # 2. merge хука в таргет
        _say(f"[{target.name}] merge -> {os.path.basename(out)}")
        toolchain.merge(binary, hook, out)

        # 3. resign результата (merge инвалидирует подпись)
        how = "ldid" if signing.use_ldid else f"codesign '{signing.identity}'"
        _say(f"[{target.name}] подпись ({how})")
        toolchain.sign(out, identity=signing.identity,
                       entitlements=signing.entitlements, use_ldid=signing.use_ldid)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{C_GREEN}OK [{target.name}] -> {out}{C_RST}")
    return out


def patch_all(config: Config) -> list[str]:
    toolchain.ensure_merger()
    results = []
    for t in config.targets:
        results.append(patch_target(t, config.signing))
    return results
