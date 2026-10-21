"""Portable Mach-O metadata and lossless universal-binary slice handling."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
from dataclasses import dataclass, field

from .diagnostics import traced


@dataclass
class MachOInfo:
    path: str
    archs: list[str] = field(default_factory=list)
    is_fat: bool = False
    arch: str = ""
    filetype: str = ""
    platform: str = ""
    minos: str = ""
    cryptid: int = 0

    @property
    def encrypted(self) -> bool:
        return self.cryptid != 0


MERGER_ARCHS = {"arm64", "arm64e"}
_THIN = {b"\xce\xfa\xed\xfe": ("<", 28), b"\xcf\xfa\xed\xfe": ("<", 32),
         b"\xfe\xed\xfa\xce": (">", 28), b"\xfe\xed\xfa\xcf": (">", 32)}
_FAT = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
        b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
_PLATFORMS = {1: "macos", 2: "ios", 3: "tvos", 4: "watchos", 5: "bridgeos",
              6: "ios-mac", 7: "ios-simulator", 8: "tvos-simulator",
              9: "watchos-simulator", 10: "driverkit", 11: "visionos",
              12: "visionos-simulator"}
_FILETYPES = {1: "MH_OBJECT", 2: "MH_EXECUTE", 3: "MH_FVMLIB", 4: "MH_CORE",
              5: "MH_PRELOAD", 6: "MH_DYLIB", 7: "MH_DYLINKER", 8: "MH_BUNDLE",
              9: "MH_DYLIB_STUB", 10: "MH_DSYM", 11: "MH_KEXT_BUNDLE"}


def _arch(cpu: int, subtype: int) -> str:
    sub = subtype & 0xffffff
    if cpu == 0x100000c:
        return "arm64e" if sub == 2 else "arm64"
    if cpu == 0x1000007:
        return "x86_64h" if sub == 8 else "x86_64"
    if cpu == 12:
        return {9: "armv7", 11: "armv7s", 12: "armv7k"}.get(sub, f"arm-{sub}")
    return {7: "i386", 0x200000c: "arm64_32", 18: "ppc", 0x1000012: "ppc64"}.get(cpu, f"cpu-{cpu:x}-{sub}")


def _header(data: bytes):
    fmt = _THIN.get(data[:4])
    if fmt is None or len(data) < fmt[1]:
        raise ValueError("Invalid or truncated Mach-O header")
    endian, size = fmt
    cpu, sub, ft, count, commands = struct.unpack_from(endian + "5I", data, 4)
    if commands > len(data) - size or count > commands // 8:
        raise ValueError("Invalid Mach-O load-command bounds")
    return endian, size, cpu, sub, ft, count, commands


@dataclass
class _Slice:
    cpu: int
    subtype: int
    align: int
    data: bytes

    @property
    def arch(self):
        return _arch(self.cpu, self.subtype)


def _read(path: str):
    with open(path, "rb") as stream:
        magic = stream.read(4)
        if magic not in _THIN and magic not in _FAT:
            raise ValueError("Invalid or truncated Mach-O header")
        data = magic + stream.read()
    fat = _FAT.get(data[:4])
    if fat is None:
        _, _, cpu, sub, *_ = _header(data)
        return [_Slice(cpu, sub, 0, data)], None
    endian, wide = fat
    if len(data) < 8:
        raise ValueError("Truncated FAT header")
    count = struct.unpack_from(endian + "I", data, 4)[0]
    entry_size = 32 if wide else 20
    table_end = 8 + count * entry_size
    if not count or table_end > len(data):
        raise ValueError("Invalid FAT architecture table")
    slices, ranges = [], []
    for index in range(count):
        values = struct.unpack_from(endian + ("IIQQII" if wide else "IIIII"), data, 8 + index * entry_size)
        cpu, sub, offset, size, align = values[:5]
        if align > 30 or offset % (1 << align) or offset < table_end or size > len(data) - offset:
            raise ValueError("Invalid FAT slice bounds or alignment")
        if any(offset < end and start < offset + size for start, end in ranges):
            raise ValueError("Overlapping FAT slices")
        payload = data[offset:offset + size]
        _, _, actual_cpu, actual_sub, *_ = _header(payload)
        if (actual_cpu, actual_sub) != (cpu, sub):
            raise ValueError("FAT architecture does not match its Mach-O header")
        item = _Slice(cpu, sub, align, payload)
        if any(s.arch == item.arch for s in slices):
            raise ValueError("Duplicate FAT architecture")
        slices.append(item)
        ranges.append((offset, offset + size))
    return slices, fat


def is_macho(path: str) -> bool:
    try:
        _read(path)
        return True
    except (OSError, ValueError, struct.error):
        return False


def _pick_arch(archs: list[str]) -> str:
    return next((a for a in ("arm64e", "arm64") if a in archs), archs[0] if archs else "")


def _version(value: int) -> str:
    return f"{value >> 16}.{(value >> 8) & 255}.{value & 255}"


@traced("Inspecting Mach-O", "path")
def inspect(path: str) -> MachOInfo:
    slices, fat = _read(path)
    archs = [s.arch for s in slices]
    info = MachOInfo(path=path, archs=archs, is_fat=fat is not None, arch=_pick_arch(archs))
    data = next(s.data for s in slices if s.arch == info.arch)
    endian, pos, _, _, ft, count, commands = _header(data)
    end = pos + commands
    info.filetype = _FILETYPES.get(ft, f"MH_{ft}")
    for _ in range(count):
        if pos + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        cmd, size = struct.unpack_from(endian + "II", data, pos)
        if size < 8 or size % 4 or pos + size > end:
            raise ValueError("Invalid Mach-O load-command size")
        minimum = {0x32: 24, 0x21: 20, 0x2c: 24, 0x24: 16, 0x25: 16, 0x2f: 16, 0x30: 16}.get(cmd, 8)
        if size < minimum:
            raise ValueError("Truncated Mach-O metadata command")
        if cmd == 0x32:
            platform, version = struct.unpack_from(endian + "II", data, pos + 8)
            info.platform, info.minos = _PLATFORMS.get(platform, str(platform)), _version(version)
        elif cmd in (0x24, 0x25, 0x2f, 0x30) and not info.platform:
            info.platform = {0x24: "macos", 0x25: "ios", 0x2f: "tvos", 0x30: "watchos"}[cmd]
            info.minos = _version(struct.unpack_from(endian + "I", data, pos + 8)[0])
        elif cmd in (0x21, 0x2c):
            info.cryptid = struct.unpack_from(endian + "I", data, pos + 16)[0]
        pos += size
    if pos != end:
        raise ValueError("Mach-O load-command count does not match its size")
    return info


def _write(path: str, writer) -> None:
    """Publish only a complete output; also support replacing the input path."""
    destination = Path(path).absolute()
    fd, temporary = tempfile.mkstemp(prefix=".coldhook-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer(stream)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def thin(path: str, arch: str, out: str) -> None:
    slices, _ = _read(path)
    selected = next((s for s in slices if s.arch == arch), None)
    if selected is None:
        raise ValueError(f"Mach-O architecture not found: {arch}")
    _write(out, lambda stream: stream.write(selected.data))


def replace_slices(orig: str, replacements: dict[str, str], out: str) -> None:
    slices, fat = _read(orig)
    unknown = set(replacements) - {s.arch for s in slices}
    if unknown:
        raise ValueError(f"Replacement architectures not found: {sorted(unknown)}")
    for item in slices:
        if item.arch in replacements:
            replacement, replacement_fat = _read(replacements[item.arch])
            if replacement_fat is not None or (replacement[0].cpu, replacement[0].subtype) != (item.cpu, item.subtype):
                raise ValueError(f"Replacement must be a thin {item.arch} Mach-O with matching CPU subtype")
            item.data = replacement[0].data
    if fat is None:
        _write(out, lambda stream: stream.write(slices[0].data))
        return
    endian, wide = fat
    offset = 8 + len(slices) * (32 if wide else 20)
    entries = []
    for item in slices:
        offset = (offset + (1 << item.align) - 1) & ~((1 << item.align) - 1)
        if not wide and offset + len(item.data) > 0xffffffff:
            raise ValueError("Replacement exceeds FAT32 size limits")
        entries.append((item, offset))
        offset += len(item.data)

    def write(stream):
        stream.write(struct.pack(endian + "II", 0xcafebabf if wide else 0xcafebabe, len(slices)))
        for item, offset in entries:
            values = (item.cpu, item.subtype, offset, len(item.data), item.align)
            stream.write(struct.pack(endian + ("IIQQII" if wide else "IIIII"), *values, *((0,) if wide else ())))
        for item, offset in entries:
            stream.seek(offset)
            stream.write(item.data)
    _write(out, write)
