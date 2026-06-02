#include <syslog.h>

// Probe-конструктор: запускается на загрузке образа (через __TEXT,__init_offsets).
// Виден в Console.app по фильтру "coldhook" -> доказательство, что слитый хук замапился
// и его init-секция выполнилась на устройстве. Ничего в приложении не ломает.
__attribute__((constructor)) static void chctor(void) {
    syslog(LOG_ERR, "[coldhook] hook loaded; url(for:) patched");
}
