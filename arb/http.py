"""Minimal HTTP client on the standard library (nothing to pip install)."""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "arb-radar/1.0 (personal odds scanner; github.com)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Response:
    status: int
    data: object
    headers: dict = field(default_factory=dict)


def redact(url: str) -> str:
    return re.sub(r"(apiKey=)[^&]+", r"\1***", url)


def build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{url}?{urllib.parse.urlencode(clean, doseq=True)}"


class Fetcher:
    def __init__(self, timeout: float = 20.0, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.calls = 0

    def _open(self, request: urllib.request.Request) -> Response:
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            raw = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.decompress(raw)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            text = raw.decode("utf-8") if raw else ""
            data = json.loads(text) if text.strip() else None
            return Response(resp.status, data, headers)

    def _send(self, request: urllib.request.Request, shown_url: str) -> Response:
        last_error = None
        for attempt in range(self.retries + 1):
            self.calls += 1
            try:
                return self._open(request)
            except urllib.error.HTTPError as exc:
                last_error = HttpError(f"HTTP {exc.code} from {shown_url}", exc.code)
                if exc.code not in RETRY_STATUS:
                    raise last_error from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = HttpError(f"network error for {shown_url}: {exc}")
            except json.JSONDecodeError:
                raise HttpError(f"non-JSON response from {shown_url}") from None
            if attempt < self.retries:
                time.sleep(1.0 + 2.0 * attempt)
        raise last_error

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Response:
        full = build_url(url, params)
        request = urllib.request.Request(full, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip",
            **(headers or {}),
        })
        return self._send(request, redact(full))

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> Response:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {}),
        })
        return self._send(request, url.split("?")[0])


class FixtureFetcher:
    """Serves saved JSON files instead of calling the internet (tests and --demo).

    routes: list of (regex, filename or python object, headers). The first
    regex that matches the full URL (with sorted query string) wins.
    """

    def __init__(self, folder: Path | str, routes: list, default=None):
        self.folder = Path(folder)
        self.routes = [(re.compile(pattern), target, hdrs) for pattern, target, hdrs in routes]
        self.default = default
        self.calls = 0
        self.seen: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Response:
        self.calls += 1
        query = urllib.parse.urlencode(sorted((params or {}).items()), doseq=True)
        full = f"{url}?{query}" if query else url
        self.seen.append(redact(full))
        for pattern, target, hdrs in self.routes:
            if pattern.search(full):
                if isinstance(target, Exception):
                    raise target
                if isinstance(target, str):
                    data = json.loads((self.folder / target).read_text(encoding="utf-8"))
                else:
                    data = target
                return Response(200, data, dict(hdrs or {}))
        if self.default is not None:
            return Response(200, self.default, {})
        raise HttpError(f"HTTP 404 (no fixture) for {redact(full)}", 404)

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> Response:
        self.posts.append((url, payload))
        return Response(200, {"ok": True}, {})
