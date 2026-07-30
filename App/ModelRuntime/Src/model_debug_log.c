#include <stdarg.h>

/*
 * TFLite Micro logging backend.
 *
 * The serial protocol is binary, so runtime diagnostics must not write to the
 * same UART. Keep the default backend silent; a board-specific debug channel
 * can provide a strong replacement in another application target.
 */
__attribute__((weak))
void DebugLog(const char *format, va_list args)
{
  (void)format;
  (void)args;
}
