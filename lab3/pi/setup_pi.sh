#!/usr/bin/env bash
# 在 Raspberry Pi 上執行一次：bash setup_pi.sh
set -euo pipefail

echo "== 1/4 安裝編譯 bluepy 需要的套件 =="
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential pkg-config libglib2.0-dev git

echo "== 2/4 建立 venv 並安裝 bluepy =="
python3 -m venv ~/hw3-venv
~/hw3-venv/bin/pip install --upgrade pip
~/hw3-venv/bin/pip install bluepy

echo "== 3/4 讓 bluepy-helper 不用 sudo 也能掃描 =="
HELPER=$(find ~/hw3-venv -name bluepy-helper -type f | head -1)
sudo setcap cap_net_raw,cap_net_admin+eip "$HELPER"
getcap "$HELPER"

echo "== 4/4 確認藍牙已開啟 =="
sudo rfkill unblock bluetooth || true
sleep 3   # Pi 3 的藍牙晶片走 UART，剛 unblock 立刻 power on 會回 org.bluez.Error.Busy
bluetoothctl power on || true
bluetoothctl show | grep -E "Controller|Powered|Name"

echo
echo "完成。之後執行："
echo "  source ~/hw3-venv/bin/activate"
echo "  python3 ble_central.py"
