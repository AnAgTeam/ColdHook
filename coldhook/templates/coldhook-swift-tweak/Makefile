ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@

# Путь к репозиторию ColdHook (подставлен `coldhook install-theos`).
COLDHOOK = @@COLDHOOK@@

# Swift-хук: theos компилит Hook.swift + glue.c в один dylib. Ни пре-пасса, ни substrate-шима
# (чистый Swift, без ObjC-свизла) — в отличие от Logos-шаблона.
@@PROJECTNAME@@_FILES = Hook.swift glue.c
@@PROJECTNAME@@_CFLAGS = -I$(COLDHOOK)/coldhook/include
# -fixup_chains + -add_split_seg_info: обязательны, чтобы dylib мёрджился ColdHook.
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info

include $(THEOS)/makefiles/tweak.mk

# После `make` твик-dylib: .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib
# Инжект в цель — ОТДЕЛЬНЫМ шагом (merge + resign):
#   python3 -m coldhook merge --target <bin> --src <dylib> --out <patched>
#   (хук тянет Swift-рантайм -> merge добавит LC_LOAD_DYLIB через --allow-new-dylibs)
