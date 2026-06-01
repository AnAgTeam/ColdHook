// driver.c — грузит dylib и зовёт domain_for(env) с заведомо «неизвестным» окружением.
// Без хука цель уходит в abort(); с хуком возвращает валидный домен.
// Путь к dylib — аргумент: ./driver <path-to-dylib>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

typedef const char *(*domain_for_t)(int);

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s <dylib>\n", argv[0]);
        return 2;
    }

    void *h = dlopen(argv[1], RTLD_NOW);
    if (!h) {
        fprintf(stderr, "[driver] dlopen failed: %s\n", dlerror());
        return 1;
    }

    // Сначала прогоняем НЕ хукаемую target_health() — она зовёт импорт A (_getpid).
    // Доказывает, что бинд A жив и резолвится в слитом бинаре через выполнение.
    int (*health)(void) = (int (*)(void))dlsym(h, "target_health");
    if (health) {
        int pid = health();
        printf("[driver] target_health() = %d (импорт A _getpid)\n", pid);
        if (pid <= 0) {
            fprintf(stderr, "[driver] импорт A вернул мусор -> бинд сломан\n");
            return 1;
        }
    }

    // Проверка внешнего импорта B (_getppid): хук возвращает свой getppid(),
    // сравниваем с нашим — один процесс, значения обязаны совпасть.
    int (*hppid)(void) = (int (*)(void))dlsym(h, "hook_ppid");
    if (hppid) {
        int from_hook = hppid();
        int real = (int)getppid();
        printf("[driver] hook getppid()=%d, наш getppid()=%d -> %s\n",
               from_hook, real, (from_hook == real) ? "СОВПАЛО" : "РАСХОЖДЕНИЕ!");
        if (from_hook != real) {
            fprintf(stderr, "[driver] импорт B _getppid резолвится неверно\n");
            return 1;
        }
    }

    domain_for_t fn = (domain_for_t)dlsym(h, "domain_for");
    if (!fn) {
        fprintf(stderr, "[driver] dlsym(domain_for) failed: %s\n", dlerror());
        return 1;
    }

    // env=0 — известное окружение. На merged хук делегирует оригиналу через ORIG,
    // значит должен вернуться реальный prod-домен. Проверка возврат-трамплина.
    const char *d0 = fn(0);
    printf("[driver] domain_for(0)  = %s\n", d0);
    if (!strstr(d0, "prod")) {
        fprintf(stderr, "[driver] ORIG сломан: ожидал реальный prod-домен, получил '%s'\n", d0);
        return 1;
    }

    // env=99 — неизвестное. Оригинал тут падает (SIGTRAP); хук возвращает fallback.
    const char *d99 = fn(99);
    printf("[driver] domain_for(99) = %s\n", d99);
    return 0;
}
