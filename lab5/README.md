# Lab 5 — PWM and Logic Analyzer（基本題）

目前進度：**基本題 PWM 程式已實作；板載 LED 與舊版 75% 波形已驗證。選做 Input Capture 尚未實作。**

最新原始碼為 **10% → 45% → 95%**，每兩秒切換。此版本的三組 LA 波形仍待補齊，不宣稱已有完整驗收證據。

## 應用與硬體

以 PWM 控制板載 LED1 平均亮度，透過 Logic Analyzer 觀察頻率、週期與高電位占空比。

- 開發板：ST B-L475E-IOT01A1，STM32L475VGT6。
- 開發環境：STM32CubeIDE 2.2.0；HAL，無 RTOS。原 Lab 1 RTOS 工程保留。
- 分析儀：ZEROPLUS LAP-C 162000，LAP-C Standard V3.14.14。
- GPIO：PA5 / AF1 / TIM2_CH1；板上 LED1 高電位亮。PA5 同時連至 Arduino D13（CN1 pin 6）。

## Timer 設計與計算

MSI 4 MHz → PLL M=1、N=40、R=2 → 80 MHz；AHB/APB1/APB2 除 1，本設定下 TIM2 clock = 80 MHz。

採 edge-aligned、up-counting、PWM Mode 1、active-high，PSC=79、ARR=999。

```text
counter tick = (PSC + 1) / f_TIM = 80 / 80 MHz = 1 us
f_PWM = f_TIM / ((PSC + 1) * (ARR + 1)) = 1 kHz
T_PWM = 1 ms
Duty = CCR1 / (ARR + 1)
```

| Duty 設定 | CCR1 | 理論 High | 理論 Low |
| --- | ---: | ---: | ---: |
| 10% | 100 | 100 us | 900 us |
| 45% | 450 | 450 us | 550 us |
| 95% | 950 | 950 us | 50 us |

TIM2 是 32-bit timer，但本次只使用 CNT=0..999；PWM 解析度由實際 ARR 決定，CCR 每加 1，Duty 增加 0.1 個百分點。

## 程式架構

完整實際程式位於 [firmware/PWM_L475](firmware/PWM_L475)，不是片段範例。

```text
啟動檔 → main
          ├─ HAL_Init：建立 SysTick 毫秒時間基準
          ├─ SystemClock_Config：設定時脈
          ├─ PWM_Init：啟用 GPIOA/TIM2 clock、PA5 AF1、PSC/ARR/CCR
          ├─ HAL_TIM_PWM_Start：啟動 CH1
          └─ 主迴圈：HAL_GetTick 判斷每兩秒更新 CCR
```

- [main.c](firmware/PWM_L475/Core/Src/main.c)：PWM、時脈、Duty 循環與錯誤處理。ARR/CCR preload 讓更新在週期邊界生效。
- [stm32l4xx_it.c](firmware/PWM_L475/Core/Src/stm32l4xx_it.c)：SysTick 中斷呼叫 HAL_IncTick。
- [stm32l4xx_hal_msp.c](firmware/PWM_L475/Core/Src/stm32l4xx_hal_msp.c)：底層系統初始化。
- `syscalls.c` / `sysmem.c`：C library 最小系統支援；沒有假定 printf 可直接顯示，也未設定 UART 輸出。
- `Drivers/`：HAL/CMSIS 副本及授權檔，無需依賴其他 Lab 的可變檔案。

主程式以 `__HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_1, request * 10U)` 更新 Duty；Timer 硬體負責每個 PWM 邊緣，沒有每週期 TIM2 IRQ。CPU 仍持續輪詢時間，尚未實作睡眠省電。

### Debugger 觀察與固定 Duty

| 變數／表達式 | 用途／預期 |
| --- | --- |
| pwm_ready | 啟動完成後為 1 |
| error_code | 正常為 0 |
| pwm_timer_clock_hz | 由 RCC 設定推算 80000000，不是獨立頻率量測 |
| pwm_auto_cycle | 1 自動循環；0 可手動固定 Duty |
| pwm_requested_percent | 手動模式填 10、45 或 95 |
| pwm_applied_percent | 程式最後接受並寫入的 Duty 設定 |
| htim2.Instance->PSC / ARR / CCR1 | 實際 Timer 暫存器 |

可在核心暫停時改 `pwm_auto_cycle=0` 及 `pwm_requested_percent`，恢復執行後等待至少一個週期再擷取。RAM 變數修改在重新開機後不保留。GPIO 電壓由輸出級與供電決定，Timer 控制高低時間，不直接產生中間類比電壓。

## Build 與執行

1. CubeIDE：File → Import → General → Existing Projects into Workspace。
2. 選取 `lab5/firmware/PWM_L475`，不要勾選 Copy projects into workspace。
3. 若工作區已有同名 PWM_L475，請使用另一個 workspace，避免同名衝突或誤操作。
4. Build Project，確認完整 Console 成功且產生 Debug/PWM_L475.elf。
5. 接 ST-LINK USB，Debug As → STM32 C/C++ Application，下載後 F8 執行。
6. 預期 LED1 每兩秒切換三階亮度；實際頻率與 Duty 需 LA 驗證。

**.ioc 是參考草稿，尚未透過 CubeMX 驗證重新產碼；本版本以手動維護的 C 程式為準，請勿直接 Generate Code 覆蓋。**

版本控制不包含 Debug/Release、ELF、workspace metadata、主機絕對路徑的自動產生 makefile。

## Logic Analyzer 接線與設定

先斷電並確認排針方向再接線；LA 是量測輸入，不接其 VDD 到板子電源。

| STM32 | LAP-C |
| --- | --- |
| D13 / PA5，CN1 pin 6 | A0 |
| GND，CN1 pin 7 | GND |

設定：內部取樣 1 MHz、記憶體 16K、壓縮關閉、Port A TTL threshold 1.5 V。A0 可用上升緣觸發，其他通道不參與條件。注意波形視窗倍率不等於取樣率，按擷取才會更新資料。

16K / 1 MHz 約為 16.384 ms；目前匯出資料前半為 Unknown，只有約 8.193 ms 有效資料，計算時略過未知及不完整週期。一次短擷取通常只看到一組 Duty，不能期望同時涵蓋兩秒一次的三段變化。

## 已有驗證與目前限制

- 舊版 25/50/75% 工程曾由使用者完成 Build（0 errors、0 warnings）、下載驗證及 LED 暗中亮觀察。
- Debugger 曾讀到 clock=80000000、PSC=79、ARR=999、CCR1=750。
- 重新接線後，舊版 75% CSV 的 7 個完整週期：T=1000..1001 us、High=750..751 us、Duty 約 74.925..75.025%。時間換算依當時畫面的 1 MHz 設定；CSV 本身只提供取樣索引。
- [原始 CSV](measurements/PWM_75pct_previous_version.csv) 與 [逐週期計算](measurements/PWM_75pct_analysis.json) 保留。這是**舊版 75% 證據，不是最新 10/45/95% 的三組量測**。
- 先前接線狀態曾量到異常窄脈衝，重接後改善；未確認具體接錯位置，不能把錯誤數據列為正常驗收。
- 最新 10/45/95% 原始碼已修改，尚未收到本版本完整 Build、下載及三組 CSV 驗證結果。

### 待完成

- [ ] 最新版重新 Build / Flash，確認 LED 三階切換。
- [ ] 各自保存 10%、45%、95% 的 LA 截圖、原生檔與 CSV。
- [ ] 整理理論與實測比較，討論取樣量化、時鐘誤差與接線問題。
- [ ] 基本題 Demo / 報告。

選做 1(a) Input Capture 尚未實作；未做 complementary PWM 1(b)。後續若加入 Capture，需另行核對 GPIO、接線、計數溢位及逾時處理。

## 參考資料

- 課堂講義：STM32 timer and PWM-L4.pdf。
- [ST STM32L4 Timer 教材](https://www.st.com/resource/en/product_training/STM32L4_WDG_TIMERS_GPTIM.pdf)。
- [ST UM2153 板卡手冊](https://www.st.com/resource/en/user_manual/dm00347848-discovery-kit-for-iot-node-multichannel-communication-with-stm32l4-stmicroelectronics.pdf)。
- [ST Input Capture 教學（後續選做參考）](https://community.st.com/t5/stm32-mcus/how-to-use-the-input-capture-feature/ta-p/704161)。
- [PWM 入門](https://en.wikipedia.org/wiki/Pulse-width_modulation)。
