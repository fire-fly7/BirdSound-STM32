#include <stdio.h>
#include <string.h>

__attribute__((weak))
void DebugLog(const char* s)
{
    // 什么都不做
    (void)s;
}