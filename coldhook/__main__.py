import sys

if sys.version_info < (3, 11):
    sys.exit("ColdHook требует Python 3.11 или новее; запусти python3.11 -m coldhook.")

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
