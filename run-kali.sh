#!/usr/bin/env bash
#
# run-kali.sh — one-command demo launcher for the StegApp backend on Kali.
#
# Starts the FastAPI backend (steghide/stegseek) locally and exposes it over a
# free Cloudflare "quick tunnel" (temporary https URL, no account needed), then
# prints the public URL and API key to paste into the Render-hosted frontend:
#   - Backend URL box -> the https://...trycloudflare.com URL printed below
#   - API key box     -> the key printed below
#
# The backend and the tunnel run independently: if the tunnel drops, it is
# restarted automatically and the new URL is reprinted (the backend keeps
# running the whole time). Ctrl+C stops both.
#
# Usage:
#   ./run-kali.sh                       # random API key, CORS open (demo)
#   STEGAPP_API_KEY=demo ./run-kali.sh  # pin a known key
#
# Requirements: python3, and cloudflared (the script offers to install it).
set -uo pipefail

PORT=8080
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$HERE/backend"
TARGET="http://127.0.0.1:$PORT"      # 127.0.0.1, not "localhost", to avoid IPv6

# --- API key: use the one from the environment, or generate a short random one.
API_KEY="${STEGAPP_API_KEY:-$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)}"
export STEGAPP_API_KEY="$API_KEY"
# Open CORS is fine for a short-lived demo. Lock it down by exporting
# STEGAPP_CORS_ORIGINS=https://your-app.onrender.com before running.
export STEGAPP_CORS_ORIGINS="${STEGAPP_CORS_ORIGINS:-*}"

# The Render-hosted frontend. Used to build a one-click "configure" link that
# fills in the backend URL + API key with no typing. Override if your URL
# differs:  STEGAPP_FRONTEND_URL=https://your-app.onrender.com ./run-kali.sh
FRONTEND_URL="${STEGAPP_FRONTEND_URL:-https://seniorproject-pr8l.onrender.com}"
FRONTEND_URL="${FRONTEND_URL%/}"

# --- Ensure cloudflared is present (install the .deb if not). ----------------
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Installing it (needs sudo)..."
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/cloudflared.deb" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i "$tmp/cloudflared.deb"
  rm -rf "$tmp"
fi

# --- Python venv + deps. Create the venv if missing, and (re)install deps if
#     the key packages aren't importable — this covers a half-built venv from
#     an interrupted earlier run. ------------------------------------------------
cd "$BACKEND"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import uvicorn, fastapi, multipart" 2>/dev/null; then
  echo "Installing dependencies..."
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

UV_LOG="$(mktemp)"
CF_LOG="$(mktemp)"
UV_PID=""
CF_PID=""
PUBLIC_URL=""

cleanup() {
  echo
  echo "Shutting down..."
  [ -n "$CF_PID" ] && kill "$CF_PID" 2>/dev/null
  [ -n "$UV_PID" ] && kill "$UV_PID" 2>/dev/null
  rm -f "$UV_LOG" "$CF_LOG"
}
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

banner() {
  echo
  echo "=================================================================="
  echo "  Backend is live. Open this link to auto-configure the frontend"
  echo "  (no typing needed):"
  echo
  echo "    ${FRONTEND_URL}/#backend=${PUBLIC_URL}&key=${API_KEY}"
  echo
  echo "  Or enter these manually in the StegApp top bar:"
  echo "    Backend URL :  $PUBLIC_URL"
  echo "    API key     :  $API_KEY"
  echo
  echo "  Leave this terminal open during the demo. Ctrl+C to stop."
  echo "=================================================================="
}

# --- Start the backend (bound to localhost; the tunnel exposes it). ----------
echo "Starting backend on 127.0.0.1:$PORT ..."
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT" >"$UV_LOG" 2>&1 &
UV_PID=$!

for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "$TARGET/api/health" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$UV_PID" 2>/dev/null; then
    echo "Backend failed to start:"; cat "$UV_LOG"; exit 1
  fi
  sleep 1
done

# --- (Re)start the quick tunnel and capture its public URL. ------------------
start_tunnel() {
  : >"$CF_LOG"
  cloudflared tunnel --url "$TARGET" --no-autoupdate >"$CF_LOG" 2>&1 &
  CF_PID=$!
  PUBLIC_URL=""
  for _ in $(seq 1 30); do
    PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" | head -n1)"
    [ -n "$PUBLIC_URL" ] && break
    kill -0 "$CF_PID" 2>/dev/null || break
    sleep 1
  done
}

echo "Opening Cloudflare quick tunnel ..."
start_tunnel
[ -n "$PUBLIC_URL" ] && banner || echo "Tunnel URL not detected yet; see $CF_LOG"

# --- Supervise: keep the backend as the primary; auto-restart the tunnel if it
#     drops (the backend keeps running), and reprint the new URL. --------------
while true; do
  if ! kill -0 "$UV_PID" 2>/dev/null; then
    echo "Backend stopped unexpectedly:"; tail -n 20 "$UV_LOG"; exit 1
  fi
  if ! kill -0 "$CF_PID" 2>/dev/null; then
    echo "Tunnel dropped — restarting it (backend still up)..."
    start_tunnel
    if [ -n "$PUBLIC_URL" ]; then
      echo "New tunnel URL — update the Backend URL box in Render:"
      banner
    fi
  fi
  sleep 3
done
