#include "significant_motion.h"
#include "stm32l475e_iot01_accelero.h"

#define ADDR LSM6DSL_ACC_GYRO_I2C_ADDRESS_LOW
#define SM_THRESHOLD 8U
static volatile uint8_t pending;
static volatile uint32_t irq_time;

static int read_reg(uint8_t reg, uint8_t *value)
{
  return SENSOR_IO_ReadMultiple(ADDR, reg, value, 1) == HAL_OK;
}
static int write_checked(uint8_t reg, uint8_t value)
{
  uint8_t check = 0;
  SENSOR_IO_Write(ADDR, reg, value);
  return read_reg(reg, &check) && check == value;
}
static int update(uint8_t reg, uint8_t clear, uint8_t set)
{
  uint8_t value;
  return read_reg(reg, &value) && write_checked(reg, (value & (uint8_t)~clear) | set);
}

int Motion_Init(void)
{
  uint8_t value;
  /* Require existing BSP configuration: at least 26 Hz and +/-2 g. */
  if (!read_reg(0x10, &value) || (value & 0xF0) < 0x20 || (value & 0x0C)) return 0;
  if (!update(0x0D, 0x40, 0) || !update(0x19, 0x01, 0)) return 0;
  /* Bank A: SM_THS=8; preserve default pedometer debounce configuration. */
  if (!write_checked(0x01, 0x80)) { SENSOR_IO_Write(ADDR, 0x01, 0); return 0; }
  int threshold_ok = write_checked(0x13, SM_THRESHOLD);
  int bank_ok = write_checked(0x01, 0x00);
  if (!threshold_ok || !bank_ok) return 0;
  /* Active-high push-pull INT1, latched until FUNC_SRC1 is read. */
  if (!update(0x12, 0x30, 0) || !update(0x58, 0, 0x01)) return 0;
  if (!read_reg(0x53, &value)) return 0;

  __HAL_RCC_GPIOD_CLK_ENABLE();
  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = GPIO_PIN_11;
  gpio.Mode = GPIO_MODE_IT_RISING;
  gpio.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOD, &gpio);
  pending = 0;
  __HAL_GPIO_EXTI_CLEAR_IT(GPIO_PIN_11);
  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);
  /* Route only the significant-motion source to INT1 in this application. */
  if (!write_checked(0x0D, 0x40) || !update(0x19, 0, 0x05)) return 0;
  return 1;
}

void Motion_NotifyIRQ(void)
{
  /* No I2C, printf, or network calls in interrupt context. */
  if (!pending) irq_time = HAL_GetTick();
  pending = 1;
}

int Motion_Take(uint32_t *timestamp)
{
  uint32_t mask = __get_PRIMASK();
  __disable_irq();
  uint8_t have_irq = pending;
  uint32_t when = irq_time;
  pending = 0;
  __set_PRIMASK(mask);
  if (!have_irq) return 0;
  uint8_t source;
  /* Reading FUNC_SRC1 acknowledges the sensor latch, independently of EXTI. */
  if (!read_reg(0x53, &source))
  {
    mask = __get_PRIMASK();
    __disable_irq();
    if (!pending) irq_time = when;
    pending = 1;
    __set_PRIMASK(mask);
    return -1;
  }
  if (!(source & 0x40)) return 0;
  *timestamp = when;
  return 1;
}
