#include <syslog.h>

// Probe-конструктор: запускается на загрузке образа (через __TEXT,__init_offsets).
// Виден в Console.app по фильтру "coldhook" -> доказательство, что слитый хук замапился.
__attribute__((constructor)) static void chctor(void) {
    syslog(LOG_ERR, "[coldhook] hook loaded; patched by address");
}
