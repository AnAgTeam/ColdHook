ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@
COLDHOOK_RUNTIME_DIR ?= $(THEOS_PROJECT_DIR)

@@PROJECTNAME@@_FILES = $(shell find Sources/@@PROJECTNAME@@ -name '*.swift') $(shell find Sources/@@PROJECTNAME@@C -name '*.m' -o -name '*.c' -o -name '*.mm' -o -name '*.cpp')
@@PROJECTNAME@@_SWIFTFLAGS = -ISources/@@PROJECTNAME@@C/include
@@PROJECTNAME@@_CFLAGS = -fobjc-arc -ISources/@@PROJECTNAME@@C/include
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info \
    -Wl,-not_for_dyld_shared_cache -L$(COLDHOOK_RUNTIME_DIR) -lcoldhook

include $(THEOS)/makefiles/tweak.mk
