# Lab 2 — Wi-Fi 感測器傳輸與 Significant Motion

使用 B-L475E-IOT01A1 的 LSM6DSL 讀取三軸加速度，透過 Wi-Fi/TCP 傳送到 Windows Python GUI。完成基本題與 significant motion 選作功能。

## 實作架構

```text
LSM6DSL → I²C2 → STM32 → SPI3 Wi-Fi 模組 → TCP → Python 即時曲線
   INT1 → PD11 / EXTI11 → 確認事件來源 → EVENT 訊息 → GUI 事件紀錄
```

- 硬體：B-L475E-IOT01A1 / STM32L475VGT6。
- 開發環境：STM32CubeIDE 2.2.0、STM32CubeL4 V1.18.2。
- 基底：官方 WiFi_Client_Server；保留本地依賴與相對目錄結構。
- 感測器：52 Hz、±2 g，BSP 輸出整數 mg；約每 100 ms 讀取並傳送一筆。
- PC：Python 3.12、Tkinter、Matplotlib；背景執行緒接收，主執行緒更新畫面。

## 匯入與執行

1. 完整下載本資料夾，保留目錄結構。
2. CubeIDE：File → Import → General → Existing Projects into Workspace，選取
   `firmware/Projects/B-L475E-IOT01A/Applications/WiFi/WiFi_Client_Server/STM32CubeIDE`。
   匯入 `Lab2_WiFi`，不要勾選 Copy projects into workspace。
3. 在範例的 `Inc` 目錄，將 `wifi_config.example.h` 複製為 `wifi_config_local.h`，填入 SSID 與密碼。
   本機設定檔被 Git 忽略，不會隨儲存庫上傳。使用 2.4 GHz、WPA2-PSK 熱點。
4. 修改 `Src/main.c` 的 RemoteIP 為電腦在該網路上的 IPv4；port 預設 8002。
5. Windows 安裝含 Tkinter 的 Python 3.12，在 `host` 目錄建立環境：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

6. 雙擊 `host/start_gui.cmd`，保留監聽 `0.0.0.0:8002`，按「開始接收」。必要時允許接收程式通過 Windows 防火牆。
7. Build、Debug 燒錄板子，再 Resume。可用 PuTTY 查看 115200 / 8N1 / 無流量控制的 ST-LINK COM port。

`0.0.0.0` 是接收端監聽設定，不能作為板子的目的 IP。GUI 與 `start_server.cmd` 文字接收器不能同時占用 8002。若使用文字接收器，可透過 `tcp_server.py --host <電腦IP>` 指定地址。

## 資料格式與 GUI

```text
DATA,序號,板端時間ms,X_mg,Y_mg,Z_mg
EVENT,事件編號,EXTI時間ms,SIGNIFICANT_MOTION
```

每行以 LF 結束。接收端處理 TCP 分段、合併、錯誤格式與重新連線。
GUI 顯示最近 20 秒三軸曲線、最新數值、連線狀態、序號不連續次數及事件紀錄。
橫軸和事件統一用板端時間（秒）：71317 ms 顯示為 71.317 s；事件以棕色虛線標示。
清除曲線不將板端時間歸零；重新連線不跨缺口補畫。時間倒退（重啟或約 49.7 天 tick 回捲）開啟新曲線段。

## 選作：Significant Motion

依 AN5040 §6.2，在現有 BSP SENSOR_IO 介面上擴充設定；沒有使用軟體加速度門檻取代硬體演算法。

- Bank A SM_THS=8，保留計步去抖設定。
- CTRL10_C 啟用 FUNC_EN、SIGN_MOTION_EN，INT1_CTRL 導向 INT1。
- INT1 使用 active-high / push-pull / latched，PD11 上升緣觸發 EXTI11。
- ISR 只記錄通知與 HAL tick；主迴圈讀 FUNC_SRC1，確認 bit 6 才傳事件。讀取同時清除感測器鎖存，中斷入口另外清除 MCU EXTI pending。
- Wi-Fi 的 EXTI1 處理保留；所有 I²C、文字列印及網路操作都不在感測器 ISR 內執行。

啟動時 PuTTY 應顯示 `MOTION READY`；真實事件確認後顯示 `MOTION EXTI confirmed`。
GUI 顯示接收事件次數與時間。門檻與晶片辨識的步伐有關，並非翻面或搖八下必定觸發。

## 主要修改檔案

| 檔案（相對 WiFi_Client_Server） | 用途 |
| --- | --- |
| Src/main.c | 感測器初始化、TCP 連線／重試、DATA 與 EVENT 傳送 |
| Src/stm32l4xx_it.c | EXTI11 的中斷入口 |
| STM32CubeIDE/Application/User/significant_motion.c | BSP 擴充、暫存器讀回驗證與事件確認 |
| Inc/significant_motion.h | 動作事件介面 |
| Inc/wifi_config.example.h | 不含真實密碼的設定範本 |

電腦端 `host/live_plot.py` 為 GUI；`tcp_server.py` 提供共用解析與文字接收；`test_live_plot.py` 為自動測試。

## 驗證結果

使用者已在實體板子確認：TCP 文字通訊、序列埠加速度讀取、翻面時 Z 軸正負反轉、Wi-Fi 數值傳輸、GUI 三軸曲線與多次 significant motion 事件。後續時間顯示微調亦回報正常。
韌體編譯通過，0 errors / 0 warnings。Python 測試涵蓋訊息分段／合併、錯誤訊息、重連、連接埠釋放、時間重置及清除曲線。

```powershell
# 在 host 目錄執行
.venv\Scripts\python.exe -m unittest test_live_plot -v
```

## 限制與搬移

- 每秒約 10 筆是展示用取樣，未使用 FIFO，未保留每個 52 Hz 樣本；網路等待會影響間隔。
- 硬體鎖存可能合併等待處理期間的多次動作，尤其離線時。
- 傳送失敗保留一筆確認事件供重試；沒有主機 ACK、持久儲存或跨重啟 exactly-once 保證。
- GUI 的事件 ID／時間去重範圍有限；事件次數不是步數。協定沒有 boot ID，無法完美識別所有離線重啟情境。
- 換筆電需重建 Python 環境、更新板子 RemoteIP 並重燒，確認 COM port 與防火牆；不要複製 `.venv`。

## 參考與第三方程式

- ST STM32CubeL4 V1.18.2 WiFi_Client_Server 範例與隨附 HAL / CMSIS / BSP。
- [LSM6DSL datasheet](https://www.st.com/resource/en/datasheet/lsm6dsl.pdf)
- [AN5040](https://www.st.com/resource/en/application_note/dm00402563-lsm6dsl-always-on-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf)

第三方程式保留其原有著作權及授權；請依各目錄授權檔與來源檔標頭使用。本專案不將第三方程式重新授權。
