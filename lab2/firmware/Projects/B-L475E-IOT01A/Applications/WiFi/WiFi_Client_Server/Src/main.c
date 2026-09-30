/**
  ******************************************************************************
  * @file    Wifi/WiFi_Client_Server/src/main.c
  * @author  MCD Application Team
  * @brief   This file provides main program functions
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2017 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "significant_motion.h"
#include "stm32l475e_iot01_accelero.h"

/* Set 1 for serial-only diagnostics, 0 for Wi-Fi sensor streaming. */
#define LAB2_SENSOR_ONLY 0
#define ACCEL_PRINT_PERIOD_MS 200U

/* Private defines -----------------------------------------------------------*/

#define TERMINAL_USE

/* Update SSID and PASSWORD with own Access point settings */
#include "wifi_config_local.h"

uint8_t RemoteIP[] = {10,86,62,1};
#define RemotePORT	8002

#define WIFI_WRITE_TIMEOUT 2000


#if defined (TERMINAL_USE)
#define TERMOUT(...)  printf(__VA_ARGS__)
#else
#define TERMOUT(...)
#endif

/* Private variables ---------------------------------------------------------*/
#if defined (TERMINAL_USE)
extern UART_HandleTypeDef hDiscoUart;
#endif /* TERMINAL_USE */


/* Private function prototypes -----------------------------------------------*/
#if defined (TERMINAL_USE)
#ifdef __GNUC__
/* With GCC, small TERMOUT (option LD Linker->Libraries->Small TERMOUT
   set to 'Yes') calls __io_putchar() */
#define PUTCHAR_PROTOTYPE int __io_putchar(int ch)
#else
#define PUTCHAR_PROTOTYPE int fputc(int ch, FILE *f)
#endif /* __GNUC__ */
#endif /* TERMINAL_USE */

static void SystemClock_Config(void);
static int SendLine(const char *line, uint16_t length)
{
  uint16_t offset = 0;
  while (offset < length)
  {
    uint16_t sent = 0, remaining = length - offset;
    if (WIFI_SendData(0, (const uint8_t *)line + offset, remaining,
                      &sent, WIFI_WRITE_TIMEOUT) != WIFI_STATUS_OK ||
        sent == 0 || sent > remaining) return 0;
    offset += sent;
  }
  return 1;
}




extern  SPI_HandleTypeDef hspi;

/* Private functions ---------------------------------------------------------*/

/**
  * @brief  Main program
  * @param  None
  * @retval None
  */
int main(void)
{
  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* Configure the system clock */
  SystemClock_Config();
  /* Configure LED2 */
  BSP_LED_Init(LED2);

#if defined (TERMINAL_USE)
  /* Initialize all configured peripherals */
  hDiscoUart.Instance = DISCOVERY_COM1;
  hDiscoUart.Init.BaudRate = 115200;
  hDiscoUart.Init.WordLength = UART_WORDLENGTH_8B;
  hDiscoUart.Init.StopBits = UART_STOPBITS_1;
  hDiscoUart.Init.Parity = UART_PARITY_NONE;
  hDiscoUart.Init.Mode = UART_MODE_TX_RX;
  hDiscoUart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  hDiscoUart.Init.OverSampling = UART_OVERSAMPLING_16;
  hDiscoUart.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  hDiscoUart.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

  BSP_COM_Init(COM1, &hDiscoUart);
#endif /* TERMINAL_USE */

  /* BSP configures LSM6DSL at 52 Hz, +/-2 g, BDU and auto-increment. */
  if (BSP_ACCELERO_Init() != ACCELERO_OK)
  {
    TERMOUT("ACCEL ERROR: LSM6DSL initialization failed. Reset to retry.\r\n");
    while (1)
    {
      BSP_LED_Toggle(LED2);
      HAL_Delay(500);
    }
  }
  HAL_Delay(100); /* Allow initial samples to settle. */
  TERMOUT("ACCEL OK: ODR=52Hz, range=+/-2g, unit=mg\r\n");
#if LAB2_SENSOR_ONLY
  TERMOUT("Sensor-only check: seq,time_ms,ax_mg,ay_mg,az_mg (5 readings/s)\r\n");
  uint32_t sample_seq = 0;
  uint32_t last_sample = HAL_GetTick();
  while (1)
  {
    uint32_t now = HAL_GetTick();
    if ((uint32_t)(now - last_sample) >= ACCEL_PRINT_PERIOD_MS)
    {
      int16_t xyz[3] = {0};
      last_sample = now;
      BSP_ACCELERO_AccGetXYZ(xyz);
      TERMOUT("ACCEL,%lu,%lu,%d,%d,%d\r\n",
              (unsigned long)sample_seq++, (unsigned long)now,
              (int)xyz[0], (int)xyz[1], (int)xyz[2]);
    }
    HAL_Delay(1);
  }
#endif

  if (!Motion_Init())
  {
    TERMOUT("MOTION ERROR: register configuration/readback failed. Reset to retry.\r\n");
    while (1) { BSP_LED_Toggle(LED2); HAL_Delay(500); }
  }
  TERMOUT("MOTION READY: threshold=8, latched INT1 -> PD11 EXTI11.\r\n");
  uint32_t event_id = 0, event_time = 0;
  uint8_t event_waiting = 0;
  TERMOUT("Wi-Fi streaming: DATA,seq,time_ms,ax_mg,ay_mg,az_mg\r\n");
  while (WIFI_Init() != WIFI_STATUS_OK)
  {
    TERMOUT("WIFI ERROR: initialization failed; retrying in 3 seconds.\r\n");
    HAL_Delay(3000);
  }
  uint32_t stream_seq = 0;
  while (1)
  {
    TERMOUT("Connecting to hotspot...\r\n");
    if (WIFI_Connect(SSID, PASSWORD, WIFI_ECN_WPA2_PSK) != WIFI_STATUS_OK)
    {
      TERMOUT("WIFI ERROR: hotspot join failed; retrying.\r\n");
      HAL_Delay(3000);
      continue;
    }
    uint8_t board_ip[4] = {0};
    if (WIFI_GetIP_Address(board_ip, sizeof(board_ip)) == WIFI_STATUS_OK)
      TERMOUT("Board IP: %u.%u.%u.%u\r\n", board_ip[0], board_ip[1], board_ip[2], board_ip[3]);
    TERMOUT("Connecting TCP: %u.%u.%u.%u:%u\r\n",
            RemoteIP[0], RemoteIP[1], RemoteIP[2], RemoteIP[3], RemotePORT);
    if (WIFI_OpenClientConnection(0, WIFI_TCP_PROTOCOL, "LAB2", RemoteIP, RemotePORT, 0) == WIFI_STATUS_OK)
    {
      BSP_LED_Off(LED2);
      TERMOUT("TCP connected. Streaming at approximately 10 samples/s.\r\n");
      uint32_t last_sample = HAL_GetTick();
      while (1)
      {
        if (!event_waiting)
        {
          int motion = Motion_Take(&event_time);
          if (motion > 0)
          {
            event_id++;
            event_waiting = 1;
            TERMOUT("MOTION EXTI confirmed: id=%lu time=%lu ms\r\n",
                    (unsigned long)event_id, (unsigned long)event_time);
          }
          else if (motion < 0)
          {
            TERMOUT("MOTION ERROR: source read failed; will retry.\r\n");
            HAL_Delay(100);
          }
        }
        if (event_waiting)
        {
          char event_line[80];
          int n = snprintf(event_line, sizeof(event_line),
                           "EVENT,%lu,%lu,SIGNIFICANT_MOTION\n",
                           (unsigned long)event_id, (unsigned long)event_time);
          if (n <= 0 || n >= (int)sizeof(event_line) || !SendLine(event_line, (uint16_t)n))
          {
            TERMOUT("MOTION TX failed; retaining event for reconnect.\r\n");
            break;
          }
          event_waiting = 0;
        }
        uint32_t now = HAL_GetTick();
        if ((uint32_t)(now - last_sample) < 100U)
        {
          HAL_Delay(1);
          continue;
        }
        last_sample = now;
        int16_t xyz[3] = {0};
        char line[96];
        BSP_ACCELERO_AccGetXYZ(xyz);
        int length = snprintf(line, sizeof(line), "DATA,%lu,%lu,%d,%d,%d\n",
                              (unsigned long)stream_seq++, (unsigned long)now,
                              (int)xyz[0], (int)xyz[1], (int)xyz[2]);
        if (length <= 0 || length >= (int)sizeof(line))
        {
          TERMOUT("ERROR: sample formatting failed.\r\n");
          continue;
        }
        if (!SendLine(line, (uint16_t)length))
        {
          TERMOUT("TCP ERROR: incomplete send; reconnecting.\r\n");
          break;
        }
        /* Keep serial diagnostics readable without printing every sample. */
        if ((stream_seq % 10U) == 0U)
          TERMOUT("TX %s\r", line);
      }
    }
    else
      TERMOUT("TCP ERROR: connection failed; start the PC receiver.\r\n");
    BSP_LED_On(LED2);
    WIFI_CloseClientConnection(0);
    WIFI_Disconnect();
    HAL_Delay(3000);
  }

}

/**
  * @brief  System Clock Configuration
  *         The system Clock is configured as follow :
  *            System Clock source            = PLL (MSI)
  *            SYSCLK(Hz)                     = 80000000
  *            HCLK(Hz)                       = 80000000
  *            AHB Prescaler                  = 1
  *            APB1 Prescaler                 = 1
  *            APB2 Prescaler                 = 1
  *            MSI Frequency(Hz)              = 4000000
  *            PLL_M                          = 1
  *            PLL_N                          = 40
  *            PLL_R                          = 2
  *            PLL_P                          = 7
  *            PLL_Q                          = 4
  *            Flash Latency(WS)              = 4
  * @param  None
  * @retval None
  */
static void SystemClock_Config(void)
{
  RCC_ClkInitTypeDef RCC_ClkInitStruct;
  RCC_OscInitTypeDef RCC_OscInitStruct;

  /* MSI is enabled after System reset, activate PLL with MSI as source */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_6;
  RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 40;
  RCC_OscInitStruct.PLL.PLLR = 2;
  RCC_OscInitStruct.PLL.PLLP = 7;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if(HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    /* Initialization Error */
    while(1);
  }

  /* Select PLL as system clock source and configure the HCLK, PCLK1 and PCLK2
     clocks dividers */
  RCC_ClkInitStruct.ClockType = (RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2);
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  if(HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    /* Initialization Error */
    while(1);
  }
}

#if defined (TERMINAL_USE)
/**
  * @brief  Retargets the C library TERMOUT function to the USART.
  * @param  None
  * @retval None
  */
PUTCHAR_PROTOTYPE
{
  /* Place your implementation of fputc here */
  /* e.g. write a character to the USART1 and Loop until the end of transmission */
  HAL_UART_Transmit(&hDiscoUart, (uint8_t *)&ch, 1, 0xFFFF);

  return ch;
}
#endif /* TERMINAL_USE */

#ifdef USE_FULL_ASSERT

/**
   * @brief Reports the name of the source file and the source line number
   * where the assert_param error has occurred.
   * @param file: pointer to the source file name
   * @param line: assert_param error line source number
   * @retval None
   */
void assert_failed(uint8_t* file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
    ex: TERMOUT("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */

}

#endif

/**
  * @brief  EXTI line detection callback.
  * @param  GPIO_Pin: Specifies the port pin connected to corresponding EXTI line.
  * @retval None
  */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  switch (GPIO_Pin)
  {
    case (GPIO_PIN_11):
    {
      Motion_NotifyIRQ();
      break;
    }
    case (GPIO_PIN_1):
    {
      SPI_WIFI_ISR();
      break;
    }
    default:
    {
      break;
    }
  }
}

void SPI3_IRQHandler(void)
{
  HAL_SPI_IRQHandler(&hspi);
}
