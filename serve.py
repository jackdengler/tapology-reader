#!/usr/bin/env python3
"""Simple HTTP server that reads port from PORT env var."""
import http.server
import os
import functools

port = int(os.environ.get("PORT", "8080"))
directory = os.path.join(os.path.dirname(__file__), "docs")

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
server = http.server.HTTPServer(("", port), handler)
print(f"Serving {directory} on port {port}")
server.serve_forever()
