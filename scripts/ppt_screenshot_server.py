from __future__ import annotations

from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from app.main import create_app


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main() -> None:
    app = create_app()
    server = make_server("127.0.0.1", 8765, app, server_class=ThreadingWSGIServer)
    print("ComplianceRadar screenshot server running at http://127.0.0.1:8765", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
