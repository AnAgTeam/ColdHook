ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@


# ColdHook-пре-пасс на ЭТАПЕ ПАРСИНГА Makefile ($(shell)): %hookf -> статический C-glue,
# остальное (ObjC %hook, %ctor, %group/%init) остаётся Logos. Результат — .coldhook/Tweak.xm,
# создаётся ДО проверки _FILES; logos на нём зовёт сам theos (со своими LOGOSFLAGS). Так ты
# пишешь только Tweak.x, а .xm — внутренний build-артефакт.
# ВАЖНО: $(shell) проглатывает ненулевой exit, а '> Tweak.xm' уже обрезал файл -> без проверки
# make слинковал бы ПУСТОЙ .xm (тихий no-op хук). Ловим код возврата в _CHRC и валим через
# $(error). stderr пре-пасса (причина) идёт на терминал выше.
_CHRC := $(shell mkdir -p .coldhook && coldhook-logos --strip-only Tweak.x 1> .coldhook/Tweak.xm; echo $$?)
ifneq ($(_CHRC),0)
$(error ColdHook prepass failed; see the error above)
endif

# substrate.m — шим MSHookMessageEx (ObjC %hook -> method_setImplementation).
# coldhook_objc.m — бутстрап, уникует selref'ы твика (после merge они в __BDATA_CONST, ObjC-runtime
# их сам не находит). Нужен для %hook; для не-ObjC твика — no-op.
@@PROJECTNAME@@_FILES = .coldhook/Tweak.xm substrate.m coldhook_objc.m
@@PROJECTNAME@@_CFLAGS = -fobjc-arc -Iinclude -Iinclude/CydiaSubstrate
# -fixup_chains + -add_split_seg_info: обязательны, чтобы dylib мёрджился ColdHook.
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info
@@PROJECTNAME@@_FRAMEWORKS = Foundation

include $(THEOS)/makefiles/tweak.mk

# После `make` твик-dylib: .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib
# Инжект в цель — ОТДЕЛЬНЫМ шагом (merge + resign):
#   python3 -m coldhook merge --target <bin> --src ... (или scripts/build_install.py --hook <dylib>)
