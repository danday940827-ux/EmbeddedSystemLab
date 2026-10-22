/* PWM LED dimming, basic problem. No RTOS; Input Capture is a later stage. */
#include "main.h"

TIM_HandleTypeDef htim2;
/* Watch these in CubeIDE. Change pwm_auto_cycle=0 for a stable LA capture.
 * In manual mode set pwm_requested_percent to 10, 45 or 95. */
volatile uint32_t pwm_auto_cycle = 1;
volatile uint32_t pwm_requested_percent = 10;
volatile uint32_t pwm_applied_percent = 10;
volatile uint32_t pwm_compare_ticks = 100;
volatile uint32_t pwm_timer_clock_hz = 0;
volatile uint32_t pwm_ready = 0;
volatile uint32_t error_code = 0;
static void SystemClock_Config(void);
static void PWM_Init(void);

void Error_Handler(void)
{
  error_code = 1;
  __disable_irq();
  while (1) { }
}

int main(void)
{
  HAL_Init();
  SystemClock_Config();
  PWM_Init();
  if (HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1) != HAL_OK) Error_Handler();
  pwm_ready = 1;
  uint32_t last_change = HAL_GetTick();
  uint32_t previous_auto = pwm_auto_cycle;
  for (;;) {
    uint32_t now = HAL_GetTick();
    if (pwm_auto_cycle != previous_auto) {
      last_change = now;
      previous_auto = pwm_auto_cycle;
    }
    if (pwm_auto_cycle && (uint32_t)(now - last_change) >= 2000U) {
      last_change = now;
      pwm_requested_percent = pwm_applied_percent == 10U ? 45U :
                              pwm_applied_percent == 45U ? 95U : 10U;
    }
    uint32_t request = pwm_requested_percent;
    if ((request == 10U || request == 45U || request == 95U) &&
        request != pwm_applied_percent) {
      __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_1, request * 10U);
      /* CCR preload takes effect on the next PWM update (within 1 ms). */
      pwm_compare_ticks = request * 10U;
      pwm_applied_percent = request;
    }
  }
}

static void PWM_Init(void)
{
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_TIM2_CLK_ENABLE();
  GPIO_InitTypeDef gpio = {0};
  gpio.Pin = GPIO_PIN_5;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  gpio.Alternate = GPIO_AF1_TIM2;
  HAL_GPIO_Init(GPIOA, &gpio);

  RCC_ClkInitTypeDef clocks = {0};
  uint32_t latency;
  HAL_RCC_GetClockConfig(&clocks, &latency);
  pwm_timer_clock_hz = HAL_RCC_GetPCLK1Freq();
  if (clocks.APB1CLKDivider != RCC_HCLK_DIV1) pwm_timer_clock_hz *= 2U;
  if (pwm_timer_clock_hz != 80000000U) Error_Handler();
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 79;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 999;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
  if (HAL_TIM_PWM_Init(&htim2) != HAL_OK) Error_Handler();
  TIM_OC_InitTypeDef oc = {0};
  oc.OCMode = TIM_OCMODE_PWM1;
  oc.Pulse = 100;
  oc.OCPolarity = TIM_OCPOLARITY_HIGH;
  oc.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &oc, TIM_CHANNEL_1) != HAL_OK)
    Error_Handler();
  __HAL_TIM_ENABLE_OCxPRELOAD(&htim2, TIM_CHANNEL_1);
  /* Load PSC/ARR/CCR before enabling the output. */
  if (HAL_TIM_GenerateEvent(&htim2, TIM_EVENTSOURCE_UPDATE) != HAL_OK)
    Error_Handler();
  __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
}

static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure LSE Drive Capability
  */
  HAL_PWR_EnableBkUpAccess();
  __HAL_RCC_LSEDRIVE_CONFIG(RCC_LSEDRIVE_LOW);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_LSE|RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.LSEState = RCC_LSE_ON;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSICalibrationValue = 0;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_6;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 40;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV7;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }

  /** Enable MSI Auto calibration
  */
  HAL_RCCEx_EnableMSIPLLMode();
}
