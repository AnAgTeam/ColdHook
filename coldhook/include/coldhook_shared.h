#ifndef COLDHOOK_SHARED_H
#define COLDHOOK_SHARED_H

// Stable on-disk/in-image ABI for ColdHook bootstrap-table mode.
// All offsets are relative to the beginning of __DATA,__coldhook unless noted.

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define COLDHOOK_TABLE_MAGIC       UINT32_C(0x43484b54) /* "CHKT" */
#define COLDHOOK_TABLE_VERSION     UINT16_C(1)
#define COLDHOOK_TABLE_FLAG_NONE   UINT16_C(0)

struct coldhook_shared_table {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint16_t record_size;
    uint16_t flags;
    uint32_t count;
    uint32_t records_offset;
    uint32_t strings_offset;
    uint32_t strings_size;
};

struct coldhook_shared_record {
    uint64_t hook_id;
    uint32_t handler_slot_offset;
    uint32_t reserved0;
    uint64_t orig_image_offset;
    uint32_t handler_name_offset;
    uint32_t handler_name_size;
    uint32_t orig_slot_key;
    uint32_t flags;
};

// Shared-side registry used by generated handlers for CH_ORIG in bootstrap-table mode.
// Returns NULL until the corresponding target image has been processed.
void *coldhook_shared_orig_lookup(uint64_t hook_id);

// Public runtime lookup: returns the original implementation for a generated
// hook function address (&my_hook), or NULL when the target image is not ready.
void *coldhook_shared_find_orig(void *hook);
uint32_t coldhook_runtime_version(void);
const char *coldhook_last_error(void);

#if defined(__cplusplus)
static_assert(sizeof(coldhook_shared_table) == 28, "ColdHook shared table ABI changed");
static_assert(sizeof(coldhook_shared_record) == 40, "ColdHook shared record ABI changed");
#else
_Static_assert(sizeof(struct coldhook_shared_table) == 28, "ColdHook shared table ABI changed");
_Static_assert(sizeof(struct coldhook_shared_record) == 40, "ColdHook shared record ABI changed");
#endif

#ifdef __cplusplus
}
#endif

#endif // COLDHOOK_SHARED_H
