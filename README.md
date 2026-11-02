# StegApp — Image Steganography Toolkit

A small web front end for steganographic operations on image (and audio) files.
Each operation has its own page and calls a server-side API that wraps Kali
steganography utilities (e.g. steghide / stegseek / stegdetect).

## Operations

| Page           | Action                                                             |
|----------------|-------------------------------------------------------------------|
| `embed.html`   | Hide a secret file inside a cover carrier, optional passphrase.    |
| `extract.html` | Recover a hidden payload from a stego file using its passphrase.   |
| `detect.html`  | Scan a file for signs of embedded content.                        |
| `crack.html`   | Run a wordlist against a stego file to recover an unknown passphrase. |

## Files

- `index.html` — landing page with links to each operation
- `embed.html` / `extract.html` / `detect.html` / `crack.html` — operation pages
- `common.js` — shared fetch / job-polling / download logic
- `style.css` — shared styling (light/dark, responsive)
- `mock_api.py` — stdlib-only mock backend for local testing (fakes all `/api/*` routes)

## Run locally against the mock backend

```sh
python mock_api.py          # serves the UI + fake API at http://localhost:8080
```

Open http://localhost:8080/ and click through the pages. On the Crack page, put
any value in the API key field (top right) — an empty key returns 401 by design.

> The mock never runs real steganography; it returns canned results so the UI
> can be exercised end to end. Point `common.js`'s `/api/*` calls at the real
> Kali backend when it's ready (same origin, or configure CORS).

## API contract

```
GET  /api/wordlists            -> ["rockyou.txt", ...]
POST /api/embed    (multipart) -> file blob
POST /api/extract  (multipart) -> file blob
POST /api/detect   (multipart) -> { job_id }   then poll
POST /api/crack    (multipart) -> { job_id }   then poll (needs X-API-Key)
GET  /api/jobs/{id}            -> { state, percent?, result?, passphrase?, download? }
POST /api/jobs/{id}/cancel     -> { ok: true }
GET  /api/download/{id}        -> extracted payload from a solved crack
```
