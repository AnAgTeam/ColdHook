// app_main.c — главный экзешник тестового .app. Линкуется с встроенным libcore.dylib
// (наш «таргет») и зовёт domain_for напрямую, как настоящий апп зовёт свой фреймворк.
// На baseline domain_for(99) уходит в trap; на пропатченном — возвращает fallback.
#include <stdio.h>

extern const char *domain_for(int env);

int main(void)
{
    printf("[app] domain_for(0)  = %s\n", domain_for(0));
    fflush(stdout);
    printf("[app] domain_for(99) = %s\n", domain_for(99)); // baseline: trap; patched: fallback
    printf("[app] завершилось без падения\n");
    return 0;
}
