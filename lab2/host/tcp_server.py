"""Receive newline-delimited Lab2 acceleration samples over TCP."""
import argparse
import socket


def parse_sample(line):
    fields = line.decode('ascii').strip().split(',')
    if len(fields) != 6 or fields[0] != 'DATA':
        raise ValueError('Expected DATA,seq,time_ms,ax_mg,ay_mg,az_mg')
    seq, ms, x, y, z = map(int, fields[1:])
    if not (0 <= seq <= 0xFFFFFFFF and 0 <= ms <= 0xFFFFFFFF):
        raise ValueError('Invalid sequence or timestamp')
    if not all(-32768 <= v <= 32767 for v in (x, y, z)):
        raise ValueError('Acceleration outside int16 range')
    return seq, ms, x, y, z


def parse_message(line):
    if line.startswith(b'EVENT,'):
        fields = line.decode('ascii').strip().split(',')
        if len(fields) != 4 or fields[3] != 'SIGNIFICANT_MOTION':
            raise ValueError('Invalid motion event')
        event_id, ms = map(int, fields[1:3])
        if not all(0 <= v <= 0xFFFFFFFF for v in (event_id, ms)):
            raise ValueError('Invalid event ID or time')
        return 'motion', (event_id, ms)
    return 'sample', parse_sample(line)


def receive(conn):
    buffer = bytearray()
    previous = None
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            if buffer:
                print('Discarded incomplete final line.', flush=True)
            return
        buffer.extend(chunk)
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer = bytearray(rest)
            try:
                if len(line) > 256:
                    raise ValueError('Line too long')
                kind, value = parse_message(line)
            except (ValueError, UnicodeError) as exc:
                print(f'Invalid sample: {exc}', flush=True)
                continue
            if kind == 'motion':
                print(f'SIGNIFICANT MOTION: event={value[0]} board_time={value[1]} ms', flush=True)
                continue
            seq, ms, x, y, z = value
            if previous is not None and seq != ((previous + 1) & 0xFFFFFFFF):
                print(f'Sequence discontinuity: {previous} -> {seq}', flush=True)
            previous = seq
            print(f'DATA seq={seq:6d} t={ms:10d} ms | X={x:6d} Y={y:6d} Z={z:6d} mg', flush=True)
        if len(buffer) > 256:
            raise ValueError('Unterminated line too long; closing connection')


def serve(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((host, port))
        server.listen(1)
        print(f'Listening on {host}:{port}. Start/reset the board.', flush=True)
        while True:
            conn, addr = server.accept()
            print(f'Connected: {addr}', flush=True)
            with conn:
                try:
                    receive(conn)
                except (OSError, ValueError) as exc:
                    print(f'Connection ended: {exc}', flush=True)
            print('Waiting for a new connection...', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='10.86.62.1')
    parser.add_argument('--port', type=int, default=8002)
    args = parser.parse_args()
    try:
        serve(args.host, args.port)
    except KeyboardInterrupt:
        print('Stopped.')
    except OSError as exc:
        print(f'Cannot listen: {exc}. Check Wi-Fi IPv4 and whether another receiver is open.')
        raise SystemExit(1)
