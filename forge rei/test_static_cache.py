"""Static files: gzip + ETag + revalidate (the phone app loads ~3.7 MB of scripts on every open).

Real connector.Handler over real HTTP. Read-only; nothing leaves the machine.
Run: python3 test_static_cache.py
"""
import gzip
import http.client
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("FORGE_MARCUS", "0")
import connector  # noqa: E402

HERE = Path(__file__).resolve().parent
srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def get(path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), body)
    c.close()
    return out


def test_gzip_and_etag_on_text():
    want = (HERE / "mobile" / "mobile.css").read_bytes()
    st, h, body = get("/mobile/mobile.css", {"Accept-Encoding": "gzip"})
    assert st == 200 and h.get("content-encoding") == "gzip", (st, h)
    assert gzip.decompress(body) == want and len(body) < len(want) // 2
    assert h["etag"] and h["cache-control"] == "no-cache" and "accept-encoding" in h["vary"].lower()
    st, h2, body = get("/mobile/mobile.css")                      # no Accept-Encoding -> raw
    assert st == 200 and "content-encoding" not in h2 and body == want
    assert h2["etag"] == h["etag"]


def test_revalidate_returns_304_with_no_body():
    _, h, _ = get("/mobile/index.html", {"Accept-Encoding": "gzip"})
    st, h2, body = get("/mobile/index.html", {"If-None-Match": h["etag"], "Accept-Encoding": "gzip"})
    assert st == 304 and body == b"" and h2["etag"] == h["etag"], (st, h2)
    st, _, body = get("/mobile/index.html", {"If-None-Match": '"stale"'})
    assert st == 200 and body.startswith(b"<!DOCTYPE html>")


def test_images_are_not_gzipped_and_unknown_still_404():
    st, h, body = get("/assets/pwa-icon-180.png", {"Accept-Encoding": "gzip"})
    assert st == 200 and "content-encoding" not in h and body[:4] == b"\x89PNG"
    assert get("/deploy/valjsx.js")[0] == 404 and get("/nope.txt")[0] == 404
    assert get("/m/")[0] == 200                                     # the short URL still serves the app


def test_vendored_babel_sri_unaffected():
    # SRI hashes the DECODED bytes, so compressing must not change what the browser sees.
    want = (HERE / "assets" / "vendor" / "babel.min.js").read_bytes()
    st, h, body = get("/assets/vendor/babel.min.js", {"Accept-Encoding": "gzip"})
    assert st == 200 and h.get("content-encoding") == "gzip" and gzip.decompress(body) == want
    assert len(body) < len(want) // 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("all OK")
