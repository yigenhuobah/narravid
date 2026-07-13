"""Shared helpers for narravid max tests (no pytest)."""
from __future__ import annotations

import base64
import io
import json
import math
import struct
import sys
import tempfile
import threading
import wave
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import video_auto  # noqa: E402
import webui  # noqa: E402


# ── tiny assets ──────────────────────────────────────────────────

def write_silence_wav(path: Path, duration_sec: float = 0.5, rate: int = 24000):
    n = max(1, int(rate * duration_sec))
    with wave.open(str(path), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b'\x00\x00' * n)
    return path


def write_tone_wav(path: Path, duration_sec: float = 1.0, freq: float = 440.0, rate: int = 24000):
    n = max(1, int(rate * duration_sec))
    frames = bytearray()
    for i in range(n):
        t = i / rate
        val = int(0.2 * 32767 * math.sin(2 * math.pi * freq * t))
        frames += struct.pack('<h', max(-32768, min(32767, val)))
    with wave.open(str(path), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))
    return path


def write_tiny_png(path: Path):
    # Minimal valid 1x1 PNG
    png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    path.write_bytes(png)
    return path


def has_ffmpeg() -> bool:
    try:
        import shutil
        return bool(shutil.which(video_auto.FFMPEG) or shutil.which('ffmpeg'))
    except Exception:
        return False


# ── HTTP handler unit helpers ────────────────────────────────────

def make_handler(path: str, method: str = 'GET', body: bytes = b''):
    h = webui.H.__new__(webui.H)
    h.client_address = ('127.0.0.1', 0)
    h.server = mock.Mock()
    h.requestline = f'{method} {path} HTTP/1.1'
    h.command = method
    h.path = path
    h.request_version = 'HTTP/1.1'
    h.headers = {'Content-Length': str(len(body))}
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.close_connection = True
    h.directory = str(ROOT)
    return h


def read_response(h) -> tuple[int, object]:
    raw = h.wfile.getvalue()
    try:
        head, body = raw.split(b'\r\n\r\n', 1)
    except ValueError:
        return 0, raw
    try:
        code = int(head.split(b'\r\n', 1)[0].decode('latin1', 'ignore').split()[1])
    except Exception:
        code = 0
    ctype = b''
    for line in head.split(b'\r\n')[1:]:
        if line.lower().startswith(b'content-type:'):
            ctype = line.split(b':', 1)[1].strip().lower()
    if b'json' in ctype:
        try:
            return code, json.loads(body.decode('utf-8'))
        except Exception:
            return code, body
    return code, body


# ── live server for integration ──────────────────────────────────

@contextmanager
def live_webui(host: str = '127.0.0.1', port: int = 0):
    """Start ThreadingHTTPServer on ephemeral port; yield base_url."""
    # ensure dirs
    for d in [webui.OUT_BASE, webui.UPLOAD_DIR, webui.TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), webui.H)
    actual_port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f'http://{host}:{actual_port}'
    finally:
        httpd.shutdown()
        httpd.server_close()


def http_json(method: str, url: str, payload=None, timeout: float = 30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=timeout)
        body = resp.read()
        ctype = resp.headers.get('Content-Type', '')
        if 'json' in ctype:
            return resp.status, json.loads(body.decode('utf-8'))
        return resp.status, body
    except HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body.decode('utf-8'))
        except Exception:
            return e.code, body


def upload_bytes(base_url: str, name: str, raw: bytes, kind: str = 'image'):
    return http_json('POST', base_url + '/api/upload', {
        'name': name,
        'data': base64.b64encode(raw).decode('ascii'),
        'kind': kind,
    })
