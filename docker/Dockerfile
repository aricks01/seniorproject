# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Runtime: steghide + stegseek from apt, plus the app.
#
# Stegseek ships a prebuilt Debian package on its GitHub releases, so we install
# that instead of compiling from source. apt resolves its libmcrypt/libmhash/
# libjpeg dependencies automatically.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ARG STEGSEEK_VERSION=0.6

# Fetch the stegseek .deb (ADD needs no curl in the image).
ADD https://github.com/RickdeJager/stegseek/releases/download/v${STEGSEEK_VERSION}/stegseek_${STEGSEEK_VERSION}-1.deb /tmp/stegseek.deb

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        steghide \
        /tmp/stegseek.deb \
 && rm -f /tmp/stegseek.deb \
 && rm -rf /var/lib/apt/lists/*

# Fail the build rather than the first request if either tool is unusable.
RUN steghide --version && stegseek --version

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# config.FRONTEND_DIR is backend/'s parent, so the static files land in /app.
COPY backend/ backend/
COPY *.html common.js style.css ./

# Scratch space for uploads and extracted payloads; mount a volume here to keep
# it off the container's writable layer.
ENV STEGAPP_WORK_DIR=/data/work
RUN useradd --create-home --uid 10001 stegapp \
 && mkdir -p /data/work \
 && chown -R stegapp:stegapp /data
VOLUME ["/data"]

USER stegapp
WORKDIR /app/backend
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/wordlists', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
