#!/usr/bin/env python3
"""Smoke/unit tests for the digital frame server. Run: python3 test_frame.py"""

import tempfile
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image

import frame

failures = []


def check(name, condition):
    status = "ok" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        failures.append(name)


def make_images(root: Path):
    Image.new("RGB", (5472, 3648), (200, 60, 60)).save(root / "landscape.jpg")
    Image.new("RGB", (3648, 5472), (60, 60, 200)).save(root / "portrait.jpg")
    Image.new("RGB", (800, 600), (60, 200, 60)).save(root / "small.png")
    (root / "notes.txt").write_text("ignore me")


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def main():
    tmp = Path(tempfile.mkdtemp())
    make_images(tmp)

    # -- Library ----------------------------------------------------------
    lib = frame.Library(tmp, recursive=False, shuffle=False)
    check("library scans images and skips non-images", len(lib) == 3)
    check("library ordering is stable/sorted", lib.path_at(0).name == "landscape.jpg")
    check("out-of-range index returns None", lib.path_at(99) is None)

    # A symlink escaping the root (even with an image extension) must not be served.
    secret = Path(tempfile.mkdtemp()) / "secret.jpg"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(secret)
    try:
        (tmp / "escape.jpg").symlink_to(secret)
        escaped_lib = frame.Library(tmp, recursive=False, shuffle=False)
        check("symlink escaping root is excluded", len(escaped_lib) == 3)
    except OSError:
        check("symlink escaping root is excluded (skipped: no symlink support)", True)

    # -- Cache render -----------------------------------------------------
    cache = frame.ImageCache(max_width=1280, quality=85)
    result = cache.get(tmp / "landscape.jpg")
    check("cache renders a downscaled jpeg", result is not None and result[0][:2] == b"\xff\xd8")
    if result:
        rendered = Image.open(__import__("io").BytesIO(result[0]))
        check("downscaled width honors max-width", rendered.width == 1280)

    disabled = frame.ImageCache(max_width=0, quality=85)
    check("cache disabled when max-width=0", disabled.get(tmp / "landscape.jpg") is None)

    # -- Server routes ----------------------------------------------------
    client_config = {"interval": 5.0, "transition": 1.0, "kenburns": True}
    handler = frame.build_handler(lib, cache, client_config)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    status, _, body = get(f"{base}/api/config")
    import json

    cfg = json.loads(body)
    check("GET /api/config -> 200", status == 200)
    check("config reports interval + count", cfg["interval"] == 5.0 and cfg["count"] == 3)

    status, _, body = get(f"{base}/api/images")
    check("GET /api/images -> 200 with count", status == 200 and json.loads(body)["count"] == 3)

    status, headers, body = get(f"{base}/img/0")
    check("GET /img/0 -> 200 jpeg", status == 200 and body[:2] == b"\xff\xd8")
    etag = headers.get("ETag")
    check("image response carries ETag", bool(etag))

    status, _, _ = get(f"{base}/img/0", headers={"If-None-Match": etag})
    check("conditional GET -> 304", status == 304)

    status, _, _ = get(f"{base}/img/999")
    check("out-of-range image -> 404", status == 404)

    status, _, _ = get(f"{base}/img/abc")
    check("non-numeric image id -> 400", status == 400)

    status, _, body = get(f"{base}/")
    check("GET / serves index.html", status == 200 and b"<html" in body.lower())

    status, _, _ = get(f"{base}/static/../frame.py")
    check("path traversal on /static blocked", status == 404)

    status, _, _ = get(f"{base}/nope")
    check("unknown route -> 404", status == 404)

    httpd.shutdown()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        raise SystemExit(1)
    print("All tests passed.")


if __name__ == "__main__":
    main()
