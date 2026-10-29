# Lab 6 — Timer 觸發 ADC 讀取內部溫度感測器（中斷 / DMA 雙緩衝）

以 TIM1 的 TRGO 固定頻率觸發 ADC1，取樣 STM32L475 內部溫度感測器，由 FreeRTOS task 經 UART 印出。
完成第 1 題（每筆轉換中斷）與第 2 題（助教框架，DMA circular + half / full 中斷）；選作未做。

## 實作架構

```text
第 1 題（HW6_Q1）
TIM1 1 Hz ─TRGO─▶ ADC1（溫度感測器）─EOC 中斷─▶ HAL_ADC_ConvCpltCallback()
                                                    │ 讀 DR → osThreadFlagsSet()
                                                    ▼
                                          defaultTask：換算溫度 → printf → USART1

第 2 題（HW6_Q2）
TIM1 20 Hz ─TRGO─▶ ADC1 ─每筆─▶ DMA1_CH1 ─▶ sample_buffer[256]（circular）
                                   │ 前 128 筆滿 → HT 中斷 → HAL_ADC_ConvHalfCpltCallback() ─┐
                                   │ 後 128 筆滿 → TC 中斷 → HAL_ADC_ConvCpltCallback()     ─┤ osMessageQueuePut()
                                   ▼                                                        ▼
                         DMA 繼續寫另一半                         PrintTask：印出該半 128 筆 + 平均溫度
```

- 硬體：B-L475E-IOT01A1（STM32L475VGT6）。
- 環境：macOS、STM32CubeIDE 2.2.0（編譯）、STM32CubeMX 6.18.1（設定與產生程式碼）、STM32Cube FW_L4 V1.18.2、
  FreeRTOS（CMSIS-RTOS v2）、STM32CubeProgrammer 2.23.0（燒錄）。
- 時脈：SYSCLK = HCLK = PCLK2 = 80 MHz（MSI 4 MHz → PLL ×40 ÷2），TIM1 位於 APB2，timer clock = 80 MHz。
- UART：USART1（PB6 TX / PB7 RX，接 ST-LINK 虛擬序列埠），115200 8N1。

## 檔案

| 路徑 | 說明 |
|---|---|
| `firmware/HW6_Q1/` | 第 1 題完整 CubeIDE 專案（含 `.ioc`） |
| `firmware/HW6_Q2/` | 第 2 題完整 CubeIDE 專案，助教框架位於 `Core/Src/main.c` 的 USER CODE 區塊 |
| `ta_reference/timer_trigger_adc_DMA_ver_main.c` | 助教提供的原始框架，供對照 |
| `logs/` | UART 實測輸出 |

兩個專案的程式都寫在 CubeMX 的 `USER CODE BEGIN/END` 之間，重新 Generate Code 不會被覆蓋。

## 溫度換算

STM32 出廠時在 Vref+ = 3.0 V 下量測兩點校正值，存在系統記憶體：

| 參數 | 位址 | 校正溫度 |
|---|---|---|
| TS_CAL1 | `0x1FFF75A8` | 30 °C |
| TS_CAL2 | `0x1FFF75CA` | **110 °C**（STM32L471/475/476/485/486；其他 L4 型號為 130 °C） |

依據：`Drivers/STM32L4xx_HAL_Driver/Inc/stm32l4xx_ll_adc.h` 的 `TEMPSENSOR_CAL2_TEMP`。
程式使用 LL 定義的巨集 `TEMPSENSOR_CAL1_ADDR`、`TEMPSENSOR_CAL2_TEMP` 等，不寫死數值。

先把讀值換算回 3.0 V 基準，再兩點線性內插：

```text
raw' = raw × VDDA / 3000            （板子 VDDA = 3300 mV）
T    = (T2 − T1) / (CAL2 − CAL1) × (raw' − CAL1) + T1
```

以 int64 計算，單位 0.01 °C，避免 printf 浮點（newlib-nano 預設不支援 `%f`）。
實測 raw 變動 1 約對應 0.32 °C。量的是晶片本身溫度，比室溫高數度屬正常；手指按住晶片時讀值會上升。

## 第 1 題：TIM1 觸發 ADC，每筆轉換中斷通知 task

### 觸發頻率

```text
f = TIM1 clock / ((PSC + 1) × (ARR + 1)) = 80 MHz / (8000 × 10000) = 1 Hz
```

| 設定 | 值 | 理由 |
|---|---|---|
| TIM1 Prescaler | 7999 | 80 MHz → 10 kHz（每 0.1 ms 計數一次） |
| TIM1 Counter Period (ARR) | 9999 | 數 10000 次 → 1 s 溢位一次 |
| TIM1 TRGO | Update Event | 每次溢位送一個觸發脈衝給 ADC；TIM1 本身不開中斷 |

選 1 Hz 的理由：溫度變化以秒到分鐘計，取樣過快只會量到雜訊；且每筆都經 UART 列印一行，
1 Hz 方便人眼閱讀，也遠低於 115200 baud 的頻寬上限。

### ADC1

| 設定 | 值 | 理由 |
|---|---|---|
| 通道 | Temperature Sensor Channel | 內部通道，不佔外部腳位 |
| External Trigger | Timer 1 Trigger Out event，rising edge | 由 TIM1 決定取樣時間點 |
| Continuous Conversion | Disabled | 開啟的話 ADC 會自行連續轉換，不再受 TIM1 控制 |
| Sampling Time | 640.5 cycles | ADC clock 48 MHz → 13.3 µs；溫度感測器輸出阻抗高，需要長取樣時間 |
| 中斷 | ADC1_2 IRQ，preemption priority 5 | callback 會呼叫 RTOS API |

### 中斷與 RTOS

- `HAL_ADC_ConvCpltCallback()`：只讀 `HAL_ADC_GetValue()` 並 `osThreadFlagsSet()`，不在 ISR 裡 printf。
- `defaultTask`：`osThreadFlagsWait()` 阻塞等待 → 換算溫度 → printf。等待期間不佔用 CPU。
- 啟動順序（task 內）：`HAL_ADCEx_Calibration_Start()` → `HAL_ADC_Start_IT()` → `HAL_TIM_Base_Start()`，
  ADC 先進入等待觸發狀態，TIM1 才開始送觸發。
- NVIC priority grouping 為 `NVIC_PRIORITYGROUP_4`（4 bit 全為 preemption），sub priority 不起作用。
  FreeRTOS 的 `configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY = 5`：數字 < 5 的中斷不受 RTOS 臨界區段遮蔽，
  不能呼叫 RTOS API，因此 ADC 中斷設為 5。

## 第 2 題：助教框架（DMA circular + 雙緩衝）

### 取樣頻率與時間預算

| 項目 | 值 |
|---|---|
| TIM1 | 助教設定 PSC 3999、ARR 999 → 80 MHz / (4000 × 1000) = **20 Hz** |
| ADC clock | 助教設定 `ADC_CLOCK_SYNC_PCLK_DIV4` → 80 MHz / 4 = 20 MHz |
| buffer | 256 筆 uint16，每半 128 筆 |
| 每半填滿時間 | 128 / 20 Hz = **6.4 s** |
| 列印一半所需時間 | 約 1 KB 文字 / 115200 baud ≈ 0.1 s |

列印時間遠小於 DMA 填滿另一半的時間，所以 task 讀取的那一半不會被 DMA 覆蓋。

### TODO 實作

| 助教 TODO | 實作 |
|---|---|
| 宣告 ISR 與 task 溝通用的 RTOS 物件 | `osMessageQueueId_t printQueue`，訊息為 `uint32_t`（`HALF_TOP` / `HALF_BOTTOM`） |
| `HAL_ADC_ConvHalfCpltCallback()` | `osMessageQueuePut(printQueue, HALF_TOP, 0, 0)`，ISR 中 timeout 必須為 0 |
| `HAL_ADC_ConvCpltCallback()` | `osMessageQueuePut(printQueue, HALF_BOTTOM, 0, 0)` |
| 定義接收列印事件的 task | `PrintTask()`：`osMessageQueueGet()` → 印出該半 128 筆、平均 raw 與溫度、距上一筆的 `dt` |
| init UART | CubeMX 的 `MX_USART1_UART_Init()` |
| init RTOS 物件與 task | `osMessageQueueNew(4, sizeof(uint32_t), NULL)`；task 由 CubeMX 的 defaultTask 執行 `PrintTask()` |
| `HAL_ADC_Start_DMA(...)` | `HAL_ADC_Start_DMA(&hadc1, (uint32_t *)sample_buffer, SAMPLE_BUFFER_SIZE)` |
| start RTOS scheduling | CubeMX 的 `osKernelStart()` |

使用 message queue 而不是 binary semaphore，是因為 task 需要知道「哪一半」寫滿；queue 也能排隊，不會因 task 稍慢而漏掉事件。

PrintTask 由 defaultTask 執行，而非另建 task：CubeMX 預設 `configTOTAL_HEAP_SIZE = 3000` bytes，
defaultTask（512 words = 2048 bytes stack）已佔大部分，再建一個同樣大小的 task 會因 heap 不足建立失敗。

### 對框架的修改

框架原本來自 Mbed 環境，移植到 CubeIDE + CubeMX 時做了以下修改，每處在程式中以 `[助教 Lxx]`、`[修改 ①]` 等註解標示。

**移植必須的修改**

| # | 原本 | 修改 | 原因 |
|---|---|---|---|
| ① | `HAL_NVIC_SetPriority(DMA1_Channel1_IRQn, 0, 0)` | preemption priority 改為 5 | callback 呼叫 RTOS API，優先權需 ≥ 5，否則 FreeRTOS 的 `configASSERT` 會使程式停住 |
| ④ | `NVIC_SetVector(DMA1_Channel1_IRQn, ...)` | 刪除 | Mbed 的向量表在 RAM；CubeIDE 的向量表在 Flash。startup 檔的向量表已指向同名的 `DMA1_Channel1_IRQHandler` |
| ⑥ | `hadc1`、`htim1`、`Error_Handler()`、ADC / TIM 的 MspInit / MspDeInit | 刪除 | CubeMX 已產生同名定義（重複會 link error）；CubeMX 版 MspInit 同樣啟用 ADC / TIM1 時脈 |
| — | 框架自己的 `main()` | 拆入 CubeMX `main()` 的 USER CODE 區塊 | 一個程式只能有一個 `main()`；執行順序與框架相同 |

CubeMX 端：ADC1 與 TIM1 仍啟用（讓 HAL 驅動與時脈設定被產生），但在 Project Manager → Advanced Settings 勾選
`MX_ADC1_Init`、`MX_TIM1_Init` 的「Do Not Generate Function Call」，改由框架的 `ADC1_DMA1CH1_init()`、`TIM1_Init()` 初始化；
ADC1 自身的中斷關閉，只用 DMA 中斷。編譯會出現兩個 `defined but not used` warning，為預期結果。

**依實測結果決定的修改**

先只做上述必要修改並燒錄觀察，再依結果決定是否修改：

| 項目 | 框架原本 | 實測 | 決定 |
|---|---|---|---|
| Sampling time | `ADC_SAMPLETIME_2CYCLES_5`（20 MHz 下 0.125 µs） | raw ≈ 485、T ≈ −121 °C（第 1 題同晶片 raw ≈ 950） | **改為框架註解中的 `ADC_SAMPLETIME_247CYCLES_5`**（12.4 µs） |
| ADC DMA 模式 | `DMAContinuousRequests = DISABLE`，在 DMA 中斷內 `SET_BIT(CFGR, DMACFG)` | 連續 8 輪 TOP / BOTTOM 正常輪流，dt = 6400 ms | 保留原樣 |
| DMA request | 未設定 `hdma1.Init.Request` | 全域變數初值 0 = `DMA_REQUEST_0`，即 L475 DMA1_CH1 的 ADC1 | 保留原樣，加註解說明 |

2.5 cycles 時讀值穩定落在 483~488 而非隨機跳動，表示是系統性偏低：取樣時間太短，ADC 內部取樣電容未充到輸入電壓即開始轉換。

## 執行

1. CubeIDE：File → Import → General → Existing Projects into Workspace，選 `firmware/HW6_Q1` 或 `firmware/HW6_Q2`，不勾 Copy projects into workspace。
2. Build（0 errors）。
3. 燒錄：CubeIDE Run，或以 STM32CubeProgrammer CLI：
   ```bash
   STM32_Programmer_CLI -c port=SWD -w Debug/HW6_Q2.elf -v -rst
   ```
4. 序列埠 115200 8N1（Windows 用 PuTTY 選 ST-LINK 的 COM port；macOS：`(stty 115200 raw -echo; cat) < /dev/cu.usbmodemXXXX`），按板子黑色 RESET 從頭顯示。

## 測試結果

### 第 1 題（`logs/q1_uart.log`）

```text
#298  tick=298017 ms  dt=1000 ms  raw=950  T=30.00 C
#299  tick=299017 ms  dt=1000 ms  raw=950  T=30.00 C
#300  tick=300017 ms  dt=1000 ms  raw=951  T=30.32 C
#305  tick=305017 ms  dt=1000 ms  raw=949  T=29.68 C
```

每筆間隔 1000 ms，與 TIM1 設定一致；溫度約 30 °C。

### 第 2 題（`logs/q2_v2_sampling_247.5cycles.log`）

```text
TIM1 clock 80000000 Hz / (PSC 3999 + 1) / (ARR 999 + 1) = 20 Hz
buffer 256 samples, half = 128 samples -> one print every 6400 ms

#1 [TOP half] buffer[0..127]  tick=6399 ms  dt=6399 ms
 946  947  947  947  948  948  947  947  946  947  947  947  949  947  948  948
 ...（共 8 行，每行 16 筆）
avg raw=947  T=29.03 C

#2 [BOTTOM half] buffer[128..255]  tick=12799 ms  dt=6400 ms
avg raw=947  T=29.03 C
```

TOP / BOTTOM 交替出現，間隔 6400 ms，與 128 / 20 Hz 一致；raw ≈ 947 與第 1 題相符。
第 3 輪出現一筆離群值 892（其餘 946~949），只發生一次，128 筆平均不受影響。

### Sampling time 對照

| Sampling time | 取樣時間 | 平均 raw | 溫度 |
|---|---|---|---|
| 2.5 cycles（框架原本，20 MHz） | 0.125 µs | ≈ 485 | ≈ −121 °C（不合理） |
| 247.5 cycles（20 MHz） | 12.4 µs | ≈ 947 | ≈ 29 °C |
| 640.5 cycles（第 1 題，48 MHz） | 13.3 µs | ≈ 950 | ≈ 30 °C |

## 遇到的問題

- CubeIDE 2.x 不內建 CubeMX，設定與產生程式碼要用獨立版 CubeMX，CubeIDE 只負責編譯。
- macOS 上 ST-LINK 虛擬序列埠名稱會隨 USB 插孔改變，先以 `ls /dev/cu.usbmodem*` 查詢。
- 外部修改檔案後，CubeIDE 需對專案 Refresh（F5）才會用新內容編譯。

## 參考

- 助教範例 `timer_trigger_adc_DMA_ver`（原始檔見 `ta_reference/`）
- [Egoruch/Internal-Temperature-Sensor-STM32-HAL](https://github.com/Egoruch/Internal-Temperature-Sensor-STM32-HAL/tree/main)
- [refcircuit：Get temperature from STM32 internal temperature sensor](https://refcircuit.com/articles/21-get-temperature-from-stm32-internal-temperature-sensor-simple-library.html)
- ST：RM0351 STM32L4 參考手冊（ADC、DMA、TIM 章節）；`stm32l4xx_ll_adc.h`（溫度感測器校正參數）
- FreeRTOS：`FreeRTOSConfig.h`（`configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY`、`configTOTAL_HEAP_SIZE`）
