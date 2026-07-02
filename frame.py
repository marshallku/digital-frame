#!/usr/bin/env python3
"""Ultralight digital photo frame server.

Serves images from a target directory as a fullscreen, auto-advancing slideshow
with crossfade + Ken Burns animations. Pure Python standard library, with an
optional Pillow fast-path that downscales large originals and caches the result
so low-power frame devices don't have to pull multi-megabyte files every cycle.

Usage:
    python3 frame.py "/path/to/photos" --interval 8 --port 8080
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import random
import socket
import tempfile
import threading
import time
from email.utils import formatdate
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from PIL import Image, ImageOps

    HAS_PILLOW = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_PILLOW = False

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"}
STATIC_DIR = Path(__file__).resolve().parent / "static"
SCAN_TTL_SECONDS = 30.0


class Library:
    """Ordered, thread-safe view of the images in the target directory."""

    def __init__(self, root: Path, *, recursive: bool, shuffle: bool):
        self.root = root
        self.recursive = recursive
        self.shuffle = shuffle
        self._lock = threading.Lock()
        self._paths: list[Path] = []
        self._scanned_at = 0.0
        self.rescan(force=True)

    def rescan(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._scanned_at < SCAN_TTL_SECONDS:
            return

        with self._lock:
            if not force and time.monotonic() - self._scanned_at < SCAN_TTL_SECONDS:
                return
            walker = self.root.rglob("*") if self.recursive else self.root.glob("*")
            paths = sorted(
                (p for p in walker if self._is_servable(p)),
                key=lambda p: str(p).lower(),
            )
            if self.shuffle:
                random.shuffle(paths)
            self._paths = paths
            self._scanned_at = time.monotonic()

    def _is_servable(self, path: Path) -> bool:
        """An image file whose real path stays inside the root (blocks symlink escapes)."""
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            return False
        try:
            return path.resolve().is_relative_to(self.root)
        except OSError:
            return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._paths)

    def path_at(self, index: int) -> Path | None:
        with self._lock:
            if 0 <= index < len(self._paths):
                return self._paths[index]
            return None


class ImageCache:
    """Downscales originals with Pillow and caches JPEGs keyed by (path, mtime, size)."""

    def __init__(self, max_width: int, quality: int):
        self.max_width = max_width
        self.quality = quality
        self.dir = Path(tempfile.gettempdir()) / "digital-frame-cache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def enabled(self) -> bool:
        return HAS_PILLOW and self.max_width > 0

    def _key(self, path: Path, mtime: float) -> str:
        raw = f"{path}|{mtime}|{self.max_width}|{self.quality}".encode()
        return hashlib.sha1(raw).hexdigest()

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def get(self, path: Path) -> tuple[bytes, str] | None:
        """Return (jpeg_bytes, etag) for the downscaled image, or None to fall back to raw."""
        if not self.enabled:
            return None
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        key = self._key(path, mtime)
        cache_file = self.dir / f"{key}.jpg"
        if cache_file.exists():
            try:
                return cache_file.read_bytes(), key
            except OSError:
                pass

        with self._key_lock(key):
            if cache_file.exists():
                try:
                    return cache_file.read_bytes(), key
                except OSError:
                    pass
            data = self._render(path)
            if data is None:
                return None
            tmp = cache_file.with_suffix(".tmp")
            try:
                tmp.write_bytes(data)
                tmp.replace(cache_file)
            except OSError:
                pass
            return data, key

    def _render(self, path: Path) -> bytes | None:
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                if img.width > self.max_width:
                    height = round(img.height * self.max_width / img.width)
                    img = img.resize((self.max_width, height), Image.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=self.quality, optimize=True)
                return buffer.getvalue()
        except Exception:  # noqa: BLE001 - a bad file must not kill the request
            return None


class FrameHandler(BaseHTTPRequestHandler):
    server_version = "DigitalFrame/1.0"
    protocol_version = "HTTP/1.1"

    # Injected by the server factory.
    library: Library
    cache: ImageCache
    client_config: dict

    def log_message(self, *args) -> None:  # noqa: D401 - quiet by default
        pass

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._serve_static("index.html")
        elif path == "/api/config":
            self._serve_config()
        elif path == "/api/images":
            self._serve_image_list()
        elif path.startswith("/img/"):
            self._serve_image(path[len("/img/"):])
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    # -- routes ---------------------------------------------------------------

    def _serve_config(self) -> None:
        self.library.rescan()
        payload = dict(self.client_config)
        payload["count"] = len(self.library)
        self._send_json(payload)

    def _serve_image_list(self) -> None:
        self.library.rescan()
        self._send_json({"count": len(self.library)})

    def _serve_image(self, raw_id: str) -> None:
        try:
            index = int(unquote(raw_id))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Bad image id")
            return

        path = self.library.path_at(index)
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND, "No such image")
            return

        cached = self.cache.get(path)
        if cached is not None:
            data, etag = cached
            self._send_bytes(data, "image/jpeg", etag=f'"{etag}"', immutable=True)
            return
        self._send_file(path)

    def _serve_static(self, rel: str) -> None:
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._send_file(target, cacheable=False)

    # -- response helpers -----------------------------------------------------

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", cacheable=False)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        etag: str | None = None,
        immutable: bool = False,
        cacheable: bool = True,
    ) -> None:
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
        if immutable:
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
        elif cacheable:
            self.send_header("Cache-Control", "public, max-age=3600")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, path: Path, *, cacheable: bool = True) -> None:
        try:
            stat = path.stat()
            data = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", formatdate(stat.st_mtime, usegmt=True))
        self.send_header("Cache-Control", "public, max-age=3600" if cacheable else "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def build_handler(library: Library, cache: ImageCache, client_config: dict):
    return type(
        "BoundFrameHandler",
        (FrameHandler,),
        {"library": library, "cache": cache, "client_config": client_config},
    )


def local_ip() -> str:
    """Best-effort LAN IP so the printed URL is reachable from the frame device."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ultralight digital photo frame server.")
    parser.add_argument("dir", type=Path, help="Directory containing the images to display.")
    parser.add_argument("--interval", type=float, default=8.0, help="Seconds each image is shown (default: 8).")
    parser.add_argument("--transition", type=float, default=1.5, help="Crossfade duration in seconds (default: 1.5).")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080).")
    parser.add_argument("--host", default="0.0.0.0", help="Interface to bind (default: 0.0.0.0).")
    parser.add_argument("--shuffle", action="store_true", help="Randomize the initial scan order.")
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Advance in order instead of picking the next image at random (random is the default).",
    )
    parser.add_argument("--recursive", "-r", action="store_true", help="Scan subdirectories too.")
    parser.add_argument("--no-kenburns", action="store_true", help="Disable the slow zoom/pan animation.")
    parser.add_argument(
        "--max-width",
        type=int,
        default=2560,
        help="Downscale originals to this width via Pillow, cached (0 = serve originals).",
    )
    parser.add_argument("--quality", type=int, default=85, help="JPEG quality for downscaled images (default: 85).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    root = args.dir.expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory")
        return 1

    library = Library(root, recursive=args.recursive, shuffle=args.shuffle)
    cache = ImageCache(max_width=max(args.max_width, 0), quality=args.quality)
    client_config = {
        "interval": args.interval,
        "transition": args.transition,
        "kenburns": not args.no_kenburns,
        "random": not args.sequential,
    }
    handler = build_handler(library, cache, client_config)

    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.daemon_threads = True

    count = len(library)
    downscale = "on" if cache.enabled else "off (serving originals)"
    print(f"Digital frame ready — {count} image(s) from {root}")
    print(f"Downscaling: {downscale}   Interval: {args.interval}s")
    print(f"Open  http://{local_ip()}:{args.port}  (or http://localhost:{args.port})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
