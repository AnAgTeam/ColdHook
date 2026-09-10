// ColdHook shared runtime/bootstrap.
// This dylib is intentionally independent of user hook code.  Targets publish
// __DATA,__coldhook records; this runtime resolves complete magic entry names
// in their provider image and registers orig trampolines when images appear.

#include "include/coldhook_shared.h"

#if defined(__APPLE__)
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <os/log.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct orig_entry {
    uint64_t key;
    void *handler;
    void *address;
    struct orig_entry *next;
};

static pthread_mutex_t g_orig_lock = PTHREAD_MUTEX_INITIALIZER;
static struct orig_entry *g_orig_entries;
static _Thread_local const char *g_last_error;
static int g_debug = -1;
static os_log_t g_log;

static int coldhook_debug_enabled(void) {
    if (g_debug < 0) {
        g_debug = getenv("COLDHOOK_DEBUG") ? 1 : 0;
        g_log = os_log_create("com.coldhook.runtime", "shared");
    }
    return g_debug;
}

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

void *coldhook_shared_find_orig(void *hook) {
    pthread_mutex_lock(&g_orig_lock);
    for (struct orig_entry *e = g_orig_entries; e; e = e->next) {
        if (e->handler == hook) {
            void *address = e->address;
            pthread_mutex_unlock(&g_orig_lock);
            return address;
        }
    }
    pthread_mutex_unlock(&g_orig_lock);
    return NULL;
}

uint32_t coldhook_runtime_version(void) { return 1; }
const char *coldhook_last_error(void) { return g_last_error; }

static void register_orig(uint64_t key, void *handler, void *address) {
    if (key == 0 || address == NULL) return;
    pthread_mutex_lock(&g_orig_lock);
    for (struct orig_entry *e = g_orig_entries; e; e = e->next) {
        if (e->key == key) {
            e->handler = handler;
            e->address = address;
            pthread_mutex_unlock(&g_orig_lock);
            return;
        }
    }
    struct orig_entry *e = (struct orig_entry *)malloc(sizeof(*e));
    if (e) {
        e->key = key;
        e->handler = handler;
        e->address = address;
        e->next = g_orig_entries;
        g_orig_entries = e;
    }
    pthread_mutex_unlock(&g_orig_lock);
}

static int valid_range(const uint8_t *base, size_t total, uint32_t off, size_t size) {
    return off <= total && size <= total - off;
}

struct hook_provider {
    void *handle;
    void *entry;
    void **orig_slot;
};

static int provider_open_flags(void) {
    int flags = RTLD_LAZY | RTLD_NOLOAD;
#ifdef RTLD_FIRST
    flags |= RTLD_FIRST;
#endif
    return flags;
}

static int find_hook_provider(const char *entry_name, const char *orig_name,
                              struct hook_provider *provider) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const struct mach_header *image = _dyld_get_image_header(i);
        Dl_info info = {0};
        if (!image || !dladdr(image, &info) || !info.dli_fname) continue;
        void *handle = dlopen(info.dli_fname, provider_open_flags());
        if (!handle) continue;
        void *entry = dlsym(handle, entry_name);
        void **orig_slot = entry ? (void **)dlsym(handle, orig_name) : NULL;
        if (entry && orig_slot) {
            provider->handle = handle;
            provider->entry = entry;
            provider->orig_slot = orig_slot;
            return 1;
        }
        dlclose(handle);
    }
    return 0;
}

static void *entry_handler(void *entry) {
    uint32_t instruction = 0;
    memcpy(&instruction, entry, sizeof(instruction));
    if ((instruction & UINT32_C(0xfc000000)) != UINT32_C(0x14000000)) return entry;
    int32_t immediate = (int32_t)(instruction << 6) >> 6;
    return (uint8_t *)entry + (int64_t)immediate * 4;
}

static void process_image(const struct mach_header *header, intptr_t slide) {
    if (!header || header->magic != MH_MAGIC_64) return;

    if (coldhook_debug_enabled()) {
        Dl_info info = {0};
        if (dladdr(header, &info) && info.dli_fname)
            os_log(g_log, "inspect image %{public}s", info.dli_fname);
    }

    unsigned long section_size = 0;
    uint8_t *table_bytes = (uint8_t *)getsectiondata((const struct mach_header_64 *)header,
                                                      "__COLDHOOK_DATA", "__coldhook", &section_size);
    if (!table_bytes || section_size < sizeof(struct coldhook_shared_table)) return;

    if (coldhook_debug_enabled())
        os_log(g_log, "shared table found (%lu bytes)", section_size);

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

        char entry_name[1024];
        memcpy(entry_name, strings + record->handler_name_offset, record->handler_name_size);
        entry_name[record->handler_name_size] = '\0';
        static const char dyn_prefix[] = "COLDHOOK_DYN_";
        if (strncmp(entry_name, dyn_prefix, sizeof(dyn_prefix) - 1) != 0) {
            fprintf(stderr, "coldhook: invalid shared entry name '%s'\n", entry_name);
            abort();
        }

        if (record->orig_image_offset != 0) {
            void *orig = (void *)(slide + (intptr_t)record->orig_image_offset);
            char orig_name[1024];
            static const char orig_prefix[] = "COLDHOOK_ORIG_";
            size_t suffix_size = strlen(entry_name) - (sizeof(dyn_prefix) - 1);
            if ((sizeof(orig_prefix) - 1) + suffix_size >= sizeof(orig_name)) abort();
            memcpy(orig_name, orig_prefix, sizeof(orig_prefix) - 1);
            memcpy(orig_name + sizeof(orig_prefix) - 1,
                   entry_name + sizeof(dyn_prefix) - 1, suffix_size + 1);

            struct hook_provider provider = {0};
            if (!find_hook_provider(entry_name, orig_name, &provider)) {
                fprintf(stderr, "coldhook: provider for '%s' and '%s' was not found\n",
                        entry_name, orig_name);
                abort();
            }
            if (coldhook_debug_enabled())
                os_log(g_log, "resolve entry '%{public}s' -> %p", entry_name, provider.entry);

            // Publish the target-local trampoline before making the provider
            // reachable from the target's hot-path slot.
            __atomic_store_n(provider.orig_slot, orig, __ATOMIC_RELEASE);
            void **slot = (void **)(table_bytes + record->handler_slot_offset);
            __atomic_store_n(slot, provider.entry, __ATOMIC_RELEASE);
            register_orig(record->orig_slot_key ? record->orig_slot_key : record->hook_id,
                          entry_handler(provider.entry), orig);
            dlclose(provider.handle);
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
void *coldhook_shared_find_orig(void *hook) { (void)hook; return NULL; }
uint32_t coldhook_runtime_version(void) { return 1; }
const char *coldhook_last_error(void) { return NULL; }
#endif
