import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from promptdeck.ipc import request_existing_daemon


class IpcTests(unittest.TestCase):
    def test_reports_when_no_daemon_is_listening(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "missing.sock"

            with patch("promptdeck.ipc.socket_path", return_value=path):
                self.assertFalse(request_existing_daemon())

    def test_sends_show_request_to_running_daemon(self):
        path = Path("/run/user/1000/promptdeck.sock")
        client = MagicMock()

        with (
            patch("promptdeck.ipc.socket_path", return_value=path),
            patch("promptdeck.ipc.socket.socket") as socket_factory,
        ):
            socket_factory.return_value.__enter__.return_value = client
            self.assertTrue(request_existing_daemon())

        client.settimeout.assert_called_once_with(0.08)
        client.connect.assert_called_once_with(str(path))
        client.sendall.assert_called_once_with(b"show\n")


if __name__ == "__main__":
    unittest.main()
