# LED_TEST

Target board: NUCLEO-L552ZE-Q / STM32L552ZE-Q.

## Build

```sh
cd .. && rm -rf build/ && mkdir build && cd build && cmake .. && make
```

## Flash

```sh
openocd -f flash.cfg
```

Expected successful flash output includes:

```text
** Programming Finished **
** Verify Started **
** Verified OK **
** Resetting Target **
```

## Board Jumper Check

For programming the on-board STM32L552 with the on-board ST-LINK:

| Jumper | Expected state | Purpose |
| --- | --- | --- |
| CN4 [1-2] | ON | ST-LINK SWCLK to target MCU |
| CN4 [3-4] | ON | ST-LINK SWDIO to target MCU |
| JP3 | ON | ST-LINK reset to target MCU |
| JP4 [1-2] | ON | VDD_MCU = 3.3 V |
| JP4 [2-3] | OFF | 1.8 V mode not used |
| JP5 [1-2] | ON | MCU VDD / IDD measurement path |
| JP6 [1-2] | ON | 5 V from ST-LINK USB |
| JP6 other positions | OFF | Other power sources not used |
| JP2 | OFF | Normal mode |
| CN5 | Not connected | External SWD can disturb on-board debug |

If the PC detects ST-LINK but OpenOCD reports `chipid: 0x000` or `unable to connect to the target`, check CN4 first.

## LED Verification

After flashing, the firmware uses the three user LEDs as a simple runtime stage indicator:

| Board LED | Color | MCU pin | Firmware stage | Expected observation |
| --- | --- | --- | --- | --- |
| LED1 / LD1 | Green | PC7 | `TEST_STAGE_AUDIO_CAPTURE` | Main normal state while audio is being captured |
| LED2 / LD2 | Blue | PB7 | `TEST_STAGE_MFCC_READY` | Briefly turns on when an MFCC window is ready |
| LED3 / LD3 | Red | PA9 | `TEST_STAGE_UART_TX` | Briefly turns on while MFCC data is sent over UART |
| LED3 / LD3 | Red | PA9 | `TEST_STAGE_FAULT` | Stays on if the firmware enters a fault stage |

Normal behavior is: green mostly on, with occasional short blue and red activity when MFCC data is produced and transmitted.

If the red LED stays on continuously, the firmware is likely in an error or fault path.

## UART Verification

The firmware initializes COM1 at `115200 8N1`.

Expected startup message:

```text
I2S AUDIO+MFCC TEST INIT
```

During normal operation, UART output includes lines like:

```text
AUDIO_FRAME,<count>,PEAK_MILLI=<value>
MFCC READY,<count>
MFCC_BEGIN,<count>,FRAMES=<audio_frame_count>,PEAK_MILLI=<value>,SCALE=1000
MFCC_ROW,<count>,<row>,...
MFCC_END,<count>
```

## I2S Microphone GPIO

The current firmware captures I2S microphone data through `SAI1_Block_B` and converts it to 512-sample float audio frames for MFCC processing.

| Signal | MCU pin | GPIO port/pin | Alternate function | Direction | Notes |
| --- | --- | --- | --- | --- | --- |
| `I2S_SD` | PB5 | GPIOB pin 5 | `GPIO_AF13_SAI1` | Microphone data to MCU | `SAI1_SD_B` |
| `I2S_SCK` | PB3 | GPIOB pin 3 | `GPIO_AF13_SAI1` | MCU clock output | `SAI1_SCK_B` |
| `I2S_WS` | PA4 | GPIOA pin 4 | `GPIO_AF13_SAI1` | MCU word-select output | `SAI1_FS_B` |

SAI/I2S settings used by the firmware:

| Setting | Value |
| --- | --- |
| Peripheral | `SAI1_Block_B` |
| Mode | Master receive |
| Standard | `SAI_I2S_STANDARD` |
| Data size | 24-bit protocol data |
| Audio frequency | 16 kHz |
| DMA | `DMA2_Channel1`, request `DMA_REQUEST_SAI1_B`, circular mode |

Important checks when `PEAK_MILLI=0`:

- Confirm the microphone or X-NUCLEO-CCA02M2 board has the correct 3.3 V power and ground.
- Confirm the microphone data line is routed to `PB5 / SAI1_SD_B`.
- Confirm `PB3 / SAI1_SCK_B` is routed to the microphone bit clock input.
- Confirm `PA4 / SAI1_FS_B` is routed to the microphone word-select input.
- Confirm the microphone output is I2S-compatible.
