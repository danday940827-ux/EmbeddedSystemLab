#ifndef LAB2_SIGNIFICANT_MOTION_H
#define LAB2_SIGNIFICANT_MOTION_H
#include "stm32l4xx_hal.h"
/* AN5040 section 6.2, built on the existing BSP SENSOR_IO interface. */
int Motion_Init(void);
void Motion_NotifyIRQ(void);
/* 1=confirmed hardware event, 0=no event, -1=read error (notification retained). */
int Motion_Take(uint32_t *timestamp);
#endif
