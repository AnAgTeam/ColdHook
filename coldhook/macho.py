"""Интроспекция Mach-O: арки, платформа, minos, cryptid, filetype.

Используем системные otool/lipo (надёжно и без зависимостей). Полноценный парсер
не нужен — оркестратору достаточно метаданных для выбора флагов сборки хука и проверок.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

try:
    import lief
except ImportError:  # pragma: no cover - only for legacy installations
    lief = None


@dataclass
class MachOInfo:
    path: str
    archs: list[str] = field(default_factory=list)  # все слайсы (fat -> несколько)
    is_fat: bool = False
    arch: str = ""        # выбранный слайс (arm64e в приоритете, иначе arm64)
    filetype: str = ""    # MH_DYLIB / MH_EXECUTE / ...
    platform: str = ""    # macos / ios / ios-simulator / ...
    minos: str = ""       # напр. "14.0"
    cryptid: int = 0      # 0 = расшифрован

    @property
    def encrypted(self) -> bool:
        return self.cryptid != 0


# Арки, которые умеет наш форк MachOMerger (arm64 формат 2/6, arm64e формат 1/12).
MERGER_ARCHS = {"arm64", "arm64e"}

_FILETYPES = {"2": "MH_EXECUTE", "6": "MH_DYLIB", "7": "MH_DYLINKER",
              "8": "MH_BUNDLE", "0xa": "MH_DSYM"}
# Числовые platform из LC_BUILD_VERSION (otool иногда печатает число, иногда имя).
_PLATFORMS = {"1": "macos", "2": "ios", "3": "tvos", "4": "watchos",
              "6": "ios-mac", "7": "ios-simulator", "8": "tvos-simulator",
              "9": "watchos-simulator"}


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def is_macho(path: str) -> bool:
    if lief is not None:
        try:
            return lief.MachO.parse(path) is not None
        except Exception:
            return False
    out = subprocess.run(["lipo", "-archs", path], capture_output=True, text=True)
    return out.returncode == 0


def _pick_arch(archs: list[str]) -> str:
    for pref in ("arm64e", "arm64"):
        if pref in archs:
            return pref
    return archs[0] if archs else ""


def inspect(path: str) -> MachOInfo:
    """Собрать метаданные Mach-O. Бросает ValueError, если это не Mach-O."""
    archs_out = subprocess.run(["lipo", "-archs", path], capture_output=True, text=True)
    if archs_out.returncode != 0:
        raise ValueError(f"не Mach-O или не читается: {path}")
    archs = archs_out.stdout.split()
    info = MachOInfo(path=path, archs=archs, is_fat=len(archs) > 1, arch=_pick_arch(archs))

    # Заголовок (filetype) выбранного слайса; -v печатает имена (MH_MAGIC_64 ARM64 ALL 0x00 DYLIB ...).
    hdr = _run(["otool", "-arch", info.arch, "-h", "-v", path])
    m = re.search(r"MH_MAGIC_64\s+\S+\s+\S+\s+\S+\s+(\S+)", hdr)
    if m:
        ft = m.group(1)
        info.filetype = _FILETYPES.get(ft, "MH_" + ft if not ft.startswith("MH_") else ft)

    lc = _run(["otool", "-arch", info.arch, "-l", path])

    pm = re.search(r"\bplatform\s+(\S+)", lc)
    if pm:
        val = pm.group(1)
        info.platform = _PLATFORMS.get(val, val.lower())
    mm = re.search(r"\bminos\s+(\S+)", lc)
    if mm:
        info.minos = mm.group(1)

    cm = re.search(r"\bcryptid\s+(\d+)", lc)
    if cm:
        info.cryptid = int(cm.group(1))

    return info


def _lipo(args: list[str], what: str) -> None:
    p = subprocess.run(["lipo", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise ValueError(f"lipo {what} упало: {p.stderr.strip() or p.stdout.strip()}")


def thin(path: str, arch: str, out: str) -> None:
    """Вырезать один arch-слайс FAT-бинаря в тонкий файл out."""
    _lipo([path, "-thin", arch, "-output", out], f"-thin {arch}")


def replace_slices(orig: str, replacements: dict[str, str], out: str) -> None:
    """Собрать FAT: взять orig и заменить указанные arch-слайсы новыми файлами."""
    args = [orig]
    for arch, p in replacements.items():
        args += ["-replace", arch, p]
    args += ["-output", out]
    _lipo(args, "-replace")
