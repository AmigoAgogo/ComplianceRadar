from __future__ import annotations

import threading
import socket
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
from pathlib import Path

from app.main import create_app

try:
    import webview
except ImportError:  # pragma: no cover - covered by runtime packaging validation
    webview = None


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def find_available_port(host: str, start_port: int, max_attempts: int = 20) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"No available port found between {start_port} and {start_port + max_attempts - 1}."
    )


def main() -> None:
    host = "127.0.0.1"
    preferred_port = 8765
    port = find_available_port(host, preferred_port)
    app = create_app()
    server = make_server(host, port, app, server_class=ThreadingWSGIServer)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app_url = f"http://{host}:{port}"
    title = "ComplianceRadar"

    if webview is None:
        raise RuntimeError(
            "pywebview is required for the desktop shell. Install dependencies and rebuild the executable."
        )

    if port != preferred_port:
        print(f"Port {preferred_port} was busy. ComplianceRadar switched to {app_url}")
    else:
        print(f"ComplianceRadar is running at {app_url}")

    icon_path = Path(__file__).resolve().parent / "static" / "icon.png"
    kwargs = {
        "title": title,
        "url": app_url,
        "width": 1480,
        "height": 980,
        "min_size": (1180, 760),
        "confirm_close": False,
        "text_select": True,
    }
    if icon_path.exists():
        kwargs["icon"] = str(icon_path)

    try:
        webview.create_window(**kwargs)
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
