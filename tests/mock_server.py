#!/usr/bin/env python3
"""
tests/mock_server.py
Lightweight multi-threaded local mock HTTP server for deterministic audit verification.

Provides controlled test fixtures:
  - /clean: 100% compliant website yielding 0 findings and GEO Score 100.
  - /robots.txt: Standard compliant robots.txt.
  - /sitemap.xml: Valid XML sitemap with recent lastmod dates.
  - /waf-block: Returns HTTP 403 for GPTBot user-agent.
  - /slow-timeout: Simulates upstream network latency.
  - /csr-app: Returns empty SPA mount container with heavy inline scripts.
"""

from __future__ import annotations

import time
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional, Tuple


class ThreadedTCPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockAuditHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler serving deterministic audit fixture endpoints."""

    routes: Dict[str, Tuple[int, Dict[str, str], bytes]] = {}

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress routine HTTP request logs to keep test output clean
        pass

    @classmethod
    def set_route(cls, path: str, status: int, headers: Dict[str, str], body: bytes) -> None:
        cls.routes[path] = (status, headers, body)

    @classmethod
    def reset_routes(cls, port: int) -> None:
        cls.routes.clear()
        cls.init_default_routes(port)

    @classmethod
    def init_default_routes(cls, port: int) -> None:
        base_url = f"http://127.0.0.1:{port}"

        clean_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Acme Cloud Enterprise AI Readiness</title>
  <link rel="canonical" href="{base_url}/clean">
  <meta property="article:modified_time" content="2026-08-01T00:00:00Z">
  <script type="application/ld+json">
  [
    {{
      "@context": "https://schema.org",
      "@type": "Organization",
      "name": "Acme Cloud Corp",
      "url": "{base_url}",
      "logo": "{base_url}/logo.png",
      "sameAs": [
        "https://www.wikidata.org/wiki/Q123456",
        "https://en.wikipedia.org/wiki/Acme_Corp",
        "https://twitter.com/acmecloud"
      ]
    }},
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Acme Enterprise AI Engine",
      "image": "{base_url}/product.jpg",
      "description": "High performance autonomous AI readiness auditing suite for enterprise brands.",
      "offers": {{
        "@type": "Offer",
        "price": "99.00",
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock"
      }}
    }},
    {{
      "@context": "https://schema.org",
      "@type": "FAQPage",
      "mainEntity": [
        {{
          "@type": "Question",
          "name": "What is Acme Enterprise AI Engine?",
          "acceptedAnswer": {{
            "@type": "Answer",
            "text": "It is an autonomous auditing toolkit validating AI discoverability and on-site engagement."
          }}
        }}
      ]
    }}
  ]
  </script>
</head>
<body>
  <header>
    <h1>Acme Enterprise AI Readiness & Discoverability</h1>
    <p>Acme Cloud provides industry-leading generative engine optimization and real-time on-site engagement retention solutions for Fortune 500 enterprises.</p>
  </header>

  <main>
    <section id="features">
      <h2>Autonomous Auditing Architecture</h2>
      <p>Our platform evaluates crawlability, RFC 9309 robots compliance, client-side rendering fallbacks, and Schema.org structured data extraction.</p>
    </section>

    <section id="deep-linking">
      <h2>Precision AI Citation Deep-Anchors</h2>
      <p>Semantic section IDs enable generative search models to quote exact factual claims with deep-link anchors back to authoritative sources.</p>
    </section>

    <section id="performance">
      <h2>Zero-Crash Enterprise Reliability</h2>
      <p>Thread-local session pooling and fault containment guarantee 100 percent operational uptime across massive batch benchmark workloads.</p>
    </section>
  </main>

  <footer>
    <p>&copy; 2026 Acme Cloud Corp. All rights reserved. Built for enterprise reliability.</p>
  </footer>
</body>
</html>""".encode("utf-8")

        robots_txt = f"""User-agent: *
Allow: /
Sitemap: {base_url}/sitemap.xml
""".encode("utf-8")

        sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base_url}/clean</loc>
    <lastmod>2026-08-01T00:00:00Z</lastmod>
  </url>
</urlset>""".encode("utf-8")

        cls.routes["/clean"] = (
            200,
            {
                "Content-Type": "text/html; charset=utf-8",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "Last-Modified": "Sat, 01 Aug 2026 00:00:00 GMT",
            },
            clean_html,
        )

        cls.routes["/robots.txt"] = (
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
            robots_txt,
        )

        cls.routes["/sitemap.xml"] = (
            200,
            {"Content-Type": "application/xml; charset=utf-8"},
            sitemap_xml,
        )

    def do_GET(self) -> None:
        # Check for simulated WAF block route
        if self.path == "/waf-block":
            ua = self.headers.get("User-Agent", "")
            if "GPTBot" in ua or "ClaudeBot" in ua:
                self.send_response(403)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Server", "Cloudflare")
                self.end_headers()
                self.wfile.write(b"<html><body>403 Forbidden: Blocked by Cloudflare WAF</body></html>")
                return

        # Check for simulated network timeout route
        if self.path == "/slow-timeout":
            time.sleep(2.5)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK after delay")
            return

        # Route lookup
        route_data = self.routes.get(self.path)
        if route_data is not None:
            status, headers, body = route_data
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Default 404 for unknown routes
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Not Found")


class MockServer:
    """Convenient context manager and controller for the local Mock Server."""

    def __init__(self, port: int = 0):
        self.server = ThreadedTCPServer(("127.0.0.1", port), MockAuditHandler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        MockAuditHandler.reset_routes(self.port)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> str:
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def get_url(self, path: str = "/") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def set_route(self, path: str, status: int, headers: Dict[str, str], body: bytes) -> None:
        MockAuditHandler.set_route(path, status, headers, body)

    def __enter__(self) -> MockServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
