# Core boundary

`Core` contains only the STM32 startup shell and CubeMX-owned platform code:

- reset, clock, cache and GPIO clock initialization;
- exception handlers and HAL MSP setup;
- linker/runtime support.

`main.c` calls the application-neutral `STM32DeployApp_Run()` entry point. It
must not contain serial protocol state, model runtime code, audio feature
processing or microphone capture state.

Application code lives under `App/`:

- `Serial`: UART experiment transport and status LEDs;
- `AudioFrontend`: shared MFCC/LogMel/PCEN implementation;
- `ModelRuntime`: model metadata, TFLite Micro runtime and performance timing;
- `Microphone`: isolated future live-capture application and legacy references.
