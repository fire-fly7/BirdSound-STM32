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
PDM DFSDM AUDIO+MFCC TEST INIT
```

During normal operation, UART output includes lines like:

```text
AUDIO_FRAME,<count>,PEAK_MILLI=<value>
MFCC READY,<count>
MFCC_BEGIN,<count>,FRAMES=<audio_frame_count>,PEAK_MILLI=<value>,SCALE=1000
MFCC_ROW,<count>,<row>,...
MFCC_END,<count>
```

## PDM Microphone GPIO

The current firmware captures PDM microphone data through `DFSDM1_Filter0` and converts it to 512-sample float audio frames for MFCC processing.

| Signal | MCU pin | GPIO port/pin | Alternate function | Direction | Notes |
| --- | --- | --- | --- | --- | --- |
| `PDM_DATA` | PB1 | GPIOB pin 1 | `GPIO_AF6_DFSDM1` | Microphone data to MCU | `DFSDM1_DATIN0` |
| `PDM_CKIN` | PB2 | GPIOB pin 2 | `GPIO_AF6_DFSDM1` | Optional external PDM clock input | `DFSDM1_CKIN0`; not required with the current internal-clock firmware |
| `PDM_CKOUT` | PF10 | GPIOF pin 10 | `GPIO_AF6_DFSDM1` | MCU clock output | `DFSDM1_CKOUT`; connect to microphone CLK |

DFSDM settings used by the firmware:

| Setting | Value |
| --- | --- |
| Filter | `DFSDM1_Filter0` |
| Channel | `DFSDM1_Channel0` |
| Regular channel | `DFSDM_CHANNEL_0` |
| Mode | Continuous regular conversion |
| Filter order | `DFSDM_FILTER_SINC3_ORDER` |
| Filter oversampling | `125` |
| Output clock divider | `55` |
| SPI clock source | `DFSDM_CHANNEL_SPI_CLOCK_INTERNAL` |
| DMA | `DMA1_Channel1`, request `DMA_REQUEST_DFSDM1_FLT0`, circular mode |

Important checks when `PEAK_MILLI=0`:

- Confirm the microphone or X-NUCLEO-CCA02M2 board has the correct 3.3 V power and ground.
- Confirm the PDM data line is routed to `PB1 / DFSDM1_DATIN0`.
- Confirm `PF10 / DFSDM1_CKOUT` is routed to the microphone clock input.
- Confirm the microphone is a PDM microphone, such as the MP34DT06J used on X-NUCLEO-CCA02M2.
- The old I2S wiring for ICS43434 (`PB5/PB3/PA4`) is no longer used by this firmware.
