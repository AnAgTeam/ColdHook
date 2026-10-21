from pathlib import Path
from unittest.mock import patch

import pytest

from coldhook import theos_install, toolchain


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def test_merger_discovery_priority(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    current = executable(tmp_path / toolchain._merger_name)
    on_path = executable(tmp_path / "tools" / toolchain._merger_name)
    explicit = executable(tmp_path / "custom tools" / toolchain._merger_name)
    with patch("shutil.which", return_value=on_path):
        monkeypatch.setenv("COLDHOOK_MERGER", explicit)
        assert toolchain.ensure_merger() == explicit
        monkeypatch.delenv("COLDHOOK_MERGER")
        assert toolchain.ensure_merger() == current
        Path(current).unlink()
        assert toolchain.ensure_merger() == on_path
        monkeypatch.setenv("COLDHOOK_MERGER", str(tmp_path / "missing"))
        with pytest.raises(toolchain.ToolError):
            toolchain.ensure_merger()


def test_no_implicit_build_or_package_search(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COLDHOOK_MERGER", raising=False)
    # Any file outside the current-directory candidate would be accepted if searched.
    candidate = str(tmp_path / toolchain._merger_name)
    with patch("shutil.which", return_value=None), \
         patch("os.path.isfile", side_effect=lambda p: p != candidate), \
         patch("os.access", return_value=True):
        with pytest.raises(toolchain.ToolError):
            toolchain.ensure_merger()


def unpack_nic(text, destination):
    lines = iter(text.splitlines())
    assert next(lines) == "nic 1"
    assert next(lines).startswith('name "')
    for line in lines:
        kind, value = line.split(" ", 1)
        if kind == "dir":
            (destination / value).mkdir(parents=True, exist_ok=True)
        else:
            assert kind == "file"
            count, relative = value.split(" ", 1)
            (destination / relative).write_text(
                "\n".join(next(lines) for _ in range(int(count))) + "\n", encoding="utf-8")


@pytest.mark.parametrize("template", ["coldhook-shared", "coldhook-swift-shared",
                                     "coldhook-tweak", "coldhook-swift-tweak"])
def test_generated_template_is_relocatable(tmp_path, template):
    text = theos_install.build_nic(str(Path(theos_install.TEMPLATES_DIR) / template), "test")
    assert theos_install.HERE not in text
    assert "@@COLDHOOK@@" not in text
    unpack_nic(text, tmp_path)
    makefile = (tmp_path / "Makefile").read_text()
    assert "$(COLDHOOK)" not in makefile
    if template != "coldhook-swift-shared":
        assert (tmp_path / "include/coldhook.h").is_file()
    if template in {"coldhook-shared", "coldhook-tweak"}:
        assert (tmp_path / "substrate.m").is_file()
        assert (tmp_path / "coldhook_objc.m").is_file()
        assert (tmp_path / "include/CydiaSubstrate/CydiaSubstrate.h").is_file()
        assert "coldhook-logos --strip-only" in makefile


def test_install_only_writes_to_selected_theos(tmp_path):
    theos = tmp_path / "Theos installation"
    theos.mkdir()
    installed = theos_install.install(str(theos))
    assert len(installed) == len(theos_install.TEMPLATES)
    for name in installed:
        assert Path(name).parent == theos / "templates"
        text = Path(name).read_text(encoding="utf-8")
        assert str(theos) not in text
        assert theos_install.HERE not in text
