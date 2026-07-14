"""Small standard-library client for the warm PromptDeck daemon."""

import os
import socket
import sys
import tempfile
from pathlib import Path


def socket_path() -> Path:
    """Return the per-user daemon socket path.

    Returns
    -------
    Path
        Socket path inside the Windows temporary directory or the Linux user
        runtime directory.
    """
    if sys.platform == "win32":
        runtime_directory = Path(tempfile.gettempdir())
    else:
        default_runtime = f"/run/user/{os.getuid()}"
        runtime_directory = Path(
            os.environ.get("XDG_RUNTIME_DIR", default_runtime)
        )

    return runtime_directory / "promptdeck.sock"


def request_existing_daemon(timeout: float = 0.08) -> bool:
    """Ask an already running daemon to show the PromptDeck overlay.

    Parameters
    ----------
    timeout : float, optional
        Maximum number of seconds to wait for the local daemon socket.

    Returns
    -------
    bool
        ``True`` when the daemon accepted the request; otherwise ``False``.
    """
    daemon_path = socket_path()

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(daemon_path))
            client.sendall(b"show\n")
    except OSError:
        return False

    return True
