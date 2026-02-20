#!/usr/bin/env python3
"""Minimal HTTP server for the canvas prototype."""
import http.server
import os
import webbrowser
import threading

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(DIR)

handler = http.server.SimpleHTTPServer if hasattr(http.server, 'SimpleHTTPServer') else http.server.SimpleHTTPRequestHandler

server = http.server.HTTPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler)

print(f"\n  Canvas Prototype running at: http://127.0.0.1:{PORT}\n")

# Auto-open browser after a short delay
def open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")

threading.Timer(0.5, open_browser).start()

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nShutting down.")
    server.shutdown()
