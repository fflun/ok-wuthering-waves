"""Local, authenticated transport for the explicitly paired Chrome extension.

No browser is launched and no profile, cookie or token store is read.
"""
import json
import queue
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ChromeBridge:
    def __init__(self, port=19876):
        self.token = secrets.token_urlsafe(32)
        self.queue = queue.Queue()
        self.pending = {}
        self.lock = threading.Lock()
        self.last_seen = 0
        self.closed = False
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                # No CORS headers: website scripts cannot pair or issue commands.
                if self.headers.get('Host') != f'127.0.0.1:{bridge.port}':
                    return self.reply(403, {'error': 'Invalid host'})
                if self.path == '/connect':
                    # Extension fetches carry their own browser-controlled Origin.
                    # Ordinary webpages cannot use this automatic local handshake.
                    if not re.fullmatch(r'chrome-extension://[a-p]{32}', self.headers.get('Origin', '')):
                        return self.reply(403, {'error': 'Local Chrome extension required'})
                    return self.reply(200, {'token': bridge.token})
                auth = self.headers.get('Authorization', '')
                if not secrets.compare_digest(auth, 'Bearer ' + bridge.token):
                    return self.reply(403, {'error': 'Pairing required'})
                if self.headers.get('Host') != f'127.0.0.1:{bridge.port}':
                    return self.reply(403, {'error': 'Invalid host'})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size < 16_000_000:
                        raise ValueError('Invalid size')
                    body = json.loads(self.rfile.read(size))
                    if self.path == '/hello':
                        return self.reply(200, {})
                    if self.path == '/poll':
                        bridge.last_seen = time.monotonic()
                        command = None
                        while not bridge.queue.empty():
                            candidate = bridge.queue.get_nowait()
                            with bridge.lock:
                                valid = candidate['id'] in bridge.pending
                            if valid and candidate['expires'] > time.time():
                                command = candidate
                                break
                        return self.reply(200, {'command': command})
                    if self.path == '/result':
                        with bridge.lock:
                            target = bridge.pending.get(body.get('id'))
                            if target:
                                target['result'] = body
                                target['event'].set()
                        return self.reply(200, {})
                    return self.reply(404, {})
                except (ValueError, TypeError, queue.Empty):
                    return self.reply(400, {'error': 'Invalid request'})

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def connected(self):
        return not self.closed and time.monotonic() - self.last_seen < 3

    def request(self, op, params=None, timeout=10):
        if self.closed:
            raise RuntimeError('Chrome connection closed')
        if op not in {'metrics', 'frame', 'input', 'enter', 'focus', 'release'}:
            raise ValueError('Unsupported bridge operation')
        ident = secrets.token_hex(12)
        target = {'event': threading.Event()}
        with self.lock:
            self.pending[ident] = target
        self.queue.put(dict(id=ident, op=op, params=params or {},
                            expires=time.time() + min(timeout, 2 if op == 'input' else timeout)))
        try:
            if not target['event'].wait(timeout):
                raise TimeoutError('Chrome did not respond; input has stopped')
            result = target['result']
            if result.get('error'):
                raise RuntimeError(result['error'])
            return result.get('result')
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def close(self):
        self.closed = True
        with self.lock:
            for target in self.pending.values():
                target['result'] = {'error': 'Chrome bridge stopped'}
                target['event'].set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def game_rect(metrics):
    """Map a verified DOM rendering surface to the normalized OK-WW frame."""
    if not metrics.get('ready'):
        raise RuntimeError('Game canvas/video is not ready')
    x, y, w, h = metrics['rect']
    sw, sh = metrics['source']
    if min(w, h, sw, sh) <= 0 or abs(sw / sh - 16 / 9) > .03:
        raise RuntimeError('Unexpected game aspect ratio')
    fit = metrics['fit']
    if fit in ('contain', 'scale-down'):
        if metrics['position'] != '50% 50%':
            raise RuntimeError('Unsupported non-centered game surface')
        scale = min(w / sw, h / sh)
        if fit == 'scale-down':
            scale = min(scale, 1)
        cw, ch = sw * scale, sh * scale
        x, y, w, h = x + (w-cw)/2, y + (h-ch)/2, cw, ch
    elif abs(w / h - sw / sh) > .02:
        # Do not guess whether the SDK painted internal bars in a stretched canvas.
        raise RuntimeError('Set the game viewport to 16:9 before automated input')
    if x < -.5 or y < -.5 or x+w > metrics['viewport'][0]+.5 or y+h > metrics['viewport'][1]+.5:
        raise RuntimeError('Game surface is outside the viewport')
    return dict(x=max(0, x), y=max(0, y), width=w, height=h)


def pixel_crop(rect, viewport, image_size):
    """Convert CSS coordinates into full screenshot pixels, including HiDPI."""
    vw, vh = viewport
    iw, ih = image_size
    if min(vw, vh, iw, ih) <= 0 or abs((iw / vw) / (ih / vh) - 1) > .01:
        raise RuntimeError('Screenshot size does not match the measured viewport')
    sx, sy = iw / vw, ih / vh
    left, top = round(rect['x'] * sx), round(rect['y'] * sy)
    right = round((rect['x'] + rect['width']) * sx)
    bottom = round((rect['y'] + rect['height']) * sy)
    if not (0 <= left < right <= iw and 0 <= top < bottom <= ih):
        raise RuntimeError('Game crop is outside the screenshot')
    return left, top, right, bottom
