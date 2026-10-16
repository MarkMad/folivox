"""A stand-in for ``audiocpp_server`` (audio.cpp): run as ``python native_fakes.py --config server.json``.

Serves ``/health``, ``/v1/models`` and ``/v1/audio/speech`` (a sine tone, 0.05 s per character). Behaviour through
environment variables: FAKE_LOG (file that gets one JSON line per request), FAKE_MODE = ok | crash_once | hang | error,
FAKE_MARK (a file that remembers that the crash already happened).
"""

import io
import json
import math
import os
import struct
import sys
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer


def tone(seconds: float, sr: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        n = int(seconds * sr)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(n)))
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, b'{"status":"ok"}')
        else:
            self._send(200, json.dumps({"data": [{"id": "cosyvoice3", "loaded": True}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if os.environ.get("FAKE_LOG"):
            with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), **body}) + "\n")
        mode, mark = os.environ.get("FAKE_MODE", "ok"), os.environ.get("FAKE_MARK", "")
        if mode == "crash_once" and mark and not os.path.exists(mark):
            open(mark, "w").close()
            os._exit(3)
        if mode == "hang":
            import time

            time.sleep(60)
        if mode == "error":
            return self._send(400, b'{"error":"bad reference"}')
        self._send(200, tone(len(body["input"]) * 0.05), "audio/wav")


if __name__ == "__main__":
    cfg = json.load(open(sys.argv[sys.argv.index("--config") + 1], encoding="utf-8"))
    HTTPServer((cfg["host"], cfg["port"]), H).serve_forever()
