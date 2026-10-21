"""Exercise real binary layouts without an Apple toolchain or subprocesses."""
import struct
from unittest.mock import patch

import pytest

from coldhook import cli, ipa, macho
from coldhook.diagnostics import DiagnosticError


def image(cpu=0x100000c, subtype=0, endian="<", legacy=False):
    version = (14 << 16) | (2 << 8) | 1
    build = (struct.pack(endian + "4I", 0x25, 16, version, version) if legacy else
             struct.pack(endian + "6I", 0x32, 24, 2, version, version, 0))
    crypt = struct.pack(endian + "6I", 0x2c, 24, 0, 0, 1, 0)
    commands = build + crypt
    return struct.pack(endian + "8I", 0xfeedfacf, cpu, subtype, 2, 2, len(commands), 0, 0) + commands


def universal(payloads, endian=">", wide=False):
    result = bytearray(4096 * (len(payloads) + 1))
    struct.pack_into(endian + "II", result, 0, 0xcafebabf if wide else 0xcafebabe, len(payloads))
    for index, payload in enumerate(payloads):
        cpu, subtype = struct.unpack_from("<II", payload, 4)
        values = (cpu, subtype, 4096 * (index + 1), len(payload), 12)
        struct.pack_into(endian + ("IIQQII" if wide else "IIIII"), result,
                         8 + index * (32 if wide else 20), *values, *((0,) if wide else ()))
        result[values[2]:values[2] + len(payload)] = payload
    return bytes(result)


@pytest.fixture(autouse=True)
def no_external_tools():
    with patch("subprocess.run", side_effect=AssertionError("No external tool should run")):
        yield


@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("legacy", [False, True])
def test_metadata(tmp_path, endian, legacy):
    binary = tmp_path / "тест app"
    binary.write_bytes(image(subtype=0x80000002, endian=endian, legacy=legacy))
    info = macho.inspect(str(binary))
    assert (info.arch, info.filetype, info.platform, info.minos, info.encrypted) == (
        "arm64e", "MH_EXECUTE", "ios", "14.2.1", True)
    assert not info.is_fat
    assert macho.is_macho(str(binary))


@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("wide", [False, True])
def test_fat_replacement_preserves_unmodified_bytes(tmp_path, endian, wide):
    arm, intel = image(), image(cpu=0x1000007, subtype=3) + b"untouched payload"
    original = tmp_path / "universal"
    original.write_bytes(universal([arm, intel], endian, wide))
    before = original.read_bytes()
    assert macho.inspect(str(original)).archs == ["arm64", "x86_64"]
    replacement = tmp_path / "replacement"
    replacement.write_bytes(arm + b"replacement" * 700)
    output = tmp_path / "output"
    macho.replace_slices(str(original), {"arm64": str(replacement)}, str(output))
    assert original.read_bytes() == before
    extracted = tmp_path / "extracted"
    macho.thin(str(output), "x86_64", str(extracted))
    assert extracted.read_bytes() == intel
    macho.thin(str(output), "arm64", str(extracted))
    assert extracted.read_bytes() == replacement.read_bytes()
    macho.replace_slices(str(output), {"arm64": str(replacement)}, str(output))
    assert macho.inspect(str(output)).is_fat


def test_invalid_replacement_does_not_overwrite_output(tmp_path):
    original, replacement, output = [tmp_path / n for n in ("original", "replacement", "output")]
    original.write_bytes(universal([image()]))
    replacement.write_bytes(image(subtype=2))
    output.write_bytes(b"existing")
    with pytest.raises(ValueError, match="matching CPU subtype"):
        macho.replace_slices(str(original), {"arm64": str(replacement)}, str(output))
    assert output.read_bytes() == b"existing"


@pytest.mark.parametrize("data", [b"", b"not Mach-O", b"\xca\xfe\xba\xbe", image()[:40],
                                  struct.pack(">II", 0xcafebabe, 0xffffffff)])
def test_malformed_input(tmp_path, data):
    binary = tmp_path / "bad"
    binary.write_bytes(data)
    assert not macho.is_macho(str(binary))
    with pytest.raises(DiagnosticError):
        macho.inspect(str(binary))


def test_invalid_command_size(tmp_path):
    data = bytearray(image())
    struct.pack_into("<I", data, 36, 0)
    binary = tmp_path / "bad-command"
    binary.write_bytes(data)
    with pytest.raises(DiagnosticError, match="load-command size"):
        macho.inspect(str(binary))


def test_shared_cli_does_not_require_apple_tools(tmp_path):
    args = cli.build_parser().parse_args([
        "shared", "Input.app", "--dylib", "Hooks.dylib", "--out", "Output.app"])
    with patch.object(cli.toolchain, "ensure_merger"), \
         patch.object(cli.toolchain, "require_tools", side_effect=AssertionError("Apple tool check")), \
         patch.object(ipa, "patch_shared_bundle", return_value=True) as bundle:
        assert cli.cmd_shared(args) == 0
    bundle.assert_called_once()


def test_shared_fat_path(tmp_path):
    target, hook, output = [tmp_path / n for n in ("target", "hook", "output")]
    arm, intel = image(), image(cpu=0x1000007, subtype=3)
    target.write_bytes(universal([arm, intel]))
    hook.write_bytes(image())

    def merge(target, hook, out, import_path, **kwargs):
        from pathlib import Path
        assert macho.inspect(target).arch == "arm64"
        Path(out).write_bytes(Path(target).read_bytes() + b"merged")
        return {"hooks": [], "status": "no-applicable-hooks"}

    with patch.object(ipa, "_merge_shared_thin", side_effect=merge):
        ipa._merge_shared(str(target), str(hook), str(output), None)
    extracted = tmp_path / "intel"
    macho.thin(str(output), "x86_64", str(extracted))
    assert extracted.read_bytes() == intel
