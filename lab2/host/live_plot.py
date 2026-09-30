"""Desktop TCP receiver and rolling acceleration plot for Lab2."""
from collections import deque
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from tcp_server import parse_message


class Samples:
    """Keep bounded history; board timestamps define the horizontal axis."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.rows = deque(maxlen=2000)
        self.previous = None
        self.elapsed = 0.0
        self.count = 0
        self.gaps = 0

    def clear_history(self):
        self.rows.clear()
        self.count = 0
        self.gaps = 0

    def add(self, row):
        seq, ms, x, y, z = row
        if self.previous is not None:
            old_seq, old_ms = self.previous
            delta = (ms - old_ms) & 0xFFFFFFFF
            if ms < old_ms or (seq == 0 and old_seq != 0xFFFFFFFF):
                self.clear()  # Board restarted: begin a new time axis.
            else:
                self.elapsed = ms / 1000.0
                if seq != ((old_seq + 1) & 0xFFFFFFFF):
                    self.gaps += 1
                    self.rows.append((self.elapsed, float('nan'), float('nan'), float('nan')))
                elif delta > 1000:
                    self.rows.append((self.elapsed, float('nan'), float('nan'), float('nan')))
        self.elapsed = ms / 1000.0
        self.previous = (seq, ms)
        self.count += 1
        self.rows.append((self.elapsed, x, y, z))
        while self.rows and self.rows[0][0] < self.elapsed - 20:
            self.rows.popleft()


class Receiver(threading.Thread):
    def __init__(self, host, port, events):
        super().__init__(daemon=True)
        self.host, self.port, self.events = host, port, events
        self.stop_event = threading.Event()

    def emit(self, kind, value=None):
        while not self.stop_event.is_set():
            try:
                self.events.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                pass

    def run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                # Keep Windows' exclusive binding behavior; no SO_REUSEADDR.
                server.bind((self.host, self.port))
                server.listen(1)
                server.settimeout(0.25)
                self.emit('listening', f'{self.host}:{server.getsockname()[1]}')
                while not self.stop_event.is_set():
                    try:
                        conn, addr = server.accept()
                    except socket.timeout:
                        continue
                    self.emit('connected', f'{addr[0]}:{addr[1]}')
                    with conn:
                        conn.settimeout(0.25)
                        buffer = bytearray()
                        try:
                            while not self.stop_event.is_set():
                                try:
                                    chunk = conn.recv(4096)
                                except socket.timeout:
                                    continue
                                if not chunk:
                                    if buffer:
                                        self.emit('invalid')
                                    break
                                buffer.extend(chunk)
                                while b'\n' in buffer:
                                    line, _, rest = buffer.partition(b'\n')
                                    buffer = bytearray(rest)
                                    try:
                                        if len(line) > 256:
                                            raise ValueError('Line too long')
                                        kind, row = parse_message(line)
                                    except (ValueError, UnicodeError):
                                        self.emit('invalid')
                                    else:
                                        self.emit(kind, row)
                                if len(buffer) > 256:
                                    raise ValueError('Unterminated line too long')
                        except (OSError, ValueError) as exc:
                            self.emit('notice', str(exc))
                    self.emit('disconnected')
        except OSError as exc:
            self.emit('error', str(exc))
        finally:
            self.emit('finished')


class App:
    def __init__(self, root):
        self.root = root
        root.title('Lab2 | Wi-Fi 三軸加速度')
        root.geometry('1100x760')
        root.minsize(850, 600)
        self.events = queue.Queue(maxsize=2000)
        self.worker = None
        self.samples = Samples()
        self.last_rx = None
        self.connected = False
        self.invalid = 0
        self.dirty = True
        self.motion_count = 0
        self.motion_seen = deque(maxlen=256)
        self.motion_markers = deque(maxlen=256)
        self.marker_artists = []
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='三軸加速度即時監看', font=('Microsoft JhengHei', 20, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Wi-Fi / TCP  ·  LSM6DSL  ·  最近 20 秒  ·  單位 mg').pack(anchor='w', pady=(2, 12))
        controls = ttk.Frame(outer)
        controls.pack(fill='x')
        self.host = tk.StringVar(value='0.0.0.0')
        self.port = tk.StringVar(value='8002')
        ttk.Label(controls, text='監聽位址').pack(side='left')
        self.host_entry = ttk.Entry(controls, textvariable=self.host, width=16)
        self.host_entry.pack(side='left', padx=(6, 12))
        ttk.Label(controls, text='Port').pack(side='left')
        self.port_entry = ttk.Entry(controls, textvariable=self.port, width=7)
        self.port_entry.pack(side='left', padx=6)
        self.start_button = ttk.Button(controls, text='開始接收', command=self.start)
        self.start_button.pack(side='left', padx=6)
        self.stop_button = ttk.Button(controls, text='停止接收', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Button(controls, text='清除曲線', command=self.clear).pack(side='right')
        self.status = tk.StringVar(value='尚未開始。請先關閉舊的文字接收程式，再按「開始接收」。')
        ttk.Label(outer, textvariable=self.status, wraplength=1000).pack(anchor='w', pady=10)
        self.values = []
        cards = ttk.Frame(outer)
        cards.pack(fill='x')
        for axis, color in zip('XYZ', ('#2563eb', '#d97706', '#15803d')):
            box = ttk.LabelFrame(cards, text=f'{axis} 軸', padding=10)
            box.pack(side='left', fill='x', expand=True, padx=4)
            value = tk.StringVar(value='— mg')
            self.values.append(value)
            ttk.Label(box, textvariable=value, foreground=color, font=('Consolas', 22, 'bold')).pack()
        self.fig = Figure(figsize=(10, 4.4), dpi=100, layout='constrained')
        self.ax = self.fig.add_subplot()
        self.ax.set_xlabel('Board uptime (s)')
        self.ax.set_ylabel('Acceleration (mg)')
        self.ax.set_ylim(-2200, 2200)
        self.ax.set_xlim(0, 20)
        self.ax.grid(alpha=0.25)
        self.lines = [self.ax.plot([], [], label=axis, color=color, linewidth=1.6)[0]
                      for axis, color in zip('XYZ', ('#2563eb', '#d97706', '#15803d'))]
        self.ax.legend(loc='upper right', ncol=3)
        self.canvas = FigureCanvasTkAgg(self.fig, master=outer)
        self.canvas.get_tk_widget().pack(fill='both', expand=True, pady=10)
        self.motion_text = tk.StringVar(value='Significant motion：本次接收 0 次，等待硬體事件')
        ttk.Label(outer, textvariable=self.motion_text, foreground='#9a3412',
                  font=('Microsoft JhengHei', 12, 'bold'), wraplength=1000).pack(anchor='w')
        self.motion_log = tk.Listbox(outer, height=3, font=('Consolas', 10))
        self.motion_log.pack(fill='x', pady=4)
        self.details = tk.StringVar(value='等待量測資料')
        ttk.Label(outer, textvariable=self.details).pack(anchor='w')
        ttk.Label(outer, text='0.0.0.0 代表監聽本機所有 IPv4 介面；板子的 RemoteIP 仍須指向電腦的 Wi-Fi IPv4。', wraplength=1000).pack(anchor='w', pady=(6, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(100, self.tick)

    def clear(self):
        self.samples.clear_history()
        self.motion_markers.clear()
        self.last_rx = None
        self.invalid = 0
        for value in self.values:
            value.set('— mg')
        self.details.set('等待新的量測資料')
        self.dirty = True

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
            socket.inet_pton(socket.AF_INET, self.host.get().strip())
        except (ValueError, OSError):
            self.status.set('請輸入有效的 IPv4 位址與 1–65535 的 Port。')
            return
        self.clear()
        self.motion_count = 0
        self.motion_seen.clear()
        self.motion_log.delete(0, 'end')
        self.motion_text.set('Significant motion：本次接收 0 次，等待硬體事件')
        self.connected = False
        self.events = queue.Queue(maxsize=2000)
        self.worker = Receiver(self.host.get().strip(), port, self.events)
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.host_entry.config(state='disabled')
        self.port_entry.config(state='disabled')
        self.status.set('正在啟動接收…')
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
        self.connected = False
        self.status.set('正在停止接收…')
        self.stop_button.config(state='disabled')

    def tick(self):
        for _ in range(1000):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'sample':
                if self.samples.previous and value[1] < self.samples.previous[1]:
                    self.motion_markers.clear()
                    self.motion_seen.clear()
                self.samples.add(value)
                self.last_rx = time.monotonic()
                for label, number in zip(self.values, value[2:]):
                    label.set(f'{number:+d} mg')
                self.status.set('接收中 · 三軸曲線使用板端時間')
                self.details.set(f'本段筆數 {self.samples.count}  |  序號 {value[0]}  |  板端 {value[1] / 1000:.3f} 秒  |  序號不連續 {self.samples.gaps} 次  |  格式錯誤 {self.invalid} 筆')
                self.dirty = True
            elif kind == 'motion':
                # Same event may be retried after an uncertain TCP send.
                if value not in self.motion_seen:
                    self.motion_seen.append(value)
                    self.motion_count += 1
                    event_id, ms = value
                    self.motion_markers.append((event_id, ms / 1000.0))
                    self.dirty = True
                    self.motion_text.set(f'偵測到 SIGNIFICANT MOTION！本次接收 {self.motion_count} 次 · 最新事件 #{event_id} · 板端 {ms / 1000:.3f} 秒')
                    self.motion_log.insert(0, f'{time.strftime("%H:%M:%S")} received | EVENT #{event_id} | EXTI board time {ms / 1000:.3f} s')
                    if self.motion_log.size() > 100:
                        self.motion_log.delete(100, 'end')
            elif kind == 'connected':
                self.clear()
                self.connected = True
                self.connected_at = time.monotonic()
                self.status.set(f'板子已連線：{value}，等待資料…')
            elif kind == 'listening':
                self.status.set(f'等待板子連線 · {value}')
            elif kind == 'disconnected':
                self.connected = False
                self.status.set('板子已斷線，等待重新連線；曲線保留最後讀值。')
            elif kind == 'invalid':
                self.invalid += 1
            elif kind == 'error':
                self.status.set(f'無法接收：{value}。請確認舊接收程式已關閉、位址與 Port 正確。')
            elif kind == 'notice':
                self.status.set(f'連線訊息：{value}')
        if self.connected and time.monotonic() - (self.last_rx or self.connected_at) > 3:
            self.status.set('超過 3 秒未收到新資料；可能是板子暫停或網路中斷。畫面保留最後讀值。')
        if self.worker and not self.worker.is_alive():
            if self.worker.stop_event.is_set():
                self.status.set('已停止接收。板子可能會重試連線。')
            self.worker = None
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.host_entry.config(state='normal')
            self.port_entry.config(state='normal')
        if self.dirty:
            rows = list(self.samples.rows)
            for i, line in enumerate(self.lines):
                line.set_data([r[0] for r in rows], [r[i + 1] for r in rows])
            for artist in self.marker_artists:
                artist.remove()
            self.marker_artists.clear()
            end = max(20, self.samples.elapsed,
                      max((t for _, t in self.motion_markers), default=0))
            for event_id, event_time in self.motion_markers:
                if end - 20 <= event_time <= end:
                    self.marker_artists.append(self.ax.axvline(
                        event_time, color='#9a3412', linestyle='--', alpha=0.7, linewidth=1))
                    self.marker_artists.append(self.ax.text(
                        event_time, 0.98, f' #{event_id}', transform=self.ax.get_xaxis_transform(),
                        va='top', fontsize=8, color='#9a3412'))
            self.ax.set_xlim(end - 20, end)
            self.canvas.draw_idle()
            self.dirty = False
        self.timer = self.root.after(100, self.tick)

    def close(self):
        if self.worker:
            self.worker.stop_event.set()
            self.worker.join(timeout=1)
        self.root.after_cancel(self.timer)
        self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()
