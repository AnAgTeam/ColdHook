// ColdHook ObjC-бутстрап: уникует selref'ы твика после merge (нужно для Logos %hook).
//
// Зачем. ColdHook мёрджит твик в таргет append-режимом -> сегменты твика переименованы
// (__DATA_CONST -> __BDATA_CONST). ObjC-runtime сканирует __objc_selrefs только в
// __DATA/__DATA_CONST -> selref'ы твика НЕ уникуются: @selector в коде хука держит указатель
// на СВОЮ копию cstring, а не канонический SEL -> objc_msgSend / class_getInstanceMethod
// промахиваются (метод не находится). Этот конструктор повторяет уникование вручную: проходит
// __B*-секцию __objc_selrefs мёрджнутого образа и заменяет каждый указатель на
// sel_registerName(имя) -> канонический SEL.
//
// Линкуется в КАЖДЫЙ Logos-твик (как substrate.m). Для не-ObjC твика секции нет -> no-op.
// Идемпотентно: sel_registerName канонична, повторный прогон безвреден. classref'ы на классы
// таргета трогать не надо — их биндит dyld (это undefined-символы _OBJC_CLASS_$_*).
//
// Парность: substrate.m::MSHookMessageEx дополнительно дефенсивно уникует ВХОДЯЩИЙ селектор
// регистрации свиззла -> корректность не зависит от порядка конструкторов (бутстрап vs %ctor).
// Здесь же уникуются selref'ы в ТЕЛЕ хука (их шлют objc_msgSend'ом при ВЫЗОВЕ хука, а к тому
// моменту конструкторы давно отработали).

#include <dlfcn.h>
#include <objc/runtime.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>

static void coldhook_unique_selrefs(const struct mach_header_64 *mh, const char *seg) {
    unsigned long sz = 0;
    uint8_t *base = getsectiondata(mh, seg, "__objc_selrefs", &sz);   // slide уже учтён
    if (!base || !sz) return;
    SEL *p = (SEL *)base;
    // Значение selref'а ДО уникования — указатель на cstring имени (__objc_methname). На Apple
    // канонический SEL — тоже указатель на имя, поэтому каст корректен и идемпотентен. Через void*,
    // чтобы не ловить -Wcast-of-sel-type.
    for (unsigned long i = 0; i < sz / sizeof(SEL); i++)
        p[i] = sel_registerName((const char *)(void *)p[i]);         // имя -> канонический SEL
}

__attribute__((constructor))
static void coldhook_objc_bootstrap(void) {
    Dl_info info;
    if (!dladdr((void *)coldhook_objc_bootstrap, &info)) return;      // -> mach_header слитого образа
    const struct mach_header_64 *mh = (const struct mach_header_64 *)info.dli_fbase;
    coldhook_unique_selrefs(mh, "__BDATA_CONST");   // переименованный __DATA_CONST (совр. toolchain)
    coldhook_unique_selrefs(mh, "__BDATA");          // или __DATA (старый toolchain)
}
