"""`coldhook install-theos` — поставить NIC-шаблоны ColdHook в $THEOS.

Для каждого шаблона из coldhook/templates/* генерит .nic (формат NIC1) и кладёт в $THEOS/templates/,
чтобы `nic.pl` показывал его в списке. Абсолютный путь к репозиторию ColdHook вшивается в Makefile
шаблона (@@COLDHOOK@@), чтобы созданные проекты ссылались на этот клон. Остальные @@…@@
(PROJECTNAME/PACKAGENAME/USER) — встроенные переменные nic.pl (свои prompt'ы НЕ объявляем).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TEMPLATES_DIR = os.path.join(HERE, "templates")

# (каталог шаблона, отображаемое имя в nic.pl)
TEMPLATES = [
    # Public template: shared is the default user-facing workflow.  The older
    # embedded templates remain in-tree for compatibility/tests but are not
    # advertised by NIC installation.
    ("coldhook-shared", "iphone/coldhook_tweak"),
]


def build_nic(template_dir: str, name: str, coldhook_root: str) -> str:
    """Собрать текст .nic (NIC1) из всех файлов каталога шаблона. @@COLDHOOK@@ вшиваем сразу,
    остальные @@…@@ оставляет nic.pl. Своих prompt'ов нет — nic.pl сам ставит встроенные
    @@PROJECTNAME@@/@@PACKAGENAME@@/@@USER@@ (иначе он спрашивал бы имя/пакет/автора дважды)."""
    # Заголовок 'nic 1' -> nic.pl грузит формат NIC::Formats::NIC1 (текстовый). Версия должна
    # быть \w+ без точки (иначе регекс _loadNIC не матчит и файл уходит в NICTar -> не парсится).
    out = ['nic 1', f'name "{name}"']
    for rel in sorted(os.listdir(template_dir)):
        path = os.path.join(template_dir, rel)
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            content = f.read()
        content = content.replace("@@COLDHOOK@@", coldhook_root)
        if not content.endswith("\n"):
            content += "\n"
        nlines = content.count("\n")
        out.append(f"file {nlines} {rel}")
        out.append(content.rstrip("\n"))   # join добавит \n между строками блока
    return "\n".join(out) + "\n"


def install(theos: str | None = None, coldhook_root: str = ROOT) -> list[str]:
    theos = theos or os.environ.get("THEOS") or os.path.expanduser("~/theos")
    if not os.path.isdir(theos):
        raise FileNotFoundError(f"THEOS не найден: {theos} (задай переменную THEOS)")
    tdir = os.path.join(theos, "templates")
    os.makedirs(tdir, exist_ok=True)
    dests = []
    for sub, name in TEMPLATES:
        dest = os.path.join(tdir, f"{sub}.nic")
        with open(dest, "w") as f:
            f.write(build_nic(os.path.join(TEMPLATES_DIR, sub), name, coldhook_root))
        dests.append(dest)
    return dests


def cmd_install_theos(args) -> int:
    dests = install(theos=getattr(args, "theos", None))
    print("Шаблоны установлены:")
    for d in dests:
        print(f"  {d}")
    print("Теперь: nic.pl  ->  «iphone/coldhook_tweak»  ->  make")
    return 0
