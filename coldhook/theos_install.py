"""Install portable, self-contained ColdHook NIC templates into Theos."""
import os
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(HERE, "templates")

# (каталог шаблона, отображаемое имя в nic.pl)
TEMPLATES = [
    # Public template: shared is the default user-facing workflow.  The older
    # embedded templates remain in-tree for compatibility/tests but are not
    # advertised by NIC installation.
    ("coldhook-shared", "iphone/coldhook_tweak"),
    ("coldhook-swift-shared", "iphone/coldhook_tweak_swift"),
]


def build_nic(template_dir: str, name: str) -> str:
    """Bundle template resources without embedding installation paths."""
    template = Path(template_dir)
    files = {path.relative_to(template).as_posix(): path
             for path in template.rglob("*")
             if path.is_file() and "__pycache__" not in path.parts
             and path.suffix not in {".pyc", ".pyo"} and path.name != ".DS_Store"}
    if template.name in {"coldhook-shared", "coldhook-tweak", "coldhook-swift-tweak"}:
        package = Path(HERE)
        for path in (package / "include").rglob("*"):
            if path.is_file():
                files["include/" + path.relative_to(package / "include").as_posix()] = path
        if template.name != "coldhook-swift-tweak":
            for filename in ("substrate.m", "coldhook_objc.m"):
                files[filename] = package / "substrate" / filename
            for path in (package / "substrate" / "CydiaSubstrate").rglob("*"):
                if path.is_file():
                    files["include/CydiaSubstrate/" + path.name] = path
    directories = set()
    for relative in files:
        for parent in Path(relative).parents:
            if parent != Path("."):
                directories.add(parent.as_posix())
    out = ['nic 1', f'name "{name}"']
    out.extend(f"dir {directory}" for directory in sorted(directories))
    for relative, path in sorted(files.items()):
        content = path.read_text(encoding="utf-8").rstrip("\n")
        out.extend((f"file {len(content.splitlines())} {relative}", content))
    return "\n".join(out) + "\n"


def install(theos: str | None = None) -> list[str]:
    theos = theos or os.environ.get("THEOS") or os.path.expanduser("~/theos")
    theos = os.path.abspath(os.path.expanduser(theos))
    if not os.path.isdir(theos):
        raise FileNotFoundError(f"Theos directory not found: {theos} (set THEOS or use --theos)")
    tdir = os.path.join(theos, "templates")
    os.makedirs(tdir, exist_ok=True)
    dests = []
    for sub, name in TEMPLATES:
        dest = os.path.join(tdir, f"{sub}.nic")
        content = build_nic(os.path.join(TEMPLATES_DIR, sub), name)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        dests.append(dest)
    return dests


def cmd_install_theos(args) -> int:
    dests = install(theos=getattr(args, "theos", None))
    print("Templates installed:")
    for d in dests:
        print(f"  {d}")
    print("Next: nic.pl -> iphone/coldhook_tweak / iphone/coldhook_tweak_swift -> make")
    return 0
