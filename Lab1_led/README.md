# Lab 1 — LED blinking and RTOS API

完成 basic + option A。本版本以訊息佇列區分短按與長按，並以 mutex 協調兩個 Task 使用 LED2。

## 實作架構

| 元件 | 我們實作的行為 |
| --- | --- |
| `ButtonDetect` | 每約 10 ms 讀取按鈕，以 30 ms 穩定狀態進行防彈跳，判斷短按／長按並送入訊息佇列。 |
| Task_1（`defaultTask`） | 接收按鈕訊息；短按以 1 Hz 閃爍 5 秒，長按以 10 Hz 閃爍 5 秒。 |
| TIM6 中斷 | 每 10 秒釋放二元信號量，通知 Task_2；中斷內不執行閃爍。 |
| Task_2 | 等待計時信號量，以 10 Hz 閃爍 2 秒。 |
| LED mutex | 兩個 Task 開始閃爍前取得，整段流程結束後才釋放，避免交錯控制 LED2。 |

```text
ButtonDetect → 短按／長按訊息佇列 → Task_1 ─┐
                                         ├→ 取得 LED mutex → 閃爍 → 釋放 mutex
TIM6 中斷 → 二元信號量 → Task_2 ───────────┘
```

## 選做題 A 的處理方式

基本題原先由 EXTI 中斷釋放按鈕信號量；目前改由獨立的 `ButtonDetect` Task 偵測，因此 LED 正在閃爍時仍可判斷新的按壓。

- **短按**：放開後確認，傳送 `BUTTON_SHORT_PRESS`。
- **長按**：按住超過 1 秒即傳送 `BUTTON_LONG_PRESS`，不必等放開。
- **避免重複觸發**：`longSent` 記錄是否已送出長按；持續按住不重送，放開也不補送短按。
- **事件排隊**：佇列可保留 8 筆待處理事件；滿時捨棄新事件，並累計 `buttonQueueOverflowCount`。

兩種按鈕事件都透過同一個 mutex 使用 LED。Task_2 的 10 秒是通知週期；若另一個 Task 正在閃爍，實際開始時間會延後。

## 手動修改的檔案

| 檔案 | 修改內容 |
| --- | --- |
| [main.c](Core/Src/main.c) | Task 邏輯、按鈕辨識、訊息佇列、信號量、mutex 與 TIM6 初始化。 |
| [stm32l4xx_it.c](Core/Src/stm32l4xx_it.c) | TIM6 中斷入口，清除旗標並通知 Task_2。 |
| [main.h](Core/Inc/main.h) | 宣告中斷通知函式。 |
| [stm32l4xx_it.h](Core/Inc/stm32l4xx_it.h) | 宣告 TIM6 中斷處理函式。 |
| [FreeRTOSConfig.h](Core/Inc/FreeRTOSConfig.h) | 在使用者區塊將 RTOS heap 覆寫為 8192 bytes，供新增 Task 與佇列使用。 |

以上修改放在 `USER CODE` 區塊。TIM6 為手動初始化，未加入 `.ioc`；以目前 80 MHz Timer clock、PSC=39999、ARR=19999 產生 10 秒週期。`freertos.c` 保留產生的框架，應用邏輯集中在 `main.c`。

## 板上測試結果

以下項目皆已實測符合預期：

| 測試 | 結果 |
| --- | --- |
| 短按後放開 | 慢閃約 5 秒。 |
| 按住超過 1 秒 | 快閃約 5 秒。 |
| 持續按住約 7 秒再放開 | 長按只觸發一次，放開不追加慢閃。 |
| 不按按鈕 | 每 10 秒觸發 Task_2，快閃約 2 秒。 |
| 快閃期間觸發按鈕事件 | 等目前流程完成，再執行 Task_1。 |
| 慢閃期間 TIM6 到期 | 等慢閃完成，再執行 Task_2，兩種閃爍不交錯。 |
