# EmbeddedSystemLab
homeworks
板板：B-L475E-IOT01A1。環境：Windows 11、STM32CubeIDE 2.2.0。

## Labs

- [Lab 1 — CMSIS-RTOS2 LED control](Lab1_led/README.md)：basic + option A 

- [Lab 2 — Wi-Fi 感測器與 Significant Motion](lab2/README.md)：三軸加速度、TCP 即時曲線與硬體中斷事件。

- [Lab 3 — BLE Central（Raspberry Pi + Python）](lab3/README.md)：Pi 以 bluepy 連線 Android GATT server，將 CCCD 設為 0x0002 並接收 indication。

- [Lab 4 — BLE GATT Server（STM32）與 Client（Raspberry Pi）](lab4/README.md)：STM32 以 FreeRTOS 提供加速度 GATT service，Pi 寫入取樣頻率並接收 notification；含 significant motion 選作。

- [Lab 5 — PWM and Logic Analyzer](lab5/README.md)：目前為基本題；LED PWM 調光 10/45/95%，已保存舊版 75% LA 量測，最新版三組波形待補；Input Capture 尚未實作。
