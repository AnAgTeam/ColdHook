ARCHS = arm64
TARGET = iphone:clang:latest:15.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = @@PROJECTNAME@@
COLDHOOK = @@COLDHOOK@@
COLDHOOK_RUNTIME_DIR ?= $(THEOS_PROJECT_DIR)

@@PROJECTNAME@@_FILES = Hook.swift glue.c
@@PROJECTNAME@@_CFLAGS = -I$(COLDHOOK)/coldhook/include
@@PROJECTNAME@@_LDFLAGS = -Wl,-no_warn_inits -Wl,-fixup_chains -Xlinker -add_split_seg_info \
    -Wl,-not_for_dyld_shared_cache -L$(COLDHOOK_RUNTIME_DIR) -lcoldhook

include $(THEOS)/makefiles/tweak.mk

