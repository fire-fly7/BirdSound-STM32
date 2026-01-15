#ifndef MFCC_H
#define MFCC_H

#include <stdint.h>
#include <stdbool.h>
#include "mel_filterbank.h"

#define MFCC_SAMPLE_RATE   16000
#define MFCC_FRAME_LEN     1024
#define MFCC_FRAME_STEP    512
#define MFCC_NUM_MEL       26
#define MFCC_NUM_COEFF     13
#define MFCC_NUM_FRAMES    32

void MFCC_Init(void);

void MFCC_Stream_PushSamples(const float *semplar_512);

bool MFCC_Stream_Ready(void);

void MFCC_Stream_Get(float *mfcc_out);

void MFCC_Reset(void);

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif


#endif // MFCC_H
