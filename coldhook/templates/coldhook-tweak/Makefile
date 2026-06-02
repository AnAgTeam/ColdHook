ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@

# Путь к репозиторию ColdHook (подставлен `coldhook install-theos`).
COLDHOOK = @@COLDHOOK@@

# ColdHook-пре-пасс на ЭТАПЕ ПАРСИНГА Makefile ($(shell)): %hookf -> статический C-glue,
# остальное (ObjC %hook, %ctor, %group/%init) остаётся Logos. Результат — .coldhook/Tweak.xm,
# создаётся ДО проверки _FILES; logos на нём зовёт сам theos (со своими LOGOSFLAGS). Так ты
# пишешь только Tweak.x, а .xm — внутренний build-артефакт.
_CHGEN := $(shell mkdir -p .coldhook && python3 $(COLDHOOK)/coldhook/logos_prepass.py --strip-only Tweak.x > .coldhook/Tweak.xm)

@@PROJECTNAME@@_FILES = .coldhook/Tweak.xm $(COLDHOOK)/coldhook/substrate/substrate.m
@@PROJECTNAME@@_CFLAGS = -fobjc-arc -I$(COLDHOOK)/coldhook/include -I$(COLDHOOK)/coldhook/substrate
# -fixup_chains + -add_split_seg_info: обязательны, чтобы dylib мёрджился ColdHook.
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info
@@PROJECTNAME@@_FRAMEWORKS = Foundation

include $(THEOS)/makefiles/tweak.mk

# После `make` твик-dylib: .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib
# Инжект в цель — ОТДЕЛЬНЫМ шагом (merge + resign):
#   python3 -m coldhook merge --target <bin> --src ... (или scripts/build_install.py --hook <dylib>)
