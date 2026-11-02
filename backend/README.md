# StegApp backend (FastAPI + steghide/stegseek)

Wraps the Kali command-line tools behind the HTTP API the frontend expects, and
serves the frontend too (so it's all one origin).

## Requirements

- Python 3.10+
- **steghide** and **stegseek** on PATH — these are Linux tools. Run this backend
  on **Kali** (or WSL/Debian): `sudo apt install steghide stegseek`.
  On Windows the server still starts, but embed/extract/detect/crack return
  HTTP 503 ("tool not installed") until the tools are present.

## Install & run

```sh
cd backend
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
uvicorn app:app --reload --port 8080
```

Open http://localhost:8080/ — the frontend is served from the same server.

## Configuration (environment variables)

| Variable                | Default            | Purpose                                   |
|-------------------------|--------------------|-------------------------------------------|
| `STEGAPP_API_KEY`       | *(unset)*          | If set, /api/crack requires this exact key. Unset = any non-empty key. |
| `STEGAPP_WORDLIST_DIR`  | *(unset)*          | Extra directory to search for wordlists.  |
| `STEGAPP_WORK_DIR`      | `backend/work`     | Scratch space for uploads & extracted files. |
| `STEGHIDE_BIN`          | `steghide`         | Path to the steghide binary.              |
| `STEGSEEK_BIN`          | `stegseek`         | Path to the stegseek binary.              |

Wordlists are read from `backend/wordlists/` and (if present) `/usr/share/wordlists/`.
A small `sample.txt` is bundled; drop `rockyou.txt` into either dir for real use.

## Notes & limitations

- **Detect** uses `stegseek --seed`, which recovers steghide's per-file seed. A
  found seed strongly implies embedded data, but it's a heuristic, not proof.
- **Passphrases** are passed to steghide via `-p`, so they are briefly visible
  in the process list on the host. Acceptable for a single-user lab tool.
- Jobs are stored in memory and reset on restart. Fine for one host; not clustered.
- Bind to localhost for local use. Don't expose this to the internet as-is.
