# Lab 1 — LED blinking and RTOS API

完成basic + option A。

## 環境

- Windows 11、STM32CubeIDE 2.2.0
- B-L475E-IOT01A1（STM32L475VG）
- STM32Cube FW_L4 V1.18.2、FreeRTOS CMSIS-RTOS2
- LED2：PB14；USER 按鈕：PC13，低電位表示按下

## 功能與程式結構

- Task_1（程式中的 `defaultTask`）：短按放開後，以 1 Hz 閃爍 5 秒；長按超過 1 秒，以 10 Hz 閃爍 5 秒。
- `ButtonDetect`：每約 10 ms 讀取按鈕，使用 30 ms 防彈跳，透過訊息佇列傳送短按／長按事件。長按不必等放開，且每次按住只觸發一次。
- Task_2：TIM6 每 10 秒透過二元信號量通知，以 10 Hz 閃爍 2 秒。
- 兩個 LED Task 共用 mutex，保護整段閃爍流程；若 LED 忙碌，實際開始時間會延後。
- 按鈕佇列容量為 8 筆，滿時捨棄新事件並累計 `buttonQueueOverflowCount`。

基本題原先使用 EXTI 與二元信號量通知 Task_1；本版本為選做題 A，改用按鈕偵測 Task 與訊息佇列。

主要應用程式在 `Core/Src/main.c`；TIM6 中斷入口在 `Core/Src/stm32l4xx_it.c`。`freertos.c` 目前為產生的空白框架。


專案保留原始碼、函式庫、linker scripts 與 CubeIDE 專案設定；不包含 Debug/Release 編譯產物與個人 `.launch` 設定。

TIM6 在使用者程式區塊手動初始化，未加入 `.ioc`；目前依 80 MHz Timer clock 設定 PSC=39999、ARR=19999。FreeRTOS heap 在 `FreeRTOSConfig.h` 的使用者區塊覆寫為 8192 bytes。變更時鐘或重新產生程式後，應重新檢查這些設定。

## Demo 與驗證

以下行為已由開發板實測確認：

| 操作 | 預期行為 |
| --- | --- |
| 短按約 0.2 秒後放開 | 1 Hz 閃爍約 5 秒 |
| 按住約 1.5 秒 | 超過 1 秒後，10 Hz 閃爍約 5 秒 |
| 持續按住約 7 秒再放開 | 長按只觸發一次，放開不補送短按 |
| 不按按鈕 | 每 10 秒通知 Task_2，10 Hz 閃爍約 2 秒 |
| Task_2 執行時按鈕觸發 | 等 Task_2 完成後才執行 Task_1 |

若有其他事件排隊，閃爍會依 mutex 的取得順序延後執行。測試計時時請讓程式持續執行，不要停在中斷點。

## 第三方程式碼

Drivers 與 Middlewares 含 ST、Arm、FreeRTOS 等第三方程式碼，其授權依各檔案標頭及隨附授權檔案為準。
