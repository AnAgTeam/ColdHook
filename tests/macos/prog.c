// prog.c — тестовый ГЛАВНЫЙ БИНАРЬ (MH_EXECUTE) для проверки merge в исполняемый.
// Зеркалит target.c, но это полноценный exe с main (__PAGEZERO + LC_MAIN). Импортирует
// printf (libSystem) — импорты таргета A мёрджер сохраняет. Символ цели: _domain_for.
#include <stdio.h>

const char *domain_for(int env);

// Указатель в __DATA_CONST -> rebase -> LC_SEGMENT_SPLIT_INFO (требование MachOMerger).
void *const g_self = (void *)domain_for;

const char *domain_for(int env)
{
    switch (env) {
        case 0:  return "https://prod.real.example";
        case 1:  return "https://stage.real.example";
        default: __builtin_trap();   // неизвестное окружение -> намеренный провал
    }
}

int main(void)
{
    printf("[prog] domain_for(0)  = %s\n", domain_for(0));
    fflush(stdout);
    printf("[prog] domain_for(99) = %s\n", domain_for(99)); // оригинал тут trap'ает
    printf("[prog] завершилось без падения\n");
    return 0;
}
