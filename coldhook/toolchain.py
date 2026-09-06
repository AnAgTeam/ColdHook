"""Обёртки над тулчейном: MachOMerger (форк), clang, codesign/ldid."""
from __future__ import annotations

import os
import subprocess

# Корень репозитория = на два уровня выше этого файла (coldhook/ -> repo).
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_merger_name = "MachOMerger.exe" if os.name == "nt" else "MachOMerger"
MERGER = os.path.join(ROOT, "vendor", "MachOMerger", ".build", "release", _merger_name)

# Флаги, обязательные для сливаемых бинарей (см. харнесс/память):
#  -fixup_chains       — мёрджер умеет только LC_DYLD_CHAINED_FIXUPS;
#  -add_split_seg_info — релокация данных через LC_SEGMENT_SPLIT_INFO.
MERGE_LDFLAGS = ["-Wl,-fixup_chains", "-Xlinker", "-add_split_seg_info"]


class ToolError(RuntimeError):
    pass


def _run(cmd: list[str], what: str) -> None:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise ToolError(f"{what}: не удалось запустить {' '.join(cmd)}: {exc}. "
                        "Проверь COLDHOOK_MERGER и DLL Swift runtime рядом с MachOMerger.exe") from exc
    if p.returncode != 0:
        raise ToolError(f"{what} упало (код {p.returncode}):\n"
                        f"  cmd: {' '.join(cmd)}\n"
                        f"  stderr: {p.stderr.strip()}\n  stdout: {p.stdout.strip()}")


def ensure_merger() -> str:
    # A release can ship MachOMerger(.exe) next to the Python package.
    configured = os.environ.get("COLDHOOK_MERGER")
    candidates = ([os.path.abspath(configured)] if configured else []) + [MERGER,
                  os.path.join(ROOT, "bin", _merger_name),
                  os.path.join(os.path.dirname(__file__), _merger_name)]
    for candidate in candidates:
        if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate
    if not os.path.isfile(MERGER):
        raise ToolError(
            f"MachOMerger не собран: {MERGER}\n"
            f"  собери: (cd vendor/MachOMerger && swift build -c release)")
    return MERGER


def _sdk_path(sdk: str) -> str:
    p = subprocess.run(["xcrun", "--sdk", sdk, "--show-sdk-path"],
                       capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise ToolError(f"не найден SDK '{sdk}' (xcrun --sdk {sdk}): {p.stderr.strip()}")
    return p.stdout.strip()


def hook_clang_cmd(sources: list[str], out: str, arch: str,
                   platform: str, minos: str, extra: list[str] | None = None) -> list[str]:
    """Команда сборки хук-dylib под арку/платформу таргета.

    Платформа важна: хук должен линковать те же пути dylib, что и таргет, иначе
    ремап dylib-ordinals при merge внешних импортов B не найдёт совпадения.
    `extra` — доп. флаги (напр. -I с каталогом coldhook.h), вставляются до исходников.
    """
    arch = arch or "arm64"
    platform = platform or "macos"
    minos = minos or ("11.0" if platform == "macos" else "14.0")
    cmd = ["xcrun", "clang", "-arch", arch, "-dynamiclib", *MERGE_LDFLAGS,
           "-install_name", "@rpath/" + os.path.basename(out), "-o", out]

    if platform == "ios":
        cmd += ["-target", f"{arch}-apple-ios{minos}", "-isysroot", _sdk_path("iphoneos")]
    elif platform == "ios-simulator":
        cmd += ["-target", f"{arch}-apple-ios{minos}-simulator",
                "-isysroot", _sdk_path("iphonesimulator")]
    elif platform == "macos":
        cmd += ["-target", f"{arch}-apple-macos{minos}"]
    else:
        # tvos/watchos и пр. — пробуем через -target без явного sysroot
        cmd += ["-target", f"{arch}-apple-{platform}{minos}"]

    if extra:
        cmd += list(extra)
    cmd += list(sources)
    return cmd


def build_hook(sources: list[str], out: str, arch: str, platform: str, minos: str,
               extra: list[str] | None = None) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    _run(hook_clang_cmd(sources, out, arch, platform, minos, extra=extra), "сборка хука")


def merge(target: str, hook: str, out: str, allow_new_dylibs: bool = False,
          mode: str | None = None, import_path: str | None = None) -> None:
    cmd = [ensure_merger(), target, hook, out]
    if allow_new_dylibs:
        cmd.append("--allow-new-dylibs")
    if mode:
        cmd += ["--mode", mode]
    if import_path:
        cmd += ["--import-path", import_path]
    _run(cmd, "merge")


def sign(path: str, identity: str = "-", entitlements: str | None = None,
         use_ldid: bool = False) -> None:
    if use_ldid:
        cmd = ["ldid", "-S" + (entitlements or ""), path]
        _run(cmd, "ldid")
        return
    cmd = ["codesign", "-f", "-s", identity]
    if entitlements:
        cmd += ["--entitlements", entitlements]
    cmd += [path]
    _run(cmd, "codesign")
