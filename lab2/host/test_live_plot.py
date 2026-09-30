import math
import queue
import socket
import time
import unittest

from live_plot import Receiver, Samples
from tcp_server import parse_message


class LiveTests(unittest.TestCase):
    def test_motion_protocol(self):
        self.assertEqual(parse_message(b'EVENT,7,2530,SIGNIFICANT_MOTION'), ('motion', (7, 2530)))
        for bad in (b'EVENT,1,2,WAKEUP', b'EVENT,-1,2,SIGNIFICANT_MOTION', b'EVENT,1,x,SIGNIFICANT_MOTION'):
            with self.assertRaises(ValueError):
                parse_message(bad)

    def test_clock_wrap_reset_and_gap(self):
        s = Samples()
        s.add((0xFFFFFFFF, 0xFFFFFFF0, 0, 0, 1000))
        s.add((0, 84, 0, 0, -1000))
        self.assertAlmostEqual(s.elapsed, 0.084)
        self.assertEqual(s.count, 1)
        s.add((2, 284, 0, 0, 1000))
        self.assertEqual(s.gaps, 1)
        self.assertTrue(math.isnan(s.rows[-2][1]))
        s.add((0, 10, 0, 0, 1000))
        self.assertEqual(s.count, 1)
        for i in range(1, 500):
            s.add((i, 10 + i * 100, 0, 0, 1000))
        self.assertLessEqual(len(s.rows), 201)

    def test_board_time_survives_clear(self):
        s = Samples()
        s.add((10, 71317, 0, 0, 1000))
        self.assertAlmostEqual(s.rows[-1][0], 71.317)
        s.clear_history()
        self.assertAlmostEqual(s.elapsed, 71.317)
        s.add((20, 73317, 0, 0, 1000))
        self.assertAlmostEqual(s.rows[-1][0], 73.317)
        s.add((0, 1200, 0, 0, 1000))
        self.assertAlmostEqual(s.elapsed, 1.2)
        self.assertEqual(len(s.rows), 1)

    def test_network_split_combined_invalid_reconnect_and_stop(self):
        events = queue.Queue(maxsize=100)
        worker = Receiver('127.0.0.1', 0, events)
        worker.start()
        def wait_for(kind):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                event, value = events.get(timeout=3)
                if event == kind:
                    return value
            self.fail(f'Missing {kind}')
        try:
            address = wait_for('listening')
            port = int(address.rsplit(':', 1)[1])
            with socket.create_connection(('127.0.0.1', port)) as conn:
                wait_for('connected')
                conn.sendall(b'DATA,0,100,1,2,')
                conn.sendall(b'1000\nBAD\nDATA,1,200,3,4,-1000\n')
                self.assertEqual(wait_for('sample'), (0, 100, 1, 2, 1000))
                wait_for('invalid')
                self.assertEqual(wait_for('sample'), (1, 200, 3, 4, -1000))
                conn.sendall(b'EVENT,7,2530,SIGNIFICANT_')
                conn.sendall(b'MOTION\nDATA,2,2600,0,0,1000\n')
                self.assertEqual(wait_for('motion'), (7, 2530))
                self.assertEqual(wait_for('sample'), (2, 2600, 0, 0, 1000))
            wait_for('disconnected')
            with socket.create_connection(('127.0.0.1', port)):
                wait_for('connected')
                worker.stop_event.set()
                worker.join(2)
                self.assertFalse(worker.is_alive())
            with socket.socket() as server:
                server.bind(('127.0.0.1', port))
        finally:
            worker.stop_event.set()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
