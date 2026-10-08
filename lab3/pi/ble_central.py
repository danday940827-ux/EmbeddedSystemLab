#!/usr/bin/env python3
"""
HW3 — BLE Central on Raspberry Pi (bluepy)

流程：掃描 → 連線手機上的 GATT server → 列出所有 service / characteristic /
descriptor → 對指定 characteristic 的 CCCD (0x2902) 直接寫入 0x0002（indication）
→ 讀回確認 → 接收手機送來的 indication → 結束前把 CCCD 寫回 0x0000。

為什麼用 bluepy 而不是 bleak：
  bleak 走 BlueZ 的 D-Bus API，而 bluetoothd 明確禁止直接寫 CCCD
  （src/gatt-client.c: descriptor_write_value 回傳 "Write not permitted"），
  只能透過 StartNotify 間接設定，而且當 characteristic 同時支援 notify 與
  indicate 時 BlueZ 一律選 0x0001（src/shared/gatt-client.c:
  notify_data_write_ccc）。bluepy 用自己的 bluepy-helper 直接送 ATT Write
  Request，所以能把任意值寫進 CCCD handle，最適合示範 CCCD 設定。

用法（在 Pi 上）：
  python3 ble_central.py                       # 掃描並互動選擇裝置
  python3 ble_central.py --name Xiaomi --cccd 1  # 依名稱篩選、改寫 0x0001
  python3 ble_central.py --service 0e5a1ab3 --cccd 2 --listen 300 --keep
  python3 ble_central.py --addr AA:BB:.. --addr-type random --cccd 2
"""

import argparse
import struct
import sys
import time

from bluepy import btle
from bluepy.btle import (
    ADDR_TYPE_PUBLIC,
    ADDR_TYPE_RANDOM,
    BTLEException,
    DefaultDelegate,
    Peripheral,
    Scanner,
    UUID,
)

CCCD_UUID = UUID(0x2902)
CCCD_NAMES = {0: "disabled", 1: "notification", 2: "indication", 3: "notification+indication"}

# AD type 代碼（Bluetooth Assigned Numbers）
AD_SHORT_NAME = 0x08
AD_COMPLETE_NAME = 0x09


def ts():
    return time.strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


def cccd_str(raw):
    """CCCD 是 2 bytes little-endian：bit0 = notification, bit1 = indication"""
    if raw is None or len(raw) < 2:
        return repr(raw)
    v = struct.unpack("<H", raw[:2])[0]
    return f"0x{v:04X} ({CCCD_NAMES.get(v, 'reserved bits set')}) raw={raw.hex(' ')}"


# ---------------------------------------------------------------- delegates
def adv_name(dev):
    return dev.getValueText(AD_COMPLETE_NAME) or dev.getValueText(AD_SHORT_NAME) or ""


def adv_matches(dev, name_filter, service_filter):
    """名稱 / 廣播中的 service UUID 部分比對（不分大小寫）"""
    if name_filter and name_filter.lower() not in adv_name(dev).lower():
        return False
    if service_filter:
        blob = " ".join(str(v).lower() for _, _, v in dev.getScanData())
        if service_filter.lower() not in blob:
            return False
    return True


class ScanPrinter(DefaultDelegate):
    """教室裡一次會掃到上百個裝置，所以有篩選條件時只印符合的那幾個"""

    def __init__(self, name_filter, service_filter):
        super().__init__()
        self.name_filter, self.service_filter = name_filter, service_filter
        self.verbose = not (name_filter or service_filter)
        self.shown = set()

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if dev.addr in self.shown:
            return
        # 名稱 / UUID 可能在 scan response 才到，所以 isNewData 時也要再比一次
        if self.verbose or adv_matches(dev, self.name_filter, self.service_filter):
            self.shown.add(dev.addr)
            log(f"found {dev.addr} ({dev.addrType}) RSSI={dev.rssi} {adv_name(dev)}"
                + ("" if self.verbose else "  <-- match"))


class NotifyPrinter(DefaultDelegate):
    """bluepy 收到 notification 或 indication 都會呼叫 handleNotification；
    indication 的 Handle Value Confirmation 由 bluepy-helper 自動回覆。"""

    def __init__(self, handle_names):
        super().__init__()
        self.handle_names = handle_names
        self.count = 0

    def handleNotification(self, cHandle, data):
        self.count += 1
        name = self.handle_names.get(cHandle, "?")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        log(f"<< #{self.count} handle=0x{cHandle:04X} [{name}] hex={data.hex(' ')}"
            + (f' text="{text}"' if text.isprintable() and text else ""))


# ---------------------------------------------------------------- steps
def scan(seconds, name_filter, service_filter):
    log(f"scanning {seconds:.0f}s ...")
    devices = Scanner().withDelegate(ScanPrinter(name_filter, service_filter)).scan(seconds)
    matches = []
    for d in devices:
        if not adv_matches(d, name_filter, service_filter):
            continue
        if not name_filter and not service_filter and not d.connectable:
            continue
        matches.append((d, adv_name(d)))
    matches.sort(key=lambda m: m[0].rssi, reverse=True)
    log(f"scan done: {len(devices)} devices seen, {len(matches)} matched")
    return matches


def choose(matches):
    if not matches:
        log("沒有符合條件的裝置。手機的 GATT server 有開始廣播嗎？")
        sys.exit(1)
    if len(matches) == 1:
        return matches[0][0]
    print("\n可連線的裝置：")
    for i, (d, name) in enumerate(matches):
        print(f"  [{i}] {d.addr} ({d.addrType}) RSSI={d.rssi:4d}  {name}")
    idx = int(input("選擇編號 > "))
    return matches[idx][0]


SIG_BASE = "-0000-1000-8000-00805f9b34fb"


def is_sig_service(svc):
    """Bluetooth SIG 定義的 16-bit service（0x1800 GAP、0x1801 GATT、LE Audio 0x184x...）"""
    return str(svc.uuid).lower().endswith(SIG_BASE)


def dump_gatt(p, focus):
    """列出 GATT 資料庫，回傳 handle -> 名稱 的對照表。
    Android 手機本身就有一堆系統 service（GATT、LE Audio、廠商自訂），逐一查 descriptor
    在 Pi 3 上要將近一分鐘，所以有 --service 時只展開符合的那個 service。"""
    names = {}
    log("discovering services ...")
    for svc in p.getServices():
        header = (f"Service {svc.uuid}  ({svc.uuid.getCommonName()})  "
                  f"handles 0x{svc.hndStart:04X}-0x{svc.hndEnd:04X}")
        if focus and focus.lower() not in str(svc.uuid).lower():
            print(header + "  [skipped]")
            continue
        print("\n" + header)
        for ch in svc.getCharacteristics():
            names[ch.getHandle()] = ch.uuid.getCommonName()
            print(f"  Char {ch.uuid}  value handle=0x{ch.getHandle():04X}  "
                  f"props=[{ch.propertiesToString().strip()}]")
            if ch.getHandle() >= svc.hndEnd:
                continue  # 這個 characteristic 是 service 的最後一個 handle，沒有 descriptor
            try:
                for desc in ch.getDescriptors(hndEnd=svc.hndEnd):
                    if desc.handle == ch.getHandle():
                        continue
                    print(f"    Desc {desc.uuid}  handle=0x{desc.handle:04X}  "
                          f"({desc.uuid.getCommonName()})")
            except BTLEException as e:
                print(f"    (descriptor discovery failed: {e})")
    print()
    return names


def pick_characteristic(p, char_uuid, focus):
    if char_uuid:
        chars = p.getCharacteristics(uuid=UUID(char_uuid))
        if not chars:
            log(f"找不到 characteristic {char_uuid}")
            sys.exit(1)
        return chars[0]
    # 只在目標 service 裡找；沒指定 --service 時跳過 SIG 標準 service，
    # 否則會選到 Android 自己的 Service Changed (0x2A05, indicate)
    if focus:
        svcs = [s for s in p.getServices() if focus.lower() in str(s.uuid).lower()]
    else:
        svcs = [s for s in p.getServices() if not is_sig_service(s)]
    chars = [c for s in svcs for c in s.getCharacteristics()]
    for mask in (0x20, 0x10):  # Assigned Numbers: 0x20 = Indicate, 0x10 = Notify
        for ch in chars:
            if ch.properties & mask:
                return ch
    log("目標 service 裡沒有任何 characteristic 支援 notify / indicate")
    sys.exit(1)


def find_cccd(p, ch):
    svc_end = 0xFFFF
    for svc in p.getServices():
        if svc.hndStart <= ch.getHandle() <= svc.hndEnd:
            svc_end = svc.hndEnd
    descs = []
    if ch.getHandle() < svc_end:
        descs = ch.getDescriptors(forUUID=CCCD_UUID, hndEnd=svc_end)
    if not descs:
        log(f"characteristic {ch.uuid} 沒有 CCCD (0x2902)。手機端要記得加這個 descriptor。")
        sys.exit(1)
    return descs[0].handle


def connect(target, addr_type, retries):
    """Pi 3 的 Wi-Fi 與藍牙共用同一顆 2.4GHz 晶片，第一次連線失敗很常見，重試幾次"""
    for i in range(1, retries + 1):
        log(f"connecting to {target} ({addr_type}) ... attempt {i}/{retries}")
        try:
            return Peripheral(target, addr_type)
        except BTLEException as e:
            log(f"  failed: {e}")
            if i < retries:
                time.sleep(1.5)
    raise BTLEException(f"giving up after {retries} attempts")


def read_cccd(p, handle):
    """有些手機 App 的 GATT server 不回應 descriptor 讀取，讀不到就略過"""
    try:
        return cccd_str(p.readCharacteristic(handle))
    except BTLEException as e:
        return f"(read failed: {e}) — 以手機端 server log 為準"


def main():
    ap = argparse.ArgumentParser(description="HW3 BLE central: CCCD demo")
    ap.add_argument("--addr", help="直接連這個位址，跳過掃描")
    ap.add_argument("--addr-type", choices=["public", "random"], default="random",
                    help="Android 當 peripheral 時通常是 random（預設）")
    ap.add_argument("--name", help="依裝置名稱篩選（部分比對）")
    ap.add_argument("--service", help="依廣播中的 service UUID 篩選（部分比對）")
    ap.add_argument("--scan", type=float, default=8.0, help="掃描秒數")
    ap.add_argument("--char", help="目標 characteristic UUID（預設：第一個可 indicate 的）")
    ap.add_argument("--cccd", type=int, default=2, choices=[0, 1, 2, 3],
                    help="要寫入的 CCCD 值（預設 2 = indication）")
    ap.add_argument("--write", help="連線後順便寫一段文字到目標 characteristic（需有 write 屬性）")
    ap.add_argument("--listen", type=float, default=30.0, help="等待 indication 的秒數")
    ap.add_argument("--keep", action="store_true", help="結束時不要把 CCCD 寫回 0x0000")
    ap.add_argument("--retries", type=int, default=3, help="連線失敗時重試次數")
    ap.add_argument("--debug", action="store_true", help="印出 bluepy-helper 的原始訊息（含連線錯誤原因）")
    args = ap.parse_args()
    btle.Debugging = args.debug

    if args.addr:
        target = args.addr
        addr_type = ADDR_TYPE_RANDOM if args.addr_type == "random" else ADDR_TYPE_PUBLIC
    else:
        dev = choose(scan(args.scan, args.name, args.service))
        target, addr_type = dev.addr, dev.addrType

    p = connect(target, addr_type, args.retries)
    try:
        try:
            p.setMTU(185)
            log("connected (MTU 185 requested)")
        except BTLEException:
            log("connected (MTU exchange skipped)")

        names = dump_gatt(p, args.service)
        ch = pick_characteristic(p, args.char, args.service)
        cccd = find_cccd(p, ch)
        log(f"target char {ch.uuid}  value handle=0x{ch.getHandle():04X}  "
            f"props=[{ch.propertiesToString().strip()}]  CCCD handle=0x{cccd:04X}")

        log(f"CCCD before : {read_cccd(p, cccd)}")

        value = struct.pack("<H", args.cccd)
        log(f">> ATT Write Request handle=0x{cccd:04X} value={value.hex(' ')}  "
            f"(CCCD = 0x{args.cccd:04X}, {CCCD_NAMES[args.cccd]})")
        p.writeCharacteristic(cccd, value, withResponse=True)
        log("<< ATT Write Response OK")

        log(f"CCCD after  : {read_cccd(p, cccd)}")

        if args.write:
            p.writeCharacteristic(ch.getHandle(), args.write.encode(), withResponse=True)
            log(f'>> wrote "{args.write}" to handle 0x{ch.getHandle():04X}')

        delegate = NotifyPrinter(names)
        p.setDelegate(delegate)
        log(f"listening {args.listen:.0f}s — 在手機上對這個 characteristic 按 Notify/Indicate 送資料")
        deadline = time.time() + args.listen
        while time.time() < deadline:
            p.waitForNotifications(1.0)
        log(f"received {delegate.count} notification/indication(s)")

        if not args.keep:
            p.writeCharacteristic(cccd, b"\x00\x00", withResponse=True)
            log(f"CCCD restored: {read_cccd(p, cccd)}")
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        p.disconnect()
        log("disconnected")


if __name__ == "__main__":
    try:
        main()
    except BTLEException as e:
        log(f"BLE error: {e}")
        log("常見原因：沒有權限（見 README 的 setcap）、手機端沒在廣播、位址已輪換（重新掃描）")
        sys.exit(2)
