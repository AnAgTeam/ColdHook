"""Обёртки над тулчейном: MachOMerger (форк), clang, codesign/ldid."""
from __future__ import annotations

import os
import subprocess
import shutil
import shlex

from .diagnostics import log, traced

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


def _run(cmd: list[str], what: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    rendered = shlex.join(cmd)
    log.info("Этап: %s", what)
    log.debug("cmd: %s; cwd: %s", rendered, cwd or os.getcwd())
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=cwd)
    except OSError as exc:
        hint = ("Проверь путь, права исполнения и совместимость бинарника с ОС/архитектурой."
                if not isinstance(exc, FileNotFoundError) else
                "Проверь наличие инструмента в PATH и его runtime/загрузчика.")
        raise ToolError(f"{what}: не удалось запустить {rendered}: {exc}. {hint}") from exc
    if p.returncode != 0:
        raise ToolError(f"{what}: код завершения {p.returncode}\n"
                        f"  cmd: {rendered}\n  cwd: {cwd or os.getcwd()}\n"
                        f"  stderr: {p.stderr.strip() or '(пусто)'}\n"
                        f"  stdout: {p.stdout.strip() or '(пусто)'}")
    if p.stderr.strip():
        log.warning("%s: %s", what, p.stderr.strip())
    log.debug("%s stdout: %s", what, p.stdout.strip())
    return p


def ensure_merger() -> str:
    configured = os.environ.get("COLDHOOK_MERGER")
    if configured:
        candidates = [os.path.abspath(os.path.expanduser(configured))]
    else:
        candidates = [os.path.join(os.getcwd(), _merger_name)]
        on_path = shutil.which(_merger_name)
        if on_path:
            candidates.append(on_path)
        candidates += [os.path.join(ROOT, "bin", _merger_name),
                       os.path.join(os.path.dirname(__file__), _merger_name), MERGER]
    for candidate in dict.fromkeys(candidates):
        if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
            log.info("MachOMerger: %s", candidate)
            return candidate
    raise ToolError("MachOMerger не найден или не исполняемый. Проверены: "
                    + ", ".join(candidates)
                    + ". Укажи COLDHOOK_MERGER=/полный/путь/к/" + _merger_name
                    + ", положи бинарник в текущий каталог или PATH; на Unix проверь chmod +x."
                    + (" Явный COLDHOOK_MERGER запрещает подстановку другого бинарника." if configured else ""))


def require_tools(*names: str) -> None:
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        raise ToolError("Не найдены инструменты в PATH: " + ", ".join(missing)
                        + ". Для lipo/otool/xcrun/codesign установи Xcode Command Line Tools "
                        "на macOS и проверь xcode-select; ldid устанавливается отдельно.")


def _sdk_path(sdk: str) -> str:
    p = _run(["xcrun", "--sdk", sdk, "--show-sdk-path"], f"поиск SDK {sdk}")
    if not p.stdout.strip():
        raise ToolError(f"xcrun вернул пустой путь SDK '{sdk}'; проверь установку Xcode")
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
