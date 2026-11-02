#!/usr/bin/env python3
"""
Mock API + static server for StegApp.

Stands in for the real Kali-utility backend so the GUI can be clicked through
end to end. Serves the static files AND the /api/* routes from one origin, so
there are no CORS concerns. Nothing here actually touches steghide/stegseek —
every response is faked with a short delay and a progress ramp.

Run:
    python mock_api.py          # http://localhost:8080
    python mock_api.py 9000     # choose a port

Then open http://localhost:8080/ in a browser.

Implemented contract (matches common.js):
    GET  /api/wordlists            -> ["rockyou.txt", ...]
    POST /api/embed    (multipart) -> file blob            (needs cover+secret)
    POST /api/extract  (multipart) -> file blob            (needs passphrase)
    POST /api/detect   (multipart) -> { job_id }  then poll
    POST /api/crack    (multipart) -> { job_id }  then poll (needs X-API-Key)
    GET  /api/jobs/{id}            -> { state, percent?, result?, passphrase?, download? }
    POST /api/jobs/{id}/cancel     -> { ok: true }
    GET  /api/download/{id}        -> the "extracted" payload from a solved crack
"""
import json
import sys
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# How long (seconds) a detect/crack job "runs" before finishing.
JOB_DURATION = 5.0

WORDLISTS = ["rockyou.txt", "fasttrack.txt", "common-passwords.txt"]

# job_id -> dict(type, start, cancelled, done)
JOBS = {}


# ---------------------------------------------------------------- multipart --
def parse_multipart(body, content_type):
    """Minimal multipart/form-data parser.

    Returns (fields, files) where fields maps name->str for text parts and
    files maps name->(filename, bytes) for file parts. Good enough for a mock;
    not hardened for production.
    """
    fields, files = {}, {}
    marker = "boundary="
    if marker not in content_type:
        return fields, files
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    sep = b"--" + boundary.encode()
    for part in body.split(sep):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, data = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", "replace")
        disp = next((ln for ln in headers.split("\r\n")
                     if ln.lower().startswith("content-disposition")), "")
        name = _param(disp, "name")
        filename = _param(disp, "filename")
        if name is None:
            continue
        if filename is not None:
            files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def _param(header, key):
    token = f'{key}="'
    if token not in header:
        return None
    return header.split(token, 1)[1].split('"', 1)[0]


# --------------------------------------------------------------- job helpers --
def job_view(job):
    """Compute the current state of a job for a poll response."""
    if job["cancelled"]:
        return {"state": "cancelled"}
    elapsed = time.time() - job["start"]
    pct = int(min(100, elapsed / JOB_DURATION * 100))
    if pct < 100:
        state = "running" if elapsed > 0.3 else "queued"
        return {"state": state, "percent": pct}
    # Finished — canned results per job type.
    if job["type"] == "detect":
        return {"state": "done", "result": "found"}  # -> "Hidden data likely present."
    # crack
    return {
        "state": "done",
        "result": "found",
        "passphrase": "hunter2",
        "download": f"/api/download/{job['id']}",
    }


# ------------------------------------------------------------------- handler --
class Handler(SimpleHTTPRequestHandler):
    # Quieter logging.
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # ---- helpers ----
    def _json(self, obj, status=200):
        payload = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _blob(self, data, filename, ctype="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _api_key(self):
        return self.headers.get("X-API-Key", "").strip()

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/wordlists":
            return self._json(WORDLISTS)
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[1]
            job = JOBS.get(job_id)
            if not job:
                return self._json({"detail": "unknown job"}, 404)
            return self._json(dict(job_view(job), job_id=job_id))
        if path.startswith("/api/download/"):
            job_id = path.rsplit("/", 1)[1]
            job = JOBS.get(job_id)
            if not job or job["type"] != "crack":
                return self._json({"detail": "nothing to download"}, 404)
            body = b"MOCK EXTRACTED PAYLOAD\nRecovered from a cracked stego file.\n"
            return self._blob(body, "extracted.txt", "text/plain")
        # Fall back to static file serving.
        return super().do_GET()

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()
        ctype = self.headers.get("Content-Type", "")

        if path == "/api/embed":
            fields, files = parse_multipart(body, ctype)
            if "cover" not in files or "secret" not in files:
                return self._json({"detail": "cover and secret files are required"}, 400)
            cover_name, cover_bytes = files["cover"]
            # Pretend we embedded: hand back the cover bytes plus a marker.
            stego = cover_bytes + b"\x00MOCK-STEGO\x00"
            return self._blob(stego, "stego_" + cover_name)

        if path == "/api/extract":
            fields, files = parse_multipart(body, ctype)
            if "stego" not in files:
                return self._json({"detail": "stego file is required"}, 400)
            if not fields.get("passphrase"):
                # Realistic failure path the GUI will surface as an error.
                return self._json({"detail": "wrong passphrase or no embedded data"}, 422)
            payload = b"MOCK EXTRACTED PAYLOAD\nThis is the hidden file contents.\n"
            return self._blob(payload, "extracted.bin")

        if path == "/api/detect":
            return self._start_job("detect")

        if path == "/api/crack":
            if not self._api_key():
                return self._json({"detail": "API key required (X-API-Key header)"}, 401)
            return self._start_job("crack")

        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path.split("/")[3]
            job = JOBS.get(job_id)
            if not job:
                return self._json({"detail": "unknown job"}, 404)
            job["cancelled"] = True
            return self._json({"ok": True})

        return self._json({"detail": "not found"}, 404)

    def _start_job(self, kind):
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "type": kind, "start": time.time(),
                        "cancelled": False}
        return self._json({"job_id": job_id})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"StegApp mock running at http://localhost:{port}/")
    print("  (serving static files + faked /api/* — Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
