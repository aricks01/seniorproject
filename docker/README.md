# Running StegApp with Docker

Everything needed to build and run is in this folder. `steghide` comes from
apt; `stegseek` has no package, so the Dockerfile compiles it from source
(multi-stage, so the compiler never ships in the final image).

## Quick start (Kali)

```sh
git clone <this-repo>
cd <repo>/docker
docker compose up --build
```

Open <http://localhost:8080/>. The frontend and API are the same origin.

## Configuration

Optional — copy the env template and edit:

```sh
cp .env.example .env
```

| Variable            | Effect                                                      |
|---------------------|------------------------------------------------------------|
| `STEGAPP_API_KEY`   | Require this exact `X-API-Key` on `/api/crack`. Blank = any non-empty key (dev). |
| `STEGSEEK_VERSION`  | stegseek release compiled in the build stage (default 0.6). |

## Wordlists

- The bundled `backend/wordlists/sample.txt` is baked into the image.
- `docker-compose.yml` bind-mounts the host's `/usr/share/wordlists` read-only,
  so Kali's lists appear automatically. On a host without that directory,
  comment that line out or the container won't start.
- Note: the backend lists only `.txt`/`.lst` wordlists, so Kali's gzipped
  `rockyou.txt.gz` won't appear until you `gunzip` it.

## Data

Uploads and extracted payloads live in the `stegapp-data` volume (mounted at
`/data`). Remove it with `docker compose down -v`.

## Not on Kali?

The image is pure Debian, so it runs anywhere Docker does — you don't need a
Kali host. Just drop the `/usr/share/wordlists` mount if that path is absent.
