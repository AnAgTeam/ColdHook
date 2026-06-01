// driver.c — грузит dylib и зовёт domain_for(env) с заведомо «неизвестным» окружением.
// Без хука цель уходит в abort(); с хуком возвращает валидный домен.
// Путь к dylib — аргумент: ./driver <path-to-dylib>
#include <dlfcn.h>
#include <stdio.h>

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

    domain_for_t fn = (domain_for_t)dlsym(h, "domain_for");
    if (!fn) {
        fprintf(stderr, "[driver] dlsym(domain_for) failed: %s\n", dlerror());
        return 1;
    }

    const char *res = fn(99); // 99 — неизвестное окружение -> без хука abort
    printf("[driver] domain_for(99) = %s\n", res);
    return 0;
}
