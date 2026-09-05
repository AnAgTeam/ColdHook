// ColdHook shared runtime/bootstrap.
// This dylib is intentionally independent of user hook code.  Targets publish
// __DATA,__coldhook records; this runtime resolves handler names and registers
// orig trampolines when images appear.

#include "include/coldhook_shared.h"

#if defined(__APPLE__)
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct orig_entry {
    uint64_t key;
    void *address;
    struct orig_entry *next;
};

static pthread_mutex_t g_orig_lock = PTHREAD_MUTEX_INITIALIZER;
static struct orig_entry *g_orig_entries;

void *coldhook_shared_orig_lookup(uint64_t hook_id) {
    pthread_mutex_lock(&g_orig_lock);
    for (struct orig_entry *e = g_orig_entries; e; e = e->next) {
        if (e->key == hook_id) {
            void *address = e->address;
            pthread_mutex_unlock(&g_orig_lock);
            return address;
        }
    }
    pthread_mutex_unlock(&g_orig_lock);
    return NULL;
}

static void register_orig(uint64_t key, void *address) {
    if (key == 0 || address == NULL) return;
    pthread_mutex_lock(&g_orig_lock);
    for (struct orig_entry *e = g_orig_entries; e; e = e->next) {
        if (e->key == key) {
            e->address = address;
            pthread_mutex_unlock(&g_orig_lock);
            return;
        }
    }
    struct orig_entry *e = (struct orig_entry *)malloc(sizeof(*e));
    if (e) {
        e->key = key;
        e->address = address;
        e->next = g_orig_entries;
        g_orig_entries = e;
    }
    pthread_mutex_unlock(&g_orig_lock);
}

static int valid_range(const uint8_t *base, size_t total, uint32_t off, size_t size) {
    return off <= total && size <= total - off;
}

static void process_image(const struct mach_header *header, intptr_t slide) {
    if (!header || header->magic != MH_MAGIC_64) return;

    unsigned long section_size = 0;
    uint8_t *table_bytes = (uint8_t *)getsectiondata((const struct mach_header_64 *)header,
                                                      "__COLDHOOK_DATA", "__coldhook", &section_size);
    if (!table_bytes || section_size < sizeof(struct coldhook_shared_table)) return;

    const struct coldhook_shared_table *table = (const struct coldhook_shared_table *)table_bytes;
    if (table->magic != COLDHOOK_TABLE_MAGIC || table->version != COLDHOOK_TABLE_VERSION) return;
    if (table->header_size < sizeof(*table) || table->header_size > section_size) return;
    if (table->record_size < sizeof(struct coldhook_shared_record)) return;
    if (!valid_range(table_bytes, section_size, table->records_offset,
                     (size_t)table->record_size * table->count)) return;
    if (!valid_range(table_bytes, section_size, table->strings_offset, table->strings_size)) return;

    const uint8_t *records = table_bytes + table->records_offset;
    const char *strings = (const char *)(table_bytes + table->strings_offset);

    for (uint32_t i = 0; i < table->count; i++) {
        const struct coldhook_shared_record *record =
            (const struct coldhook_shared_record *)(records + (size_t)i * table->record_size);
        if (!valid_range(table_bytes, section_size, record->handler_slot_offset, sizeof(void *))) continue;
        if (record->handler_name_offset > table->strings_size ||
            record->handler_name_size > table->strings_size - record->handler_name_offset ||
            record->handler_name_size == 0 || record->handler_name_size >= 1024) continue;

        char name[1024];
        memcpy(name, strings + record->handler_name_offset, record->handler_name_size);
        name[record->handler_name_size] = '\0';
        void *handler = dlsym(RTLD_DEFAULT, name);
        if (!handler) {
            fprintf(stderr, "coldhook: required handler '%s' was not found\n", name);
            abort();
        }

        void **slot = (void **)(table_bytes + record->handler_slot_offset);
        __atomic_store_n(slot, handler, __ATOMIC_RELEASE);

        if (record->orig_image_offset != 0) {
            void *orig = (void *)(slide + (intptr_t)record->orig_image_offset);
            const char *base_name = name;
            static const char gate_prefix[] = "coldhook_gate_";
            if (strncmp(name, gate_prefix, sizeof(gate_prefix) - 1) == 0)
                base_name += sizeof(gate_prefix) - 1;
            char orig_slot_name[1024];
            int written = snprintf(orig_slot_name, sizeof(orig_slot_name),
                                   "coldhook_orig_slot_%s", base_name);
            if (written > 0 && (size_t)written < sizeof(orig_slot_name)) {
                void **orig_slot = (void **)dlsym(RTLD_DEFAULT, orig_slot_name);
                if (!orig_slot) {
                    fprintf(stderr, "coldhook: ORIG slot '%s' was not found\n", orig_slot_name);
                    abort();
                }
                __atomic_store_n(orig_slot, orig, __ATOMIC_RELEASE);
            }
            if (base_name != name) {
                char dispatch_name[1024];
                written = snprintf(dispatch_name, sizeof(dispatch_name),
                                   "coldhook_disp_%s", base_name);
                if (written <= 0 || (size_t)written >= sizeof(dispatch_name)) abort();
                void **dispatch = (void **)dlsym(RTLD_DEFAULT, dispatch_name);
                if (!dispatch) {
                    fprintf(stderr, "coldhook: gated dispatch '%s' was not found\n", dispatch_name);
                    abort();
                }
                __atomic_store_n(dispatch, orig, __ATOMIC_RELEASE);
            }
            register_orig(record->orig_slot_key ? record->orig_slot_key : record->hook_id, orig);
        }
    }
}

static void image_added(const struct mach_header *header, intptr_t slide) {
    process_image(header, slide);
}

__attribute__((constructor))
static void coldhook_shared_init(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        image_added(_dyld_get_image_header(i), _dyld_get_image_vmaddr_slide(i));
    }
    _dyld_register_func_for_add_image(image_added);
}

#else
// Keep non-Apple builds linkable for header/API tests.
void *coldhook_shared_orig_lookup(uint64_t hook_id) {
    (void)hook_id;
    return NULL;
}
#endif
