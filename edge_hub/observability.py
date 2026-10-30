"""Bounded, in-memory HTTP counters with no bodies, URLs, headers or error text."""
from __future__ import annotations

import asyncio
import math
import threading
import time
import uuid
from collections import Counter, deque


class HttpMetrics:
    def __init__(self, max_routes: int = 128, window: int = 256):
        if max_routes < 1 or window < 1:
            raise ValueError("metrics limits must be positive")
        self.max_routes = max_routes
        self.window = window
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.in_flight = self.total = self.errors = self.aborted = 0
        self.exceptions = self.cancelled = 0
        self.body_bytes = self.body_messages = 0
        self.routes: dict[tuple[str, str], dict] = {}

    def begin(self):
        with self.lock:
            self.in_flight += 1

    def finish(self, method: str, route: str, status: int, seconds: float, aborted=False,
               *, exception=False, cancelled=False, body_bytes=0, body_messages=0, first_body_seconds=None):
        with self.lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.total += 1
            self.errors += int(status >= 500)
            self.aborted += int(aborted)
            self.exceptions += int(exception)
            self.cancelled += int(cancelled)
            self.body_bytes += body_bytes
            self.body_messages += body_messages
            key = (method, route)
            if key not in self.routes and len(self.routes) >= self.max_routes:
                key = ("OTHER", "overflow")
            row = self.routes.setdefault(key, {
                "count": 0, "statuses": Counter(), "aborted": 0,
                "exceptions": 0, "cancelled": 0,
                "response_body_bytes_sent": 0, "response_body_messages_sent": 0,
                "samples": deque(maxlen=self.window), "first_body_samples": deque(maxlen=self.window),
            })
            row["count"] += 1
            row["statuses"][str(status)] += 1
            row["aborted"] += int(aborted)
            row["exceptions"] += int(exception)
            row["cancelled"] += int(cancelled)
            row["response_body_bytes_sent"] += body_bytes
            row["response_body_messages_sent"] += body_messages
            row["samples"].append(max(0., seconds * 1000))
            if first_body_seconds is not None and math.isfinite(first_body_seconds):
                row['first_body_samples'].append(max(0., first_body_seconds*1000))

    def snapshot(self):
        with self.lock:
            rows = []
            for (method, route), row in sorted(self.routes.items()):
                samples = sorted(row["samples"])
                first = sorted(row['first_body_samples'])
                rows.append({
                    "method": method, "route": route, "count": row["count"],
                    "statuses": dict(row["statuses"]), "aborted": row["aborted"],
                    "exceptions": row["exceptions"], "cancelled": row["cancelled"],
                    "response_body_bytes_sent": row["response_body_bytes_sent"],
                    "response_body_messages_sent": row["response_body_messages_sent"],
                    "window_samples": len(samples),
                    "first_body_samples": len(first),
                    "first_body_p50_ms": round(first[math.ceil(len(first)*.5)-1], 3) if first else None,
                    "first_body_p95_ms": round(first[math.ceil(len(first)*.95)-1], 3) if first else None,
                    "p50_ms": round(samples[math.ceil(len(samples) * .5) - 1], 3),
                    "p95_ms": round(samples[math.ceil(len(samples) * .95) - 1], 3),
                })
            return {
                "scope": "process-local HTTP; not speech, websocket or hardware acceptance",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "total_requests": self.total, "in_flight": self.in_flight,
                "server_errors": self.errors, "aborted_requests": self.aborted,
                "exception_requests": self.exceptions, "cancelled_requests": self.cancelled,
                "response_body_bytes_sent": self.body_bytes,
                "response_body_messages_sent": self.body_messages,
                "response_body_scope": "ASGI send returned; body only including empty messages; not delivery ACK",
                "first_body_scope": "first nonempty ASGI body sent; not browser receipt, first token or audible speech",
                "route_limit": self.max_routes, "latency_window": self.window,
                "routes": rows,
            }


class MetricsMiddleware:
    def __init__(self, app, metrics: HttpMetrics):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status = 500
        completed = False
        exception = cancelled = False
        body_bytes = body_messages = 0
        first_body_seconds = None
        request_id = uuid.uuid4().hex
        self.metrics.begin()

        async def measured_send(message):
            nonlocal status, completed, body_bytes, body_messages, first_body_seconds
            body_size = len(message.get('body', b'')) if message['type'] == 'http.response.body' else 0
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)
            if message["type"] == "http.response.body":
                if body_size and first_body_seconds is None:
                    first_body_seconds = time.monotonic()-started
                body_bytes += body_size
                body_messages += 1
                if not message.get("more_body", False):
                    completed = True

        try:
            await self.app(scope, receive, measured_send)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception:
            # Handler, background-task or send failures may occur AFTER a 200
            # start/final body. Preserve status and exception propagation; retain
            # only counts, never exception types/messages or request contents.
            exception = True
            raise
        finally:
            # Only the framework's route template is retained, never the request path/query.
            template = getattr(scope.get("route"), "path", None) or "unmatched"
            method = scope.get("method", "OTHER")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                method = "OTHER"
            self.metrics.finish(method, template, status, time.monotonic() - started,
                                aborted=not completed, exception=exception, cancelled=cancelled,
                                body_bytes=body_bytes, body_messages=body_messages, first_body_seconds=first_body_seconds)
