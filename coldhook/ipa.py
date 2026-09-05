"""Патч бандла: .ipa (iOS) или .app-каталога (macOS) — merge хука в бинари in-place.

Структура патча одинакова для обеих платформ: распаковать -> найти .app -> по каждому
таргету (путь относительно .app) merge in-place -> запаковать. Подпись по умолчанию НЕ
делается (это забота пользователя; iOS-установка потребует её отдельно).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile

from . import build
from .build import C_CYAN, C_GREEN, C_RST, PatchError
from .config import Config


def _run(cmd: list[str], what: str, cwd: str | None = None) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if p.returncode != 0:
        raise PatchError(f"{what} упало: {p.stderr.strip() or p.stdout.strip()}")


def _find_app(root: str) -> str:
    """Найти .app: для IPA — Payload/*.app; если root сам .app — он и есть."""
    if root.endswith(".app") and os.path.isdir(root):
        return root
    cands = glob.glob(os.path.join(root, "Payload", "*.app"))
    if not cands:
        cands = glob.glob(os.path.join(root, "*.app"))
    if not cands:
        raise PatchError(f"не найден .app внутри {root}")
    return cands[0]


def patch_bundle(inp: str, config: Config, out: str, do_sign: bool = False) -> str:
    build.toolchain.ensure_merger()
    is_ipa = inp.lower().endswith(".ipa") or os.path.isfile(inp)
    work = tempfile.mkdtemp(prefix="coldhook_bundle_")
    try:
        if is_ipa:
            print(f"{C_CYAN}== распаковка IPA: {os.path.basename(inp)}{C_RST}")
            _run(["unzip", "-q", "-o", inp, "-d", work], "unzip")
            stage = work
        else:
            # .app-каталог: работаем на копии, чтобы не трогать оригинал
            print(f"{C_CYAN}== копия .app: {os.path.basename(inp)}{C_RST}")
            dst = os.path.join(work, os.path.basename(inp))
            shutil.copytree(inp, dst, symlinks=True)
            stage = dst

        app = _find_app(stage)
        print(f"{C_CYAN}== .app: {os.path.relpath(app, work)}{C_RST}")

        for t in config.targets:
            binary = os.path.join(app, t.binary)
            # merge in-place внутри бандла; подпись по флагу (по умолч. off)
            build.patch_target(t, config.signing, binary, binary, do_sign=do_sign)

        # запаковка
        if is_ipa:
            print(f"{C_CYAN}== запаковка -> {os.path.basename(out)}{C_RST}")
            out_abs = os.path.abspath(out)
            if os.path.exists(out_abs):
                os.remove(out_abs)
            # zip из каталога staging, сохраняя Payload/ и права/симлинки
            _run(["zip", "-qry", out_abs, "Payload"], "zip", cwd=stage)
        else:
            print(f"{C_CYAN}== вывод .app -> {out}{C_RST}")
            if os.path.exists(out):
                shutil.rmtree(out)
            shutil.copytree(app, out, symlinks=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"{C_GREEN}OK бандл пропатчен -> {out}{C_RST}")
    return out


def patch_shared_bundle(inp: str, dylib: str, out: str, do_sign: bool = False,
                        import_path: str | None = None, verbose: bool = False) -> str:
    """Apply one shared hook dylib to every Mach-O in an app bundle.

    File discovery is deliberately dumb: every regular file is probed, and the
    merger decides whether the current image has applicable declarations.
    """
    build.toolchain.ensure_merger()
    if not os.path.exists(dylib):
        raise PatchError(f"shared hook-dylib не найден: {dylib}")
    work = tempfile.mkdtemp(prefix="coldhook_shared_bundle_")
    is_ipa = inp.lower().endswith(".ipa") or os.path.isfile(inp)
    try:
        if is_ipa:
            print(f"{C_CYAN}== распаковка IPA: {os.path.basename(inp)}{C_RST}")
            _run(["unzip", "-q", "-o", inp, "-d", work], "unzip")
            stage = work
        else:
            if not inp.endswith(".app") or not os.path.isdir(inp):
                raise PatchError("shared: ожидается каталог .app или файл .ipa")
            stage = os.path.join(work, os.path.basename(inp))
            shutil.copytree(inp, stage, symlinks=True)
        app = _find_app(stage)
        # Shared sideload bundles carry the hook runtime with the app.  The
        # merger rewrites LC_LOAD_DYLIB to @executable_path/Frameworks/<name>.
        bundled_dylib = None
        if import_path is None:
            frameworks = os.path.join(app, "Frameworks")
            os.makedirs(frameworks, exist_ok=True)
            bundled_dylib = os.path.join(frameworks, os.path.basename(dylib))
            shutil.copy2(dylib, bundled_dylib)
        dylib_real = os.path.realpath(dylib)
        patched = 0
        for root, _, files in os.walk(stage):
            for name in files:
                target = os.path.join(root, name)
                if os.path.realpath(target) == dylib_real or (bundled_dylib and os.path.realpath(target) == os.path.realpath(bundled_dylib)):
                    continue
                try:
                    build.macho.inspect(target)
                except Exception:
                    continue
                merged = target + ".coldhook"
                try:
                    build.toolchain.merge(target, dylib, merged, mode="shared", import_path=import_path)
                except Exception:
                    if os.path.exists(merged):
                        os.remove(merged)
                    raise
                shutil.copymode(target, merged)
                shutil.move(merged, target)
                if do_sign:
                    build.toolchain.sign(target)
                patched += 1
                if verbose:
                    print(f"will add {os.path.relpath(target, app)}")
        if is_ipa:
            print(f"{C_CYAN}== запаковка IPA: {os.path.basename(out)}{C_RST}")
            out_abs = os.path.abspath(out)
            if os.path.exists(out_abs):
                os.remove(out_abs)
            _run(["zip", "-qry", out_abs, "Payload"], "zip", cwd=stage)
        else:
            if os.path.exists(out):
                shutil.rmtree(out)
            shutil.copytree(stage, out, symlinks=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{C_GREEN}OK shared bundle: обработано Mach-O: {patched}{C_RST}")
    return out
