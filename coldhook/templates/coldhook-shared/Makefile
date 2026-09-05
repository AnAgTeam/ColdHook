ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@
COLDHOOK = @@COLDHOOK@@
# Path to the universal shared bootstrap dylib. Override this for your build host.
COLDHOOK_RUNTIME_DIR ?= /usr/local/lib

# Shared backend: the same dylib may be applied to every Mach-O in the bundle.
_CHRC := $(shell mkdir -p .coldhook && python3 $(COLDHOOK)/coldhook/logos_prepass.py --strip-only Tweak.x 1> .coldhook/Tweak.xm; echo $$?)
ifneq ($(_CHRC),0)
$(error ColdHook shared prepass failed)
endif

@@PROJECTNAME@@_FILES = .coldhook/Tweak.xm $(COLDHOOK)/coldhook/substrate/substrate.m $(COLDHOOK)/coldhook/substrate/coldhook_objc.m
@@PROJECTNAME@@_CFLAGS = -fobjc-arc -I$(COLDHOOK)/coldhook/include -I$(COLDHOOK)/coldhook/substrate
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info \
    -L$(COLDHOOK_RUNTIME_DIR) -lcoldhook -Wl,-rpath,$(COLDHOOK_RUNTIME_DIR)
@@PROJECTNAME@@_FRAMEWORKS = Foundation

include $(THEOS)/makefiles/tweak.mk

# Build output is a shared hook dylib. Apply it with:
# python3 -m coldhook shared <App.app> --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib -o <out.app>
