"""Serve a page and byte ranges of the original captures to a local browser.

The browser's `<video>` seeks into the source capture through HTTP 206, so a
review window is a pointer into source media: nothing is decoded or copied.
`reticle dashboard --serve` and `prototypes/e1_review.py` share this handler.

`RangeHandler` serves `/` (the page at `html_path`) and `/video/<file>` (the
file under `videos_dir`, else `<file>` read as a path). A subclass adds routes
by overriding `route_get` or `do_POST`.
"""
from __future__ import annotations

import http.server
import re
import socketserver
import urllib.parse
from pathlib import Path


class RangeHandler(http.server.BaseHTTPRequestHandler):
    html_path: Path
    videos_dir: Path

    def route_get(self, req_path: str) -> bool:
        """Serve an extra GET route; return True when handled."""
        return False

    def send_bytes(self, content: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _video_target(self, req_path: str) -> Path | None:
        fname = req_path[len("/video/"):].lstrip("/\\")
        target = self.videos_dir / fname
        if not target.is_file():
            target = Path(fname)
        return target if target.is_file() else None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        req_path = urllib.parse.unquote(parsed.path)

        if req_path in ("/", "/index.html"):
            self.send_bytes(self.html_path.read_bytes(), "text/html; charset=utf-8")
            return

        if req_path.startswith("/video/"):
            target = self._video_target(req_path)
            if target is None:
                fname = req_path[len("/video/"):].lstrip("/\\")
                self.send_error(404, f"Video not found: {fname}")
                return
            self._serve_range(target)
            return

        if self.route_get(req_path):
            return
        self.send_error(404, "Not Found")

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        req_path = urllib.parse.unquote(parsed.path)

        if req_path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(self.html_path.stat().st_size))
            self.end_headers()
            return

        if req_path.startswith("/video/"):
            target = self._video_target(req_path)
            if target is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return

        self.send_error(404)

    def _serve_range(self, file_path: Path):
        file_size = file_path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header:
            m = re.match(r"^bytes=(\d+)-(\d+)?$", range_header.strip())
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else file_size - 1
                if start < file_size and end < file_size and start <= end:
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    self._copy(file_path, start, length)
                    return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._copy(file_path, 0, file_size)

    def _copy(self, file_path: Path, start: int, length: int) -> None:
        try:
            with open(file_path, "rb") as f:
                f.seek(start)
                rem = length
                while rem > 0:
                    chunk = f.read(min(rem, 65536))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    rem -= len(chunk)
        except ConnectionError:  # the browser drops a range when it seeks
            pass

    def log_message(self, format, *args):
        pass


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def serve(handler: type[RangeHandler], port: int, what: str, open_browser: bool = False) -> int:
    """Serve `handler` on 127.0.0.1:`port` until Ctrl+C."""
    try:
        httpd = ThreadingServer(("127.0.0.1", port), handler)
    except OSError as e:
        raise SystemExit(f"Could not bind to port {port}: {e}")

    url = f"http://127.0.0.1:{port}"
    print(f"Serving {what} at: {url}")
    print(f"Streaming video from: {handler.videos_dir} (HTTP 206 Range enabled)")
    print("Press Ctrl+C to stop.")

    if open_browser:
        import webbrowser
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{what[:1].upper()}{what[1:]} server stopped.")
    finally:
        httpd.server_close()
    return 0
