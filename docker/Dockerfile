# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build stegseek from source.
# Upstream ships no Debian package, so we compile the release tarball. Stegseek
# vendors its own steghide fork, hence the libmcrypt/libmhash/libjpeg deps.
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS stegseek-build

ARG STEGSEEK_VERSION=0.6

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ca-certificates \
        curl \
        libmcrypt-dev \
        libmhash-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl -fsSL "https://github.com/RickdeJager/stegseek/archive/refs/tags/v${STEGSEEK_VERSION}.tar.gz" \
      -o stegseek.tar.gz \
 && tar -xzf stegseek.tar.gz --strip-components=1 \
 && rm stegseek.tar.gz

RUN cmake -DCMAKE_BUILD_TYPE=Release -S . -B build \
 && cmake --build build -j "$(nproc)" \
 && strip build/stegseek \
 && build/stegseek --version

# ---------------------------------------------------------------------------
# Stage 2: runtime — steghide from apt, stegseek from stage 1, plus the app.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        steghide \
        libmcrypt4 \
        libmhash2 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=stegseek-build /src/build/stegseek /usr/local/bin/stegseek

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
