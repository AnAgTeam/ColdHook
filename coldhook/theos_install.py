"""`coldhook install-theos` — поставить NIC-шаблон «ColdHook Tweak» в $THEOS.

Генерит .nic (формат NIC1) из coldhook/templates/coldhook-tweak/ и кладёт в $THEOS/templates/,
чтобы `nic.pl` показывал шаблон в списке. Абсолютный путь к репозиторию ColdHook вшивается в
Makefile шаблона (@@COLDHOOK@@), чтобы созданные проекты ссылались на этот клон. Остальные
@@…@@ (PROJECTNAME/PACKAGENAME/AUTHOR) — промпты nic.pl на этапе создания проекта.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TEMPLATE_DIR = os.path.join(HERE, "templates", "coldhook-tweak")

# Файлы шаблона в порядке записи в .nic
FILES = ["Makefile", "control", "Tweak.x", "README.md"]


def build_nic(coldhook_root: str) -> str:
    """Собрать текст .nic (NIC1). @@COLDHOOK@@ вшиваем сразу, остальные @@…@@ оставляет nic.pl.

    СВОИХ prompt'ов НЕ объявляем: nic.pl сам спрашивает Project Name/Package Name/Author и ставит
    встроенные @@PROJECTNAME@@/@@PACKAGENAME@@/@@USER@@. Объявить их же = двойной опрос."""
    # Заголовок 'nic 1' -> nic.pl грузит формат NIC::Formats::NIC1 (текстовый). Версия должна
    # быть \w+ без точки (иначе регекс _loadNIC не матчит и файл уходит в NICTar -> не парсится).
    out = ['nic 1', 'name "ColdHook Tweak"']
    for rel in FILES:
        with open(os.path.join(TEMPLATE_DIR, rel)) as f:
            content = f.read()
        content = content.replace("@@COLDHOOK@@", coldhook_root)
        if not content.endswith("\n"):
            content += "\n"
        nlines = content.count("\n")
        out.append(f"file {nlines} {rel}")
        out.append(content.rstrip("\n"))   # join добавит \n между строками блока
    return "\n".join(out) + "\n"


def install(theos: str | None = None, coldhook_root: str = ROOT) -> str:
    theos = theos or os.environ.get("THEOS") or os.path.expanduser("~/theos")
    if not os.path.isdir(theos):
        raise FileNotFoundError(f"THEOS не найден: {theos} (задай переменную THEOS)")
    tdir = os.path.join(theos, "templates")
    os.makedirs(tdir, exist_ok=True)
    dest = os.path.join(tdir, "coldhook-tweak.nic")
    with open(dest, "w") as f:
        f.write(build_nic(coldhook_root))
    return dest


def cmd_install_theos(args) -> int:
    dest = install(theos=getattr(args, "theos", None))
    print(f"Шаблон «ColdHook Tweak» установлен: {dest}")
    print("Теперь: nic.pl  ->  выбери 'ColdHook Tweak'  ->  пиши Tweak.x  ->  make")
    return 0
