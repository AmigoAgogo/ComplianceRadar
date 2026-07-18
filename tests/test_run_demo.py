import socket
import unittest

from run_demo import find_available_port


class RunDemoTests(unittest.TestCase):
    def test_find_available_port_skips_busy_port(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]

        try:
            selected = find_available_port("127.0.0.1", busy_port)
        finally:
            sock.close()

        self.assertNotEqual(selected, busy_port)
        self.assertGreater(selected, busy_port)

