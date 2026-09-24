# Lab 1 — LED blinking and RTOS API

完成 basic + option A，用 message queue 和 mutex 控制 LED 燈。

## 實作架構

| 元件 | 功能 |
| --- | --- |
| `ButtonDetect` | 每約 10 ms 讀取按鈕，狀態穩定 30 ms 才確認變化，避免彈跳。判斷短按或長按後，將結果送進 message queue。 |
| Task_1（`defaultTask`） | 接收按鈕訊息；短按以 1 Hz 閃爍 5 秒，長按以 10 Hz 閃爍 5 秒。 |
| TIM6 中斷 | 每 10 秒釋放 binary semaphore，通知 Task_2；中斷內不執行閃爍。 |
| Task_2 | 等待 timer semaphore，以 10 Hz 閃爍 2 秒。 |
| LED mutex | 兩個 Task 開始閃爍前取得，整段流程結束後才釋放，避免交錯控制 LED2。 |

```text
ButtonDetect → 短按／長按 message queue → Task_1 ─┐
                                                 ├→ 取得 LED mutex → 閃爍 → 釋放 mutex
TIM6 中斷 → binary semaphore → Task_2 ───────────┘
```

## option A 的作法

basic 原本用 EXTI 中斷釋放 button semaphore。option A 改用 `ButtonDetect` Task 判斷短按和長按，LED 正在閃爍時也能繼續偵測按鈕。

- **短按**：放開後確認，傳送 `BUTTON_SHORT_PRESS`。
- **長按**：按住超過 1 秒就送出 `BUTTON_LONG_PRESS`，不必等放開。
- **避免重複觸發**：`longSent` 記錄是否已送出長按；持續按住不重送，放開也不補送短按。
- **事件排隊**：queue 最多存 8 筆事件；滿了就丟掉新事件，並記錄在 `buttonQueueOverflowCount`。

短按和長按都要先取得 mutex 才能控制 LED。Task_2 每 10 秒收到一次通知，如果另一個 Task 還在閃爍，就等它結束再開始。

## 手動修改的檔案

| 檔案 | 修改內容 |
| --- | --- |
| [main.c](Core/Src/main.c) | Task、按鈕判斷、message queue、semaphore、mutex 和 TIM6 初始化。 |
| [stm32l4xx_it.c](Core/Src/stm32l4xx_it.c) | TIM6 中斷入口，清除旗標並通知 Task_2。 |
| [main.h](Core/Inc/main.h) | 宣告中斷通知函式。 |
| [stm32l4xx_it.h](Core/Inc/stm32l4xx_it.h) | 宣告 TIM6 中斷處理函式。 |
| [FreeRTOSConfig.h](Core/Inc/FreeRTOSConfig.h) | 在 USER CODE 區塊把 RTOS heap 改成 8192 bytes，讓新增的 Task 和 queue 有足夠記憶體。 |

修改都放在 `USER CODE` 區塊。TIM6 直接在程式裡設定，沒有加進 `.ioc`，用 80 MHz Timer clock、PSC=39999、ARR=19999 做出 10 秒週期。主要程式寫在 `main.c`，`freertos.c` 沒有另外修改。

## 板上測試結果

以下測試都已在開發板上確認成功：

| 測試 | 結果 |
| --- | --- |
| 短按後放開 | 慢閃約 5 秒。 |
| 按住超過 1 秒 | 快閃約 5 秒。 |
| 持續按住約 7 秒再放開 | 長按只觸發一次，放開不追加慢閃。 |
| 不按按鈕 | 每 10 秒觸發 Task_2，快閃約 2 秒。 |
| 快閃期間觸發按鈕事件 | 等目前流程完成，再執行 Task_1。 |
| 慢閃期間 TIM6 到期 | 等慢閃完成，再執行 Task_2，兩種閃爍不交錯。 |
