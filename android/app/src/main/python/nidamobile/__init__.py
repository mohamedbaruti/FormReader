"""Starts the Form Reader inside the Android app.

The phone app runs the same reader as the computer (the `app` package next to this file: OpenCV,
the character models, the form editions, the rules), without Reader Training. It listens only on
the phone itself (127.0.0.1) and also serves the app's screens (the `ui` folder), which the app
shows full screen. Saved enrolments go into an SQLite database in the app's own storage.
"""
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
_started = {"port": None, "error": None}


def start(data_dir, port=8765):
    """Start the reader (once). Returns the port. Called by MainActivity on a background thread."""
    if _started["port"]:
        return _started["port"]
    os.makedirs(data_dir, exist_ok=True)
    os.environ["FORMREADER_DATA_DIR"] = data_dir        # uploads, saved records, lookup copy
    os.environ["FORMREADER_NO_TRAINING"] = "1"          # no Reader Training on the phone

    from flask import request, send_from_directory
    from werkzeug.serving import make_server
    from app.server import app

    @app.before_request
    def _screens():
        """Everything that is not /api/... is the app's screens (one page that shows them all)."""
        path = request.path
        if path.startswith("/api/"):
            return None
        name = path.lstrip("/")
        if name and os.path.isfile(os.path.join(UI_DIR, name)):
            return send_from_directory(UI_DIR, name, max_age=0)
        return send_from_directory(UI_DIR, "index.html", max_age=0)

    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _started["port"] = port
    return port


def wait_ready(port, timeout=60):
    """True once the reader answers (used before showing the screens)."""
    import urllib.request
    t = time.time()
    while time.time() - t < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.5)
    return False
