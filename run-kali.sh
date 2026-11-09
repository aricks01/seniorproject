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
# Usage:
#   ./run-kali.sh                 # random API key, CORS open (fine for a demo)
#   STEGAPP_API_KEY=demo ./run-kali.sh    # pin a known key
#
# Ctrl+C stops both the backend and the tunnel.
#
# Requirements: python3, and cloudflared (the script offers to install it).
set -euo pipefail

PORT=8080
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$HERE/backend"

# --- API key: use the one from the environment, or generate a short random one.
API_KEY="${STEGAPP_API_KEY:-$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)}"
export STEGAPP_API_KEY="$API_KEY"
# Open CORS is fine for a short-lived demo. Lock it down by exporting
# STEGAPP_CORS_ORIGINS=https://your-app.onrender.com before running.
export STEGAPP_CORS_ORIGINS="${STEGAPP_CORS_ORIGINS:-*}"

# --- Ensure cloudflared is present (install the .deb if not). ----------------
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Installing it (needs sudo)..."
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/cloudflared.deb" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i "$tmp/cloudflared.deb"
  rm -rf "$tmp"
fi

# --- Python venv + deps. -----------------------------------------------------
cd "$BACKEND"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtualenv and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

# --- Start the backend (bound to localhost; the tunnel exposes it). ----------
UV_LOG="$(mktemp)"
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT" >"$UV_LOG" 2>&1 &
UV_PID=$!

CF_LOG="$(mktemp)"
CF_PID=""
cleanup() {
  echo
  echo "Shutting down..."
  [ -n "$CF_PID" ] && kill "$CF_PID" 2>/dev/null || true
  kill "$UV_PID" 2>/dev/null || true
  rm -f "$UV_LOG" "$CF_LOG"
}
trap cleanup EXIT INT TERM

# Wait for the backend to answer before tunneling.
echo "Starting backend on 127.0.0.1:$PORT ..."
for i in $(seq 1 20); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$UV_PID" 2>/dev/null; then
    echo "Backend failed to start:"; cat "$UV_LOG"; exit 1
  fi
  sleep 1
done

# --- Start the quick tunnel and capture its public URL. ----------------------
echo "Opening Cloudflare quick tunnel ..."
cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate >"$CF_LOG" 2>&1 &
CF_PID=$!

PUBLIC_URL=""
for i in $(seq 1 30); do
  PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" | head -n1 || true)"
  [ -n "$PUBLIC_URL" ] && break
  if ! kill -0 "$CF_PID" 2>/dev/null; then
    echo "Tunnel failed to start:"; cat "$CF_LOG"; exit 1
  fi
  sleep 1
done

echo
echo "=================================================================="
if [ -n "$PUBLIC_URL" ]; then
  echo "  Backend is live. In the Render-hosted StegApp page, enter:"
  echo
  echo "    Backend URL :  $PUBLIC_URL"
  echo "    API key     :  $API_KEY"
else
  echo "  Tunnel started but the URL wasn't detected. Check it here:"
  echo "    $CF_LOG"
  echo "    API key     :  $API_KEY"
fi
echo
echo "  Leave this terminal open during the demo. Ctrl+C to stop."
echo "=================================================================="

# Keep running until Ctrl+C; surface tunnel output if it dies.
wait "$CF_PID"
