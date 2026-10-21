/*
 * acc_service.c
 *
 *  Created on: 2026/10/14
 *      Author: jjlia
 */

#include "main.h"
#include "cmsis_os.h"
#include "hci.h"
#include "bluenrg_conf.h"   /* PRINTF 定義在這裡 */
#include "bluenrg_gatt_aci.h"
#include "bluenrg_gatt_server.h"
#include "sensor.h"
#include "acc_service.h"

extern I2C_HandleTypeDef hi2c2;          /* CubeMX 在 main.c 產生的 I2C2 */
extern osMutexId_t bleMutexHandle;       /* 步驟 1-2 建立的 mutex */
extern __IO uint8_t set_connectable;     /* 定義在 sensor.c */
extern __IO uint32_t connected;

/* ---- LSM6DSL（直接用 I2C 讀暫存器）---- */
#define LSM6DSL_ADDR  0xD4   /* I2C 位址（8-bit 寫法） */
#define WHO_AM_I      0x0F   /* 讀到 0x6A 代表晶片正確 */
#define CTRL1_XL      0x10   /* 加速度計 ODR / 量程 */
#define CTRL3_C       0x12
#define OUTX_L_XL     0x28   /* X/Y/Z 共 6 bytes */
#define INT1_CTRL     0x0D   /* 哪些事件要送到 INT1 腳 */
#define CTRL10_C      0x19   /* 內建功能（embedded functions）開關 */
#define FUNC_SRC1     0x53   /* 內建功能的事件旗標，讀取後清除 */

static int LSM6DSL_Init(void)
{
  uint8_t id = 0, v;
  if (HAL_I2C_Mem_Read(&hi2c2, LSM6DSL_ADDR, WHO_AM_I, I2C_MEMADD_SIZE_8BIT, &id, 1, 100) != HAL_OK || id != 0x6A)
    return -1;
  v = 0x44; /* BDU=1 讀取時資料不會被換掉, IF_INC=1 位址自動遞增 */
  HAL_I2C_Mem_Write(&hi2c2, LSM6DSL_ADDR, CTRL3_C, I2C_MEMADD_SIZE_8BIT, &v, 1, 100);
  v = 0x40; /* ODR = 104 Hz, 量程 ±2g（significant motion 需要 ODR >= 26 Hz） */
  HAL_I2C_Mem_Write(&hi2c2, LSM6DSL_ADDR, CTRL1_XL, I2C_MEMADD_SIZE_8BIT, &v, 1, 100);

  /* 選作 (b)：significant motion（參考 ST AN5040） */
  v = 0x05; /* FUNC_EN=1 開啟內建功能, SIGN_MOTION_EN=1 開啟 significant motion */
  HAL_I2C_Mem_Write(&hi2c2, LSM6DSL_ADDR, CTRL10_C, I2C_MEMADD_SIZE_8BIT, &v, 1, 100);
  v = 0x40; /* INT1_SIGN_MOT=1：偵測到時拉高 INT1 腳（PD11） */
  HAL_I2C_Mem_Write(&hi2c2, LSM6DSL_ADDR, INT1_CTRL, I2C_MEMADD_SIZE_8BIT, &v, 1, 100);
  HAL_I2C_Mem_Read(&hi2c2, LSM6DSL_ADDR, FUNC_SRC1, I2C_MEMADD_SIZE_8BIT, &v, 1, 100); /* 清掉舊的旗標 */
  return 0;
}

static int LSM6DSL_ReadAcc(int16_t mg[3])
{
  uint8_t b[6];
  if (HAL_I2C_Mem_Read(&hi2c2, LSM6DSL_ADDR, OUTX_L_XL, I2C_MEMADD_SIZE_8BIT, b, 6, 100) != HAL_OK)
    return -1;
  for (int i = 0; i < 3; i++) {
    int16_t raw = (int16_t)(b[2*i] | (b[2*i+1] << 8));
    mg[i] = (int16_t)((int32_t)raw * 61 / 1000);   /* ±2g 時 0.061 mg/LSB */
  }
  return 0;
}

/* ---- GATT：自訂 128-bit UUID（陣列是 little-endian，順序是反的）----
 * Service : 12345678-1234-5678-1234-56789abc0000
 * Char A  : 12345678-1234-5678-1234-56789abc0001  加速度  Read+Notify
 * Char B  : 12345678-1234-5678-1234-56789abc0002  頻率Hz  Read+Write
 * Char C  : 12345678-1234-5678-1234-56789abc0003  significant motion 次數  Read+Notify */
#define MY_UUID(lo) {lo,0x00,0xbc,0x9a,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12}
static const uint8_t SERV_UUID[16]   = MY_UUID(0x00);
static const uint8_t ACC_UUID[16]    = MY_UUID(0x01);
static const uint8_t FREQ_UUID[16]   = MY_UUID(0x02);
static const uint8_t SIGMOT_UUID[16] = MY_UUID(0x03);

static uint16_t accServHandle, accCharHandle, freqCharHandle, sigmotCharHandle;
static volatile uint16_t acc_freq_hz = 10;
static volatile uint8_t  acc_notify_on = 0;
static volatile uint8_t  sigmot_notify_on = 0;
static uint16_t sigmot_count = 0;

tBleStatus Add_Acc_Service(void)
{
  tBleStatus ret;
  /* 屬性數量：service 1 + charA 3 (宣告/值/CCCD) + charB 2 + charC 3 = 9，多留一點給 10 */
  ret = aci_gatt_add_serv(UUID_TYPE_128, SERV_UUID, PRIMARY_SERVICE, 10, &accServHandle);
  if (ret != BLE_STATUS_SUCCESS) return ret;

  ret = aci_gatt_add_char(accServHandle, UUID_TYPE_128, ACC_UUID, 6,
                          CHAR_PROP_NOTIFY | CHAR_PROP_READ, ATTR_PERMISSION_NONE,
                          GATT_DONT_NOTIFY_EVENTS, 16, 0, &accCharHandle);
  if (ret != BLE_STATUS_SUCCESS) return ret;

  ret = aci_gatt_add_char(accServHandle, UUID_TYPE_128, FREQ_UUID, 2,
                          CHAR_PROP_READ | CHAR_PROP_WRITE, ATTR_PERMISSION_NONE,
                          GATT_NOTIFY_ATTRIBUTE_WRITE,   /* 被寫入時通知我們 */
                          16, 1, &freqCharHandle);
  if (ret != BLE_STATUS_SUCCESS) return ret;

  ret = aci_gatt_add_char(accServHandle, UUID_TYPE_128, SIGMOT_UUID, 2,
                          CHAR_PROP_NOTIFY | CHAR_PROP_READ, ATTR_PERMISSION_NONE,
                          GATT_DONT_NOTIFY_EVENTS, 16, 0, &sigmotCharHandle);
  if (ret != BLE_STATUS_SUCCESS) return ret;

  uint16_t f = acc_freq_hz;
  return aci_gatt_update_char_value(accServHandle, freqCharHandle, 0, 2, (uint8_t *)&f);
}

/* handle 規則：charHandle+1 = 值，charHandle+2 = CCCD */
void Acc_AttributeModified_CB(uint16_t handle, uint8_t len, uint8_t *data)
{
  if (handle == accCharHandle + 2) {
    acc_notify_on = data[0] & 0x01;
    PRINTF("ACC notify %s\n", acc_notify_on ? "ON" : "OFF");
  } else if (handle == freqCharHandle + 1) {
    uint16_t f = (len >= 2) ? (data[0] | (data[1] << 8)) : data[0];
    if (f < 1) f = 1;
    if (f > 100) f = 100;
    acc_freq_hz = f;
    PRINTF("ACC freq = %u Hz\n", f);
  } else if (handle == sigmotCharHandle + 2) {
    sigmot_notify_on = data[0] & 0x01;
    PRINTF("SIGMOT notify %s\n", sigmot_notify_on ? "ON" : "OFF");
  }
}

void Acc_OnDisconnect(void) { acc_notify_on = 0; sigmot_notify_on = 0; }

/* ---- TASK_BLE：處理 BLE 事件 ---- */
void TaskBLE_Body(void)
{
  for (;;) {
    osMutexAcquire(bleMutexHandle, osWaitForever);
    if (set_connectable) {           /* 剛開機或斷線後重新廣播 */
      Set_DeviceConnectable();
      set_connectable = FALSE;
    }
    hci_user_evt_proc();             /* 處理連線/斷線/寫入事件 */
    osMutexRelease(bleMutexHandle);
    osDelay(5);
  }
}

/* ---- 選作 (b)：significant motion 中斷 ----
 * LSM6DSL INT1 -> PD11 -> EXTI11 -> HAL_GPIO_EXTI_Callback()
 * 中斷裡不能用 I2C（太慢），所以只發一個 thread flag 叫醒 TASK_ACC，
 * 由 TASK_ACC 去讀 FUNC_SRC1 並 notify。I2C 也因此只有 TASK_ACC 在用。 */
#define SIGMOT_FLAG  0x0001U
static osThreadId_t accTaskId = NULL;

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  if (GPIO_Pin == LSM6DSL_INT1_EXTI11_Pin && accTaskId != NULL)
    osThreadFlagsSet(accTaskId, SIGMOT_FLAG);   /* 可在中斷中呼叫（EXTI 優先權 = 5） */
}

static void SigMot_Handle(void)
{
  uint8_t src = 0;
  if (HAL_I2C_Mem_Read(&hi2c2, LSM6DSL_ADDR, FUNC_SRC1, I2C_MEMADD_SIZE_8BIT, &src, 1, 100) != HAL_OK)
    return;
  if (!(src & 0x40))   /* SIGN_MOTION_IA */
    return;

  sigmot_count++;
  PRINTF("Significant motion #%u\n", sigmot_count);

  uint16_t c = sigmot_count;
  osMutexAcquire(bleMutexHandle, osWaitForever);
  aci_gatt_update_char_value(accServHandle, sigmotCharHandle, 0, 2, (uint8_t *)&c);  /* 有訂閱就會 notify */
  osMutexRelease(bleMutexHandle);
}

/* ---- TASK_ACC：照頻率取樣並 notify，並處理 significant motion ---- */
void TaskACC_Body(void)
{
  int16_t xyz[3];
  accTaskId = osThreadGetId();
  if (LSM6DSL_Init() != 0) PRINTF("LSM6DSL init failed!\n");

  uint32_t next = osKernelGetTickCount();
  for (;;) {
    /* 等到下次取樣時間；期間如果中斷發生，會提早被叫醒 */
    int32_t wait = (int32_t)(next - osKernelGetTickCount());
    if (wait > 0) {
      uint32_t flags = osThreadFlagsWait(SIGMOT_FLAG, osFlagsWaitAny, (uint32_t)wait);
      if (!(flags & osFlagsError)) {   /* 不是 timeout -> 是 significant motion */
        SigMot_Handle();
        continue;
      }
    }

    if (connected && acc_notify_on && LSM6DSL_ReadAcc(xyz) == 0) {
      osMutexAcquire(bleMutexHandle, osWaitForever);
      aci_gatt_update_char_value(accServHandle, accCharHandle, 0, 6, (uint8_t *)xyz);
      osMutexRelease(bleMutexHandle);
    }
    next += 1000 / acc_freq_hz;
    if ((int32_t)(osKernelGetTickCount() - next) > 1000)   /* 落後太多就重新對齊 */
      next = osKernelGetTickCount();
  }
}
