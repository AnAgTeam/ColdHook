ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@
# Path to the runtime linker stub. The real dylib is only needed at launch.
COLDHOOK_RUNTIME_DIR ?= $(THEOS_PROJECT_DIR)

# Shared backend: the same dylib may be applied to every Mach-O in the bundle.
_CHRC := $(shell mkdir -p .coldhook && coldhook-logos --strip-only Tweak.x 1> .coldhook/Tweak.xm; echo $$?)
ifneq ($(_CHRC),0)
$(error ColdHook shared prepass failed)
endif

@@PROJECTNAME@@_FILES = .coldhook/Tweak.xm substrate.m coldhook_objc.m
@@PROJECTNAME@@_CFLAGS = -fobjc-arc -Iinclude -Iinclude/CydiaSubstrate
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info \
    -Wl,-not_for_dyld_shared_cache \
    -L"$(COLDHOOK_RUNTIME_DIR)" -lcoldhook
@@PROJECTNAME@@_FRAMEWORKS = Foundation

include $(THEOS)/makefiles/tweak.mk

# Build output is a shared hook dylib. Apply it with:
# python3 -m coldhook shared <App.app> --dylib .theos/obj/debug/arm64/@@PROJECTNAME@@.dylib -o <out.app>
