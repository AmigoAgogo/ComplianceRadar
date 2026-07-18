from __future__ import annotations

import threading
import time
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main() -> None:
    from playwright.sync_api import sync_playwright

    out_dir = Path("dist") / "demo_ppt_assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = create_app()
    server = make_server("127.0.0.1", 8765, app, server_class=ThreadingWSGIServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 980}, device_scale_factor=1)
            page.goto("http://127.0.0.1:8765", wait_until="networkidle", timeout=20000)
            page.screenshot(path=str(out_dir / "dashboard.png"), full_page=True)

            views = [
                ("events", "event_library.png"),
                ("sources", "source_center.png"),
                ("review", "regulatory_radar.png"),
                ("models", "model_gateway.png"),
            ]
            for view, filename in views:
                try:
                    page.locator(f'button[data-view="{view}"]').click(timeout=5000)
                    page.wait_for_timeout(900)
                    page.screenshot(path=str(out_dir / filename), full_page=True)
                except Exception:
                    continue
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=3)

    print(out_dir.resolve())


if __name__ == "__main__":
    main()
