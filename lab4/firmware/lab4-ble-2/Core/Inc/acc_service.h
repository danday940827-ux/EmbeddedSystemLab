/*
 * acc_service.h
 *
 *  Created on: 2026/10/14
 *      Author: jjlia
 */

#ifndef ACC_SERVICE_H
#define ACC_SERVICE_H
#include <stdint.h>
#include "bluenrg_def.h"

tBleStatus Add_Acc_Service(void);
void Acc_AttributeModified_CB(uint16_t handle, uint8_t len, uint8_t *data);
void Acc_OnDisconnect(void);
void TaskBLE_Body(void);
void TaskACC_Body(void);

#endif /* INC_ACC_SERVICE_H_ */
